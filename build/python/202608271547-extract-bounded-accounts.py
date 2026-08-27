#!/usr/bin/env python3
"""Generation-scoped extractor with a bounded iXBRL document allowance."""
from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath

GENERATION = "202608271547"
MAX_DOCUMENT_BYTES = 128_000_000
MAX_OTHER_MEMBER_BYTES = 32_000_000
DOCUMENT_SUFFIXES = frozenset({".html", ".xhtml", ".xml"})
PARENT = Path(__file__).with_name("202608271507-extract-bounded-accounts.py")

spec = importlib.util.spec_from_file_location("companies_extract_202608271507", PARENT)
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
PREVIOUS.GENERATION = GENERATION
# iter_documents uses this only for bounded reads; validate_member below applies
# the narrower legacy allowance to every member that is not a parsed document.
PREVIOUS.MAX_MEMBER_BYTES = MAX_DOCUMENT_BYTES


def member_ceiling(filename: str) -> int:
    return MAX_DOCUMENT_BYTES if PurePosixPath(filename).suffix.lower() in DOCUMENT_SUFFIXES else MAX_OTHER_MEMBER_BYTES


def validate_member(info, counters: dict) -> None:
    """Retain every inherited guard while varying only the type-aware byte cap."""
    inherited_read_ceiling = PREVIOUS.MAX_MEMBER_BYTES
    PREVIOUS.MAX_MEMBER_BYTES = member_ceiling(info.filename)
    try:
        ORIGINAL_VALIDATE_MEMBER(info, counters)
    finally:
        PREVIOUS.MAX_MEMBER_BYTES = inherited_read_ceiling


PREVIOUS.validate_member = validate_member


# Re-export the bounded primitives for deterministic boundary fixtures.
extract = PREVIOUS.extract
validate_basic_snapshot = PREVIOUS.validate_basic_snapshot
MAX_TOTAL_EXPANDED_BYTES = PREVIOUS.MAX_TOTAL_EXPANDED_BYTES
MAX_COMPRESSION_RATIO = PREVIOUS.MAX_COMPRESSION_RATIO
MAX_MEMBERS = PREVIOUS.MAX_MEMBERS
MAX_NESTING = PREVIOUS.MAX_NESTING


if __name__ == "__main__":
    raise SystemExit(PREVIOUS.main())
