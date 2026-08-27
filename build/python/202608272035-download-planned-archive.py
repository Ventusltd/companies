#!/usr/bin/env python3
"""Download one exact 202608272035 Companies House archive with a fixed receipt."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

GENERATION = "202608272035"
BASE_COMMIT = "1f91f8efced903aa82e62acf56b9af2db476cfdb"
FIXED_GENERATED_AT = "2026-08-27T19:35:00Z"
PARENT = Path(__file__).with_name("202608271507-download-planned-archive.py")

spec = importlib.util.spec_from_file_location("companies_download_202608271507_for_2035", PARENT)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608271507 downloader")
PREVIOUS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREVIOUS)
PREVIOUS.GENERATION = GENERATION
PREVIOUS.BASE_COMMIT = BASE_COMMIT
PREVIOUS.USER_AGENT = "Ventus-Companies/202608272035 (+https://github.com/Ventusltd/companies)"

EXPECTED_FILES = (
    {
        "kind": "accounts",
        "url": "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-May2026.zip",
        "resolved_url": "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-May2026.zip",
        "filename": "Accounts_Monthly_Data-May2026.zip",
        "bytes": 1_975_424_256,
        "etag": '"5c27d3b897a72e43c915cf5b5d167e77-236"',
        "last_modified": "Sat, 04 Jul 2026 09:00:07 GMT",
    },
    {
        "kind": "accounts",
        "url": "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-June2026.zip",
        "resolved_url": "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-June2026.zip",
        "filename": "Accounts_Monthly_Data-June2026.zip",
        "bytes": 2_348_684_884,
        "etag": '"b86d234bcb747225b02d8bae3bc93491-280"',
        "last_modified": "Sat, 01 Aug 2026 09:00:12 GMT",
    },
    {
        "kind": "accounts",
        "url": "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-July2026.zip",
        "resolved_url": "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-July2026.zip",
        "filename": "Accounts_Monthly_Data-July2026.zip",
        "bytes": 2_229_763_708,
        "etag": '"2dcaa897d193afbcf0f15be83d3a0a65-266"',
        "last_modified": "Mon, 10 Aug 2026 09:00:13 GMT",
    },
    {
        "kind": "basic",
        "url": "https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-2026-08-01.zip",
        "resolved_url": "https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-2026-08-01.zip",
        "filename": "BasicCompanyDataAsOneFile-2026-08-01.zip",
        "bytes": 493_049_031,
        "etag": '"b684020145defd5a3373b3d2c56c3b87-59"',
        "last_modified": "Fri, 07 Aug 2026 08:10:19 GMT",
    },
)
EXPECTED_TOTAL_BYTES = 7_046_921_879
ORIGINAL_LOAD_ITEM = PREVIOUS.load_item
ORIGINAL_DOWNLOAD = PREVIOUS.download


def load_item(plan_path: Path, index: int) -> tuple[dict, dict]:
    plan, item = ORIGINAL_LOAD_ITEM(plan_path, index)
    if plan.get("planned_at") != FIXED_GENERATED_AT:
        raise RuntimeError("Download plan timestamp is not generation-fixed")
    if plan.get("total_bytes") != EXPECTED_TOTAL_BYTES or plan.get("files") != list(EXPECTED_FILES):
        raise RuntimeError("Download plan differs from the source-pinned archive closure")
    return plan, item


def download(plan_path: Path, index: int, output: Path, receipt_path: Path) -> dict:
    receipt = ORIGINAL_DOWNLOAD(plan_path, index, output, receipt_path)
    receipt["retrieved_at"] = FIXED_GENERATED_AT
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


PREVIOUS.load_item = load_item
PREVIOUS.download = download


if __name__ == "__main__":
    raise SystemExit(PREVIOUS.main())
