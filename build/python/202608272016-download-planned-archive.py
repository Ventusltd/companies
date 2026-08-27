#!/usr/bin/env python3
"""202608272016 generation wrapper for receipt-bound archive acquisition."""
from __future__ import annotations

import importlib.util
from pathlib import Path

GENERATION = "202608272016"
BASE_COMMIT = "cc61a74edea5321b9654a22af2e589a56c6dc19b"
PARENT = Path(__file__).with_name("202608271507-download-planned-archive.py")

spec = importlib.util.spec_from_file_location("companies_download_202608271507", PARENT)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608271507 downloader")
PREVIOUS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREVIOUS)
PREVIOUS.GENERATION = GENERATION
PREVIOUS.BASE_COMMIT = BASE_COMMIT
PREVIOUS.USER_AGENT = "Ventus-Companies/202608272016 (+https://github.com/Ventusltd/companies)"


if __name__ == "__main__":
    raise SystemExit(PREVIOUS.main())

