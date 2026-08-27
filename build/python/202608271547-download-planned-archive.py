#!/usr/bin/env python3
"""202608271547 generation wrapper for receipt-bound archive acquisition."""
from __future__ import annotations

import importlib.util
from pathlib import Path

GENERATION = "202608271547"
BASE_COMMIT = "625101ef325f3d67fc866e3822bd76f1fcbb2e49"
PARENT = Path(__file__).with_name("202608271507-download-planned-archive.py")

spec = importlib.util.spec_from_file_location("companies_download_202608271507", PARENT)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608271507 downloader")
PREVIOUS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREVIOUS)
PREVIOUS.GENERATION = GENERATION
PREVIOUS.BASE_COMMIT = BASE_COMMIT
PREVIOUS.USER_AGENT = "Ventus-Companies/202608271547 (+https://github.com/Ventusltd/companies)"


if __name__ == "__main__":
    raise SystemExit(PREVIOUS.main())
