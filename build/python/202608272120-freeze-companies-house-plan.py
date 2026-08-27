#!/usr/bin/env python3
"""Generation wrapper for the unchanged source-pinned Companies House plan."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

GENERATION = "202608272120"
BASE_COMMIT = "cd870ff53d2693b734e5860947bb0fa96bde9cf3"
FIXED_GENERATED_AT = "2026-08-27T20:20:00Z"
PARENT_PATH = Path(__file__).with_name("202608272035-freeze-companies-house-plan.py")

spec = importlib.util.spec_from_file_location("companies_plan_202608272035_for_2120", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272035 planner")
PARENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT)

# The four upstream objects are unchanged. Only the immutable producer identity
# advances. Patch both wrapper and inherited implementation because the latter
# owns the bounded HTTPS probe used by fixed_plan.
PARENT.GENERATION = GENERATION
PARENT.BASE_COMMIT = BASE_COMMIT
PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PREVIOUS.GENERATION = GENERATION
PARENT.PREVIOUS.BASE_COMMIT = BASE_COMMIT
PARENT.PREVIOUS.USER_AGENT = "Ventus-Companies/202608272120 (+https://github.com/Ventusltd/companies)"

EXPECTED_FILES = PARENT.EXPECTED_FILES
EXPECTED_TOTAL_BYTES = PARENT.EXPECTED_TOTAL_BYTES
ORIGINAL_FIXED_PLAN = PARENT.fixed_plan


def fixed_plan(probe=PARENT.PREVIOUS.probe) -> dict:
    plan = ORIGINAL_FIXED_PLAN(probe)
    if plan.get("files") != list(EXPECTED_FILES) or plan.get("total_bytes") != EXPECTED_TOTAL_BYTES:
        raise RuntimeError("The inherited source-pinned archive closure drifted")
    return plan


def fixed_rest_evidence(output: Path) -> dict:
    return PARENT.fixed_rest_evidence(output)


PARENT.fixed_plan = fixed_plan


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
