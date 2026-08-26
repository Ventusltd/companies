#!/usr/bin/env python3
"""Acquire official Companies House bulk files with immutable provenance."""
from __future__ import annotations
import argparse, hashlib, json, re, sys, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
import requests

BASIC_PAGE = "https://download.companieshouse.gov.uk/en_output.html"
DAILY_ACCOUNTS_PAGE = "https://download.companieshouse.gov.uk/en_accountsdata.html"
MONTHLY_ACCOUNTS_PAGE = "https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html"
UA = "Ventus-PipelineNews/1.0 (+https://github.com/Ventusltd/pipelinenews)"

def links(page: str, pattern: str) -> list[str]:
    response = requests.get(page, headers={"User-Agent": UA}, timeout=90)
    response.raise_for_status()
    found = re.findall(r'href=["\']([^"\']+\.zip)["\']', response.text, re.I)
    return sorted({urllib.parse.urljoin(page, x) for x in found if re.search(pattern, x, re.I)})

def latest_basic() -> list[str]:
    candidates = links(BASIC_PAGE, r"BasicCompanyData")
    if not candidates:
        raise RuntimeError("No official basic-company ZIP links discovered")
    dated = [(re.search(r"(20\d{2}-\d{2}-\d{2})", x), x) for x in candidates]
    dates = [m.group(1) for m, _ in dated if m]
    if not dates:
        return candidates
    latest = max(dates)
    current = [x for m, x in dated if m and m.group(1) == latest]
    one_file = [x for x in current if "asonefile" in x.lower()]
    return one_file[:1] if one_file else current

def latest_daily_accounts(count: int) -> list[str]:
    candidates = links(DAILY_ACCOUNTS_PAGE, r"Accounts[_-]Bulk[_-]Data")
    return candidates[-count:] if count else []

def latest_monthly_accounts(count: int) -> list[str]:
    candidates = links(MONTHLY_ACCOUNTS_PAGE, r"Accounts[_-]Monthly[_-]Data")
    if not candidates:
        raise RuntimeError("No official monthly accounts ZIP links discovered")
    return candidates[-count:] if count else []

def download(url: str, directory: Path) -> dict:
    name = Path(urllib.parse.urlparse(url).path).name
    target = directory / name
    digest = hashlib.sha256()
    size = 0
    with requests.get(url, headers={"User-Agent": UA}, timeout=(30, 300), stream=True) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk); digest.update(chunk); size += len(chunk)
    if size < 1024:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Unexpectedly small download: {url}")
    return {"url": url, "filename": name, "bytes": size, "sha256": digest.hexdigest()}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--basic-url", action="append", default=[])
    parser.add_argument("--accounts-url", action="append", default=[])
    parser.add_argument("--latest-daily-accounts", type=int, default=0)
    parser.add_argument("--list-monthly-output")
    parser.add_argument("--latest-monthly-count", type=int, default=12)
    parser.add_argument("--skip-basic", action="store_true")
    args = parser.parse_args()
    if args.list_monthly_output:
        urls = latest_monthly_accounts(args.latest_monthly_count)
        Path(args.list_monthly_output).write_text(json.dumps(urls, separators=(",", ":")) + "\n")
        print(json.dumps({"monthly_urls": len(urls)}))
        return 0
    out = Path(args.output); raw = out / "raw"; raw.mkdir(parents=True, exist_ok=True)
    basic = [] if args.skip_basic else (args.basic_url or latest_basic())
    accounts = args.accounts_url or latest_daily_accounts(args.latest_daily_accounts)
    records = [download(url, raw) for url in [*basic, *accounts]]
    manifest = {
        "schema": "companies-house-source-manifest-v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "official_pages": [BASIC_PAGE, DAILY_ACCOUNTS_PAGE, MONTHLY_ACCOUNTS_PAGE],
        "basic_files": [x for x in records if "basiccompanydata" in x["filename"].lower()],
        "accounts_files": [x for x in records if "account" in x["filename"].lower()],
    }
    if not args.skip_basic and not manifest["basic_files"]:
        raise RuntimeError("Basic-company snapshot is mandatory")
    (out / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"basic": len(manifest["basic_files"]), "accounts": len(manifest["accounts_files"])}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
