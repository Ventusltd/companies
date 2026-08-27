#!/usr/bin/env python3
"""Fail-closed size and provenance plan for official Companies House archives."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

OFFICIAL_HOST = "download.companieshouse.gov.uk"
UA = "Ventus-PipelineNews/1.0 (+https://github.com/Ventusltd/pipelinenews)"


def require_official(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != OFFICIAL_HOST or not parsed.path.endswith(".zip"):
        raise RuntimeError(f"Not an official Companies House ZIP URL: {url}")
    if parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port:
        raise RuntimeError(f"Unexpected URL components: {url}")


def probe(url: str, session=requests) -> dict:
    require_official(url)
    response = session.head(
        url,
        headers={"User-Agent": UA},
        timeout=(15, 45),
        allow_redirects=True,
    )
    response.raise_for_status()
    require_official(response.url)
    size_text = response.headers.get("Content-Length", "")
    if not size_text.isdigit() or int(size_text) < 1024:
        raise RuntimeError(f"Missing or implausible Content-Length for {url}")
    return {
        "url": url,
        "resolved_url": response.url,
        "filename": Path(urllib.parse.urlparse(response.url).path).name,
        "bytes": int(size_text),
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
    }


def load_urls(path: Path, kind: str) -> list[tuple[str, str]]:
    value = json.loads(path.read_text())
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"{kind} URL list is empty or malformed")
    rows = []
    for url in value:
        if not isinstance(url, str):
            raise RuntimeError(f"{kind} URL is not a string")
        require_official(url)
        rows.append((kind, url))
    return rows


def build_plan(rows: list[tuple[str, str]], maximum_total_bytes: int, session=requests) -> dict:
    if maximum_total_bytes < 1024:
        raise RuntimeError("Maximum total bytes is implausibly small")
    urls = [url for _, url in rows]
    if len(urls) != len(set(urls)):
        raise RuntimeError("Duplicate archive URL in download closure")
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(rows))) as executor:
        futures = [executor.submit(probe, url, session) for _, url in rows]
        files = []
        for (kind, _), future in zip(rows, futures):
            files.append({"kind": kind, **future.result()})
    total = sum(item["bytes"] for item in files)
    if total > maximum_total_bytes:
        raise RuntimeError(
            f"Planned download closure is {total} bytes; budget is {maximum_total_bytes} bytes"
        )
    return {
        "schema": "companies-house-download-plan-v1",
        "planned_at": datetime.now(timezone.utc).isoformat(),
        "official_host": OFFICIAL_HOST,
        "maximum_total_bytes": maximum_total_bytes,
        "total_bytes": total,
        "file_count": len(files),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts-urls", required=True, type=Path)
    parser.add_argument("--basic-urls", required=True, type=Path)
    parser.add_argument("--maximum-total-bytes", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        rows = load_urls(args.accounts_urls, "accounts") + load_urls(args.basic_urls, "basic")
        plan = build_plan(rows, args.maximum_total_bytes)
        args.output.write_text(json.dumps(plan, indent=2) + "\n")
        print(json.dumps({
            "status": "PASS",
            "files": plan["file_count"],
            "total_bytes": plan["total_bytes"],
            "maximum_total_bytes": plan["maximum_total_bytes"],
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
