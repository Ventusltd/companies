#!/usr/bin/env python3
"""Bounded extractor anchored to the measured monthly-member identity slot."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

GENERATION = "202608272120"
FIXED_GENERATED_AT = "2026-08-27T20:20:00Z"
COMPANY_NUMBER = re.compile(r"^[A-Z0-9]{8}$", re.ASCII)
# Measured official member example: Prod224_2605_00009872_20260331.html.
# Identity is exclusively the third underscore-delimited token. The surrounding
# tokens are also closed so a malformed period/date cannot shift identity.
COMPANY_NUMBER_IN_FILENAME = re.compile(
    r"^Prod[0-9]{3}_[0-9]{4}_((?i:[A-Z0-9]{8}))_[0-9]{8}\.(?i:html|xhtml|xml)$",
    re.ASCII,
)
PARENT_PATH = Path(__file__).with_name("202608272035-extract-bounded-accounts.py")

spec = importlib.util.spec_from_file_location("companies_extract_202608272035_for_2120", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272035 extractor")
PARENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT)

PARENT.GENERATION = GENERATION
PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.COMPANY_NUMBER = COMPANY_NUMBER
PARENT.COMPANY_NUMBER_IN_FILENAME = COMPANY_NUMBER_IN_FILENAME
PARENT.PREVIOUS.GENERATION = GENERATION
PARENT.PREVIOUS.COMPANY_NUMBER = COMPANY_NUMBER_IN_FILENAME

parse_document = PARENT.PREVIOUS.parse_document
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
    raise SystemExit(PARENT.PREVIOUS.main())
