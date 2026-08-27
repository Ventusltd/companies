#!/usr/bin/env python3
"""Freeze a small, official Companies House download closure before acquisition."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

GENERATION = "202608271507"
BASE_COMMIT = "145da3dc6ff7541edb008676528636c11ba428ee"
OFFICIAL_HOST = "download.companieshouse.gov.uk"
REST_HOST = "api.company-information.service.gov.uk"
REST_PROBE_PATH = "/company/00000006"
MONTHLY_PAGE = "https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html"
BASIC_PAGE = "https://download.companieshouse.gov.uk/en_output.html"
ACCOUNT_MONTHS = 3
FILE_LIMIT = 4
MAXIMUM_TOTAL_BYTES = 12_000_000_000
MAXIMUM_ARCHIVE_BYTES = 4_000_000_000
MAXIMUM_PAGE_BYTES = 2_000_000
MAXIMUM_REST_RESPONSE_BYTES = 1_000_000
CONNECT_TIMEOUT_SECONDS = 15
READ_TIMEOUT_SECONDS = 45
USER_AGENT = "Ventus-Companies/202608271507 (+https://github.com/Ventusltd/companies)"
REDIRECT_CODES = {301, 302, 303, 307, 308}
OGL = {
    "name": "Open Government Licence v3.0",
    "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    "attribution": "Contains public sector information licensed under the Open Government Licence v3.0. Source: Companies House.",
    "rights_caveat": "OGL applies to Crown copyright material; third-party rights and data-protection duties may still apply.",
    "accuracy_caveat": "Companies House records what was filed; it does not verify every filed statement.",
}


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def require_official(url: str, *, suffix: str | None = None) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != OFFICIAL_HOST
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(f"URL is outside the official Companies House boundary: {url}")
    if (
        not parsed.path.startswith("/")
        or urllib.parse.unquote(parsed.path) != parsed.path
        or "\\" in parsed.path
        or ".." in PurePosixPath(parsed.path).parts
    ):
        raise RuntimeError(f"Unsafe official URL path: {url}")
    if suffix and not parsed.path.lower().endswith(suffix.lower()):
        raise RuntimeError(f"Official URL has the wrong suffix: {url}")
    return parsed


def _one_request(method: str, url: str, body_limit: int = 0) -> tuple[int, dict[str, str], bytes]:
    parsed = require_official(url)
    connection = http.client.HTTPSConnection(
        OFFICIAL_HOST,
        timeout=CONNECT_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            method,
            parsed.path,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", "Connection": "close"},
        )
        response = connection.getresponse()
        if connection.sock:
            connection.sock.settimeout(READ_TIMEOUT_SECONDS)
        headers = {key.lower(): value.strip() for key, value in response.getheaders()}
        if body_limit:
            body = response.read(body_limit + 1)
            if len(body) > body_limit:
                raise RuntimeError(f"Official index exceeded {body_limit} bytes: {url}")
        else:
            body = b""
        return response.status, headers, body
    finally:
        connection.close()


def request_bounded(method: str, url: str, body_limit: int = 0) -> tuple[str, dict[str, str], bytes]:
    require_official(url)
    current = url
    for redirect_count in range(2):
        status, headers, body = _one_request(method, current, body_limit)
        if status in REDIRECT_CODES:
            if redirect_count:
                raise RuntimeError(f"More than one redirect for official resource: {url}")
            location = headers.get("location")
            if not location:
                raise RuntimeError(f"Redirect lacked Location: {url}")
            current = urllib.parse.urljoin(current, location)
            require_official(current)
            continue
        if status != 200:
            raise RuntimeError(f"Official resource returned HTTP {status}: {url}")
        return current, headers, body
    raise RuntimeError(f"Redirect closure failed: {url}")


def discover(page: str, pattern: re.Pattern[str]) -> list[str]:
    resolved, _headers, body = request_bounded("GET", page, MAXIMUM_PAGE_BYTES)
    parser = LinkParser()
    parser.feed(body.decode("utf-8", errors="strict"))
    found = set()
    for link in parser.links:
        url = urllib.parse.urljoin(resolved, link)
        try:
            require_official(url, suffix=".zip")
        except RuntimeError:
            continue
        if pattern.search(PurePosixPath(urllib.parse.urlsplit(url).path).name):
            found.add(url)
    if not found:
        raise RuntimeError(f"No matching official ZIP links discovered at {page}")
    return sorted(found)


def monthly_period(url: str) -> tuple[int, int]:
    name = PurePosixPath(urllib.parse.urlsplit(url).path).name
    match = re.search(r"-([A-Za-z]+)(20\d{2})\.zip$", name)
    if not match:
        raise RuntimeError(f"Monthly archive lacks a parseable period: {name}")
    month = datetime.strptime(match.group(1), "%B").month
    return int(match.group(2)), month


def basic_period(url: str) -> tuple[int, int, int, int]:
    name = PurePosixPath(urllib.parse.urlsplit(url).path).name
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", name)
    if not match:
        return (0, 0, 0, int("asonefile" in name.lower()))
    return (*map(int, match.groups()), int("asonefile" in name.lower()))


def probe(kind_url: tuple[str, str]) -> dict:
    kind, url = kind_url
    resolved, headers, _body = request_bounded("HEAD", url)
    require_official(resolved, suffix=".zip")
    length = headers.get("content-length", "")
    if not length.isdigit() or int(length) < 1024:
        raise RuntimeError(f"Missing or implausible Content-Length: {url}")
    etag = headers.get("etag", "")
    modified = headers.get("last-modified", "")
    if not etag or not modified:
        raise RuntimeError(f"ETag and Last-Modified are required for the frozen closure: {url}")
    return {
        "kind": kind,
        "url": url,
        "resolved_url": resolved,
        "filename": PurePosixPath(urllib.parse.urlsplit(resolved).path).name,
        "bytes": int(length),
        "etag": etag,
        "last_modified": modified,
    }


def _rate_reset_delay(headers: dict[str, str]) -> float:
    """Return a server-header-derived wait; never invent a fixed polling delay."""
    reset = headers.get("x-ratelimit-reset", "")
    if not reset.isdigit():
        raise RuntimeError("Companies House REST rate response lacked X-Ratelimit-Reset")
    reset_value = int(reset)
    now = time.time()
    # Companies House documents this as an epoch, but tolerate a bounded seconds value.
    delay = reset_value - now if reset_value > 1_000_000_000 else reset_value
    if delay < 0:
        return 0
    if delay > 305:
        raise RuntimeError("Companies House REST reset exceeded the five-minute boundary")
    return delay + 1


def _rest_once(api_key: str) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPSConnection(
        REST_HOST,
        timeout=CONNECT_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    token = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    try:
        connection.request(
            "GET",
            REST_PROBE_PATH,
            headers={
                "Authorization": f"Basic {token}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        if connection.sock:
            connection.sock.settimeout(READ_TIMEOUT_SECONDS)
        headers = {key.lower(): value.strip() for key, value in response.getheaders()}
        body = response.read(MAXIMUM_REST_RESPONSE_BYTES + 1)
        if len(body) > MAXIMUM_REST_RESPONSE_BYTES:
            raise RuntimeError("Companies House REST probe exceeded its response ceiling")
        return response.status, headers, body
    finally:
        connection.close()


def optional_rest_evidence(output: Path) -> dict:
    """Validate optional credentials once and retain no company payload or secret."""
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
    evidence = {
        "schema": "companies-house-optional-rest-evidence-v1",
        "generation": GENERATION,
        "endpoint": f"https://{REST_HOST}{REST_PROBE_PATH}",
        "enabled": bool(api_key),
    }
    if not api_key:
        evidence.update({"status": "SKIPPED", "reason": "optional-secret-not-configured"})
    else:
        status, headers, _body = _rest_once(api_key)
        if status == 429:
            time.sleep(_rate_reset_delay(headers))
            status, headers, _body = _rest_once(api_key)
        if status != 200:
            # Deliberately omit response bodies and authentication material from errors.
            raise RuntimeError(f"Companies House REST credential probe returned HTTP {status}")
        limit = headers.get("x-ratelimit-limit", "")
        remaining = headers.get("x-ratelimit-remain", "")
        reset = headers.get("x-ratelimit-reset", "")
        window = headers.get("x-ratelimit-window", "")
        if not limit.isdigit() or not remaining.isdigit() or not reset.isdigit():
            raise RuntimeError("Companies House REST response lacked numeric rate-limit headers")
        evidence.update(
            {
                "status": "PASS",
                "rate_limit": int(limit),
                "rate_remaining": int(remaining),
                "rate_reset": int(reset),
                "rate_window": window,
                "response_body_retained": False,
                "credential_retained": False,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def build_plan(monthly_urls: list[str], basic_urls: list[str]) -> dict:
    monthly = sorted(monthly_urls, key=monthly_period)[-ACCOUNT_MONTHS:]
    if len(monthly) != ACCOUNT_MONTHS or len({monthly_period(url) for url in monthly}) != ACCOUNT_MONTHS:
        raise RuntimeError(f"Expected {ACCOUNT_MONTHS} distinct monthly archives")
    latest_basic = sorted(basic_urls, key=basic_period)[-1:]
    if len(latest_basic) != 1 or "asonefile" not in latest_basic[0].lower():
        raise RuntimeError("Expected one current BasicCompanyDataAsOneFile archive")
    rows = [("accounts", url) for url in monthly] + [("basic", latest_basic[0])]
    if len(rows) != FILE_LIMIT or len({url for _, url in rows}) != FILE_LIMIT:
        raise RuntimeError("Download closure must contain four distinct files")
    with concurrent.futures.ThreadPoolExecutor(max_workers=FILE_LIMIT) as executor:
        files = list(executor.map(probe, rows))
    if len({item["resolved_url"] for item in files}) != FILE_LIMIT or len({item["filename"] for item in files}) != FILE_LIMIT:
        raise RuntimeError("Official redirects collapsed the four-file closure")
    for item in files:
        if item["kind"] == "accounts":
            if monthly_period(item["url"]) != monthly_period(item["resolved_url"]):
                raise RuntimeError("An accounts redirect changed the selected month")
            if not re.search(r"Accounts[_-]Monthly[_-]Data", item["filename"], re.I):
                raise RuntimeError("An accounts redirect left the monthly archive family")
        else:
            if "basiccompanydata" not in item["filename"].lower() or "asonefile" not in item["filename"].lower():
                raise RuntimeError("The basic snapshot redirect left the one-file archive family")
            if basic_period(item["url"])[:3] != basic_period(item["resolved_url"])[:3]:
                raise RuntimeError("The basic snapshot redirect changed the selected date")
    if any(item["bytes"] > MAXIMUM_ARCHIVE_BYTES for item in files):
        raise RuntimeError(f"An archive exceeded the {MAXIMUM_ARCHIVE_BYTES}-byte per-file ceiling")
    total = sum(item["bytes"] for item in files)
    if total > MAXIMUM_TOTAL_BYTES:
        raise RuntimeError(f"Frozen closure is {total} bytes; ceiling is {MAXIMUM_TOTAL_BYTES}")
    return {
        "schema": "companies-house-bounded-download-plan-v1",
        "generation": GENERATION,
        "base_commit": BASE_COMMIT,
        "deployment_state": "not-authorised",
        "planned_at": datetime.now(timezone.utc).isoformat(),
        "official_host": OFFICIAL_HOST,
        "accounts_months": ACCOUNT_MONTHS,
        "file_limit": FILE_LIMIT,
        "maximum_archive_bytes": MAXIMUM_ARCHIVE_BYTES,
        "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
        "total_bytes": total,
        "files": files,
        "licence": OGL,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rest-evidence", type=Path)
    args = parser.parse_args()
    try:
        monthly = discover(MONTHLY_PAGE, re.compile(r"Accounts[_-]Monthly[_-]Data", re.I))
        basic = discover(BASIC_PAGE, re.compile(r"BasicCompanyData", re.I))
        plan = build_plan(monthly, basic)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        if args.rest_evidence:
            optional_rest_evidence(args.rest_evidence)
        print(json.dumps({"status": "PASS", "files": len(plan["files"]), "bytes": plan["total_bytes"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
