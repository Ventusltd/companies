#!/usr/bin/env python3
"""Download wrapper for the immutable 202608272155 Companies closure."""
from __future__ import annotations

import importlib.util
from pathlib import Path

GENERATION = "202608272155"
BASE_COMMIT = "edc8d5d08ca6e224af0a907af90d0ed253d1c60d"
FIXED_GENERATED_AT = "2026-08-27T21:55:00Z"
PARENT_PATH = Path(__file__).with_name("202608272120-download-planned-archive.py")

spec = importlib.util.spec_from_file_location("companies_download_202608272120_for_2155", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272120 downloader")
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
load_item = PARENT.load_item
download = PARENT.download


if __name__ == "__main__":
    raise SystemExit(PARENT.PARENT.PREVIOUS.main())
