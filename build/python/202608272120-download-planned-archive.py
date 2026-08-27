#!/usr/bin/env python3
"""Download wrapper for the immutable 202608272120 Companies closure."""
from __future__ import annotations

import importlib.util
from pathlib import Path

GENERATION = "202608272120"
BASE_COMMIT = "cd870ff53d2693b734e5860947bb0fa96bde9cf3"
FIXED_GENERATED_AT = "2026-08-27T20:20:00Z"
PARENT_PATH = Path(__file__).with_name("202608272035-download-planned-archive.py")

spec = importlib.util.spec_from_file_location("companies_download_202608272035_for_2120", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272035 downloader")
PARENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT)

PARENT.GENERATION = GENERATION
PARENT.BASE_COMMIT = BASE_COMMIT
PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PREVIOUS.GENERATION = GENERATION
PARENT.PREVIOUS.BASE_COMMIT = BASE_COMMIT
PARENT.PREVIOUS.USER_AGENT = "Ventus-Companies/202608272120 (+https://github.com/Ventusltd/companies)"

EXPECTED_FILES = PARENT.EXPECTED_FILES
EXPECTED_TOTAL_BYTES = PARENT.EXPECTED_TOTAL_BYTES
load_item = PARENT.load_item
download = PARENT.download


if __name__ == "__main__":
    raise SystemExit(PARENT.PREVIOUS.main())
