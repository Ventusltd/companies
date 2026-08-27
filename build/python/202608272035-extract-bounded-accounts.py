#!/usr/bin/env python3
"""Bounded 202608272035 extractor with the full eight-alphanumeric key domain."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path, PurePosixPath

GENERATION = "202608272035"
FIXED_GENERATED_AT = "2026-08-27T19:35:00Z"
MAX_DOCUMENT_BYTES = 128_000_000
MAX_OTHER_MEMBER_BYTES = 32_000_000
DOCUMENT_SUFFIXES = frozenset({".html", ".xhtml", ".xml"})
COMPANY_NUMBER = re.compile(r"^[A-Z0-9]{8}$")
# Companies House monthly accounts members name the identity in the first
# basename slot: ``Prod_<company-number>_...``.  Anchoring that slot prevents
# an invalid identity from falling through to a later date or label token.
COMPANY_NUMBER_IN_FILENAME = re.compile(r"^Prod_([A-Z0-9]{8})(?:_|\.)", re.I | re.ASCII)
PARENT = Path(__file__).with_name("202608271507-extract-bounded-accounts.py")

spec = importlib.util.spec_from_file_location("companies_extract_202608271507_for_2035", PARENT)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608271507 extractor")
PREVIOUS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREVIOUS)

if PREVIOUS.MAX_MEMBER_BYTES != MAX_OTHER_MEMBER_BYTES:
    raise RuntimeError("The inherited non-document ceiling drifted")
if PREVIOUS.MAX_TOTAL_EXPANDED_BYTES != 60_000_000_000:
    raise RuntimeError("The inherited aggregate expanded-byte ceiling drifted")
if PREVIOUS.MAX_COMPRESSION_RATIO != 250:
    raise RuntimeError("The inherited compression-ratio ceiling drifted")
if PREVIOUS.MAX_MEMBERS != 2_000_000 or PREVIOUS.MAX_NESTING != 1:
    raise RuntimeError("The inherited member-count or nesting ceiling drifted")

ORIGINAL_VALIDATE_MEMBER = PREVIOUS.validate_member
ORIGINAL_EXTRACT = PREVIOUS.extract
ORIGINAL_VALIDATE_BASIC = PREVIOUS.validate_basic_snapshot
PREVIOUS.GENERATION = GENERATION
PREVIOUS.COMPANY_NUMBER = COMPANY_NUMBER_IN_FILENAME
# iter_documents uses this for bounded reads. validate_member below restores the
# narrower legacy allowance for every member that is not a parsed document.
PREVIOUS.MAX_MEMBER_BYTES = MAX_DOCUMENT_BYTES


def member_ceiling(filename: str) -> int:
    return MAX_DOCUMENT_BYTES if PurePosixPath(filename).suffix.lower() in DOCUMENT_SUFFIXES else MAX_OTHER_MEMBER_BYTES


def validate_member(info, counters: dict) -> None:
    inherited_read_ceiling = PREVIOUS.MAX_MEMBER_BYTES
    PREVIOUS.MAX_MEMBER_BYTES = member_ceiling(info.filename)
    try:
        ORIGINAL_VALIDATE_MEMBER(info, counters)
    finally:
        PREVIOUS.MAX_MEMBER_BYTES = inherited_read_ceiling


def _fix_report(report: dict, report_path: Path) -> dict:
    report["completed_at"] = FIXED_GENERATED_AT
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def extract(archive_path: Path, output: Path, report_path: Path) -> dict:
    return _fix_report(ORIGINAL_EXTRACT(archive_path, output, report_path), report_path)


def validate_basic_snapshot(archive_path: Path, report_path: Path) -> dict:
    return _fix_report(ORIGINAL_VALIDATE_BASIC(archive_path, report_path), report_path)


PREVIOUS.validate_member = validate_member
PREVIOUS.extract = extract
PREVIOUS.validate_basic_snapshot = validate_basic_snapshot

# Re-export bounded primitives for source-only regression fixtures.
parse_document = PREVIOUS.parse_document
MAX_TOTAL_EXPANDED_BYTES = PREVIOUS.MAX_TOTAL_EXPANDED_BYTES
MAX_COMPRESSION_RATIO = PREVIOUS.MAX_COMPRESSION_RATIO
MAX_MEMBERS = PREVIOUS.MAX_MEMBERS
MAX_NESTING = PREVIOUS.MAX_NESTING


if __name__ == "__main__":
    raise SystemExit(PREVIOUS.main())
