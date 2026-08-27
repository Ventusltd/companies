#!/usr/bin/env python3
"""Timestamped wrapper preserving the audited 2035 two-grain verifier."""
from __future__ import annotations

import importlib.util
from pathlib import Path

GENERATION = "202608272120"
BASE_COMMIT = "cd870ff53d2693b734e5860947bb0fa96bde9cf3"
FIXED_GENERATED_AT = "2026-08-27T20:20:00Z"
EXPECTED_PLAN_SHA256 = "a3d614e85c87af03b6b5d4ef50d1e2634dc4adce987f01ac36491736110a2cde"
EXPECTED_REST_EVIDENCE_SHA256 = "92b5c7c3bc2e3ccee3287a371e09413c85b4c4e0ea5c7f4fd9429650535ac15f"
PARENT_PATH = Path(__file__).with_name("202608272035-verify-companies-house-candidate.py")

spec = importlib.util.spec_from_file_location("companies_verify_202608272035_for_2120", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272035 verifier")
BASE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BASE)

# Preserve every 2035 schema, grain, ZSTD, DuckDB readback, provenance and
# publication invariant. Only generation-bound values advance.
BASE.GENERATION = GENERATION
BASE.BASE_COMMIT = BASE_COMMIT
BASE.FIXED_GENERATED_AT = FIXED_GENERATED_AT
BASE.EXPECTED_PLAN_SHA256 = EXPECTED_PLAN_SHA256
BASE.EXPECTED_REST_EVIDENCE_SHA256 = EXPECTED_REST_EVIDENCE_SHA256
BASE.PARENT.GENERATION = GENERATION
BASE.PARENT.BASE_COMMIT = BASE_COMMIT
BASE.PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
BASE.PARENT.PREVIOUS.GENERATION = GENERATION
BASE.PARENT.PREVIOUS.BASE_COMMIT = BASE_COMMIT
BASE.PARENT.PREVIOUS.FIXED_GENERATED_AT = FIXED_GENERATED_AT

# Match the public module surface of the inherited verifier so the unchanged
# two-grain contract fixtures exercise precisely the same implementation.
PARENT = BASE.PARENT


def _sync_generation_contract() -> None:
    """Keep mutable fixture overrides visible to the inherited implementation."""
    BASE.EXPECTED_PLAN_SHA256 = EXPECTED_PLAN_SHA256
    BASE.EXPECTED_REST_EVIDENCE_SHA256 = EXPECTED_REST_EVIDENCE_SHA256


def seal(*args, **kwargs):
    _sync_generation_contract()
    return BASE.seal(*args, **kwargs)


def verify(*args, **kwargs):
    _sync_generation_contract()
    return BASE.verify(*args, **kwargs)


def __getattr__(name: str):
    return getattr(BASE, name)


if __name__ == "__main__":
    raise SystemExit(BASE.PARENT.PREVIOUS.main())
