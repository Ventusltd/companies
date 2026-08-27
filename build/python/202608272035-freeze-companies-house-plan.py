#!/usr/bin/env python3
"""Freeze the exact bounded Companies House archive closure for 202608272035."""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import sys
from pathlib import Path

GENERATION = "202608272035"
BASE_COMMIT = "1f91f8efced903aa82e62acf56b9af2db476cfdb"
FIXED_GENERATED_AT = "2026-08-27T19:35:00Z"
PARENT = Path(__file__).with_name("202608271507-freeze-companies-house-plan.py")

spec = importlib.util.spec_from_file_location("companies_plan_202608271507_for_2035", PARENT)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608271507 planner")
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


def fixed_plan(probe=PREVIOUS.probe) -> dict:
    """Re-probe the source-pinned official objects and fail on any drift."""
    requests = [(row["kind"], row["url"]) for row in EXPECTED_FILES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as executor:
        actual = list(executor.map(probe, requests))
    if actual != list(EXPECTED_FILES):
        raise RuntimeError("The source-pinned Companies House archive closure drifted")
    if sum(row["bytes"] for row in actual) != EXPECTED_TOTAL_BYTES:
        raise RuntimeError("The source-pinned Companies House byte closure drifted")
    return {
        "schema": "companies-house-bounded-download-plan-v1",
        "generation": GENERATION,
        "base_commit": BASE_COMMIT,
        "deployment_state": "not-authorised",
        "planned_at": FIXED_GENERATED_AT,
        "official_host": PREVIOUS.OFFICIAL_HOST,
        "accounts_months": 3,
        "file_limit": 4,
        "maximum_archive_bytes": PREVIOUS.MAXIMUM_ARCHIVE_BYTES,
        "maximum_total_bytes": PREVIOUS.MAXIMUM_TOTAL_BYTES,
        "total_bytes": EXPECTED_TOTAL_BYTES,
        "files": actual,
        "licence": PREVIOUS.OGL,
    }


def fixed_rest_evidence(output: Path) -> dict:
    """Retain a deterministic no-credential decision for this bulk-only run."""
    evidence = {
        "schema": "companies-house-optional-rest-evidence-v1",
        "generation": GENERATION,
        "endpoint": f"https://{PREVIOUS.REST_HOST}{PREVIOUS.REST_PROBE_PATH}",
        "enabled": False,
        "status": "SKIPPED",
        "reason": "optional-secret-not-configured",
        "policy": "fixed-bulk-generation-does-not-probe-rest",
        "response_body_retained": False,
        "credential_retained": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rest-evidence", type=Path)
    args = parser.parse_args()
    try:
        plan = fixed_plan()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        if args.rest_evidence:
            fixed_rest_evidence(args.rest_evidence)
        print(json.dumps({"status": "PASS", "files": len(plan["files"]), "bytes": plan["total_bytes"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
