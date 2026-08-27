#!/usr/bin/env python3
"""Generation wrapper for the measured 202608272120 monthly-member grammar."""
from __future__ import annotations

import importlib.util
from pathlib import Path

GENERATION = "202608272155"
FIXED_GENERATED_AT = "2026-08-27T21:55:00Z"
PARENT_PATH = Path(__file__).with_name("202608272120-extract-bounded-accounts.py")

spec = importlib.util.spec_from_file_location("companies_extract_202608272120_for_2155", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272120 extractor")
PARENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT)

PARENT.GENERATION = GENERATION
PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PARENT.GENERATION = GENERATION
PARENT.PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PARENT.PREVIOUS.GENERATION = GENERATION

COMPANY_NUMBER = PARENT.COMPANY_NUMBER
COMPANY_NUMBER_IN_FILENAME = PARENT.COMPANY_NUMBER_IN_FILENAME
parse_document = PARENT.parse_document
extract = PARENT.extract
validate_basic_snapshot = PARENT.validate_basic_snapshot
validate_member = PARENT.validate_member
member_ceiling = PARENT.member_ceiling
MAX_DOCUMENT_BYTES = PARENT.MAX_DOCUMENT_BYTES
MAX_OTHER_MEMBER_BYTES = PARENT.MAX_OTHER_MEMBER_BYTES
MAX_TOTAL_EXPANDED_BYTES = PARENT.MAX_TOTAL_EXPANDED_BYTES
MAX_COMPRESSION_RATIO = PARENT.MAX_COMPRESSION_RATIO
MAX_MEMBERS = PARENT.MAX_MEMBERS
MAX_NESTING = PARENT.MAX_NESTING


if __name__ == "__main__":
    raise SystemExit(PARENT.PARENT.PREVIOUS.main())
