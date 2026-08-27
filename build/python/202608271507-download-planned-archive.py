#!/usr/bin/env python3
"""Download one member of a preflight-frozen Companies House closure."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import ssl
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

GENERATION = "202608271507"
BASE_COMMIT = "145da3dc6ff7541edb008676528636c11ba428ee"
OFFICIAL_HOST = "download.companieshouse.gov.uk"
MAXIMUM_TOTAL_BYTES = 12_000_000_000
MAXIMUM_ARCHIVE_BYTES = 4_000_000_000
CONNECT_TIMEOUT_SECONDS = 15
READ_TIMEOUT_SECONDS = 300
USER_AGENT = "Ventus-Companies/202608271507 (+https://github.com/Ventusltd/companies)"
REDIRECT_CODES = {301, 302, 303, 307, 308}


def require_official(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != OFFICIAL_HOST
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
        or not parsed.path.lower().endswith(".zip")
        or urllib.parse.unquote(parsed.path) != parsed.path
        or "\\" in parsed.path
        or ".." in parsed.path.split("/")
    ):
        raise RuntimeError(f"Archive URL is outside the official Companies House boundary: {url}")
    return parsed


def open_once(url: str) -> tuple[http.client.HTTPSConnection, http.client.HTTPResponse]:
    parsed = require_official(url)
    connection = http.client.HTTPSConnection(
        OFFICIAL_HOST,
        timeout=CONNECT_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    connection.request(
        "GET",
        parsed.path,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", "Connection": "close"},
    )
    response = connection.getresponse()
    if connection.sock:
        connection.sock.settimeout(READ_TIMEOUT_SECONDS)
    return connection, response


def open_bounded(url: str) -> tuple[str, http.client.HTTPSConnection, http.client.HTTPResponse]:
    current = url
    for redirect_count in range(2):
        connection, response = open_once(current)
        if response.status in REDIRECT_CODES:
            location = response.getheader("Location")
            response.read(1024)
            connection.close()
            if redirect_count or not location:
                raise RuntimeError(f"Invalid redirect closure for archive: {url}")
            current = urllib.parse.urljoin(current, location)
            require_official(current)
            continue
        if response.status != 200:
            status = response.status
            connection.close()
            raise RuntimeError(f"Official archive returned HTTP {status}: {url}")
        return current, connection, response
    raise RuntimeError(f"Redirect closure failed: {url}")


def load_item(plan_path: Path, index: int) -> tuple[dict, dict]:
    plan = json.loads(plan_path.read_text())
    if plan.get("schema") != "companies-house-bounded-download-plan-v1":
        raise RuntimeError("Unexpected download-plan schema")
    if plan.get("generation") != GENERATION or plan.get("base_commit") != BASE_COMMIT:
        raise RuntimeError("Download plan is outside the fixed generation/source boundary")
    if plan.get("deployment_state") != "not-authorised":
        raise RuntimeError("Download plan is not quarantined")
    if plan.get("accounts_months") != 3 or plan.get("file_limit") != 4:
        raise RuntimeError("Download plan cardinality contract is invalid")
    files = plan.get("files")
    if not isinstance(files, list) or len(files) != 4:
        raise RuntimeError("Download plan must contain exactly four files")
    if (
        plan.get("maximum_total_bytes") != MAXIMUM_TOTAL_BYTES
        or plan.get("maximum_archive_bytes") != MAXIMUM_ARCHIVE_BYTES
        or plan.get("total_bytes", MAXIMUM_TOTAL_BYTES + 1) > MAXIMUM_TOTAL_BYTES
    ):
        raise RuntimeError("Download plan exceeds the fixed byte ceiling")
    if [item.get("kind") for item in files].count("accounts") != 3 or [item.get("kind") for item in files].count("basic") != 1:
        raise RuntimeError("Download plan kind closure is invalid")
    if len({str(item.get("url", "")) for item in files}) != 4:
        raise RuntimeError("Download plan contains duplicate archive URLs")
    planned_total = 0
    for planned in files:
        source = require_official(str(planned.get("url", "")))
        resolved = require_official(str(planned.get("resolved_url", "")))
        filename = str(planned.get("filename", ""))
        if (
            PurePosixPath(filename).name != filename
            or filename != PurePosixPath(resolved.path).name
            or not filename
            or "\x00" in filename
        ):
            raise RuntimeError("Download plan contains an unsafe archive filename")
        planned_bytes = planned.get("bytes")
        if not isinstance(planned_bytes, int) or planned_bytes < 1024 or planned_bytes > MAXIMUM_ARCHIVE_BYTES:
            raise RuntimeError("Planned archive byte count is invalid")
        if not planned.get("etag") or not planned.get("last_modified"):
            raise RuntimeError("Planned archive lacks frozen validator headers")
        if not source.path.lower().endswith(".zip"):
            raise RuntimeError("Planned source is not a ZIP archive")
        planned_total += planned_bytes
    if planned_total != plan.get("total_bytes"):
        raise RuntimeError("Download plan byte closure is inconsistent")
    if index < 0 or index >= len(files):
        raise RuntimeError("Planned archive index is out of range")
    item = files[index]
    if item.get("kind") not in {"accounts", "basic"}:
        raise RuntimeError("Unknown planned archive kind")
    require_official(str(item.get("url", "")))
    require_official(str(item.get("resolved_url", "")))
    return plan, item


def download(plan_path: Path, index: int, output: Path, receipt_path: Path) -> dict:
    plan, item = load_item(plan_path, index)
    final_url, connection, response = open_bounded(item["url"])
    try:
        require_official(final_url)
        if final_url != item["resolved_url"]:
            raise RuntimeError("Archive redirect target changed after preflight")
        headers = {key.lower(): value.strip() for key, value in response.getheaders()}
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise RuntimeError("Archive response used an unexpected Content-Encoding")
        length = headers.get("content-length", "")
        if not length.isdigit() or int(length) != item["bytes"]:
            raise RuntimeError("Archive Content-Length changed after preflight")
        if headers.get("etag") != item["etag"]:
            raise RuntimeError("Archive ETag changed after preflight")
        if headers.get("last-modified") != item["last_modified"]:
            raise RuntimeError("Archive Last-Modified changed after preflight")
        output.mkdir(parents=True, exist_ok=True)
        target = output / item["filename"]
        if target.resolve().parent != output.resolve():
            raise RuntimeError("Archive target escaped its output directory")
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > item["bytes"]:
                        raise RuntimeError("Archive exceeded its frozen byte count")
                    handle.write(chunk)
                    digest.update(chunk)
            if size != item["bytes"]:
                raise RuntimeError("Downloaded archive differs from its frozen byte count")
        except Exception:
            target.unlink(missing_ok=True)
            raise
    finally:
        connection.close()
    receipt = {
        "schema": "companies-house-bounded-download-receipt-v1",
        "generation": GENERATION,
        "base_commit": BASE_COMMIT,
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "index": index,
        "kind": item["kind"],
        "url": item["url"],
        "resolved_url": final_url,
        "filename": item["filename"],
        "bytes": size,
        "etag": item["etag"],
        "last_modified": item["last_modified"],
        "sha256": digest.hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--index", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    try:
        receipt = download(args.plan, args.index, args.output, args.receipt)
        print(json.dumps({"status": "PASS", "index": args.index, "bytes": receipt["bytes"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
