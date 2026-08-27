#!/usr/bin/env python3
"""Deterministic tests for the pre-download Companies House budget gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build/python/202608270548-plan-companies-house-downloads.py"
SPEC = importlib.util.spec_from_file_location("companies_download_plan", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Response:
    def __init__(self, url: str, size: int):
        self.url = url
        self.headers = {
            "Content-Length": str(size),
            "ETag": '"fixture"',
            "Last-Modified": "Thu, 27 Aug 2026 00:00:00 GMT",
        }

    def raise_for_status(self) -> None:
        return None


class Session:
    sizes = {
        "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-July2026.zip": 2_000_000_000,
        "https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-2026-08-01.zip": 800_000_000,
    }

    @classmethod
    def head(cls, url, **_kwargs):
        return Response(url, cls.sizes[url])


def rejected(callable_) -> str:
    try:
        callable_()
    except RuntimeError as exc:
        return str(exc)
    raise AssertionError("Expected RuntimeError")


def main() -> None:
    rows = [("accounts", url) for url in list(Session.sizes)[:1]] + [("basic", list(Session.sizes)[1])]
    plan = MODULE.build_plan(rows, 3_000_000_000, Session)
    assert plan["schema"] == "companies-house-download-plan-v1"
    assert plan["total_bytes"] == 2_800_000_000
    assert plan["file_count"] == 2
    assert "budget" in rejected(lambda: MODULE.build_plan(rows, 2_799_999_999, Session))
    assert "Duplicate" in rejected(lambda: MODULE.build_plan(rows + [rows[0]], 9_000_000_000, Session))
    assert "official" in rejected(lambda: MODULE.require_official("https://example.test/archive.zip"))
    assert "components" in rejected(lambda: MODULE.require_official(
        "https://download.companieshouse.gov.uk/archive.zip?unexpected=1"
    ))
    print('{"status":"PASS","planned_bytes":2800000000,"rejection_cases":4}')


if __name__ == "__main__":
    main()
