#!/usr/bin/env python3
"""Generation wrapper for the unchanged source-pinned Companies House plan."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

GENERATION = "202608272155"
BASE_COMMIT = "edc8d5d08ca6e224af0a907af90d0ed253d1c60d"
FIXED_GENERATED_AT = "2026-08-27T21:55:00Z"
PARENT_PATH = Path(__file__).with_name("202608272120-freeze-companies-house-plan.py")

spec = importlib.util.spec_from_file_location("companies_plan_202608272120_for_2155", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272120 planner")
PARENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT)

PARENT.GENERATION = GENERATION
PARENT.BASE_COMMIT = BASE_COMMIT
PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PARENT.GENERATION = GENERATION
PARENT.PARENT.BASE_COMMIT = BASE_COMMIT
PARENT.PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PARENT.PREVIOUS.GENERATION = GENERATION
PARENT.PARENT.PREVIOUS.BASE_COMMIT = BASE_COMMIT
PARENT.PARENT.PREVIOUS.USER_AGENT = "Ventus-Companies/202608272155 (+https://github.com/Ventusltd/companies)"

EXPECTED_FILES = PARENT.EXPECTED_FILES
EXPECTED_TOTAL_BYTES = PARENT.EXPECTED_TOTAL_BYTES


def fixed_plan(probe=PARENT.PARENT.PREVIOUS.probe) -> dict:
    plan = PARENT.fixed_plan(probe)
    if plan.get("files") != list(EXPECTED_FILES) or plan.get("total_bytes") != EXPECTED_TOTAL_BYTES:
        raise RuntimeError("The inherited source-pinned archive closure drifted")
    return plan


def fixed_rest_evidence(output: Path) -> dict:
    return PARENT.fixed_rest_evidence(output)


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
