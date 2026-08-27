#!/usr/bin/env python3
"""Deterministic boundary contract for the 202608272016 iXBRL ceiling repair."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


EXTRACT = load("companies_extract_202608272016", "build/python/202608272016-extract-bounded-accounts.py")
PLAN = load("companies_plan_202608272016", "build/python/202608272016-freeze-companies-house-plan.py")
DOWNLOAD = load("companies_download_202608272016", "build/python/202608272016-download-planned-archive.py")
VERIFY = load("companies_verify_202608272016", "build/python/202608272016-verify-companies-house-candidate.py")


def rejected(callable_, contains: str) -> None:
    try:
        callable_()
    except RuntimeError as exc:
        assert contains.lower() in str(exc).lower(), (contains, str(exc))
        return
    raise AssertionError(f"Expected RuntimeError containing {contains!r}")


def member(name: str, size: int, compressed: int | None = None) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.file_size = size
    info.compress_size = size if compressed is None else compressed
    return info


def counters(expanded: int = 0) -> dict:
    return {"members": 0, "expanded_bytes": expanded}


def test_generation_boundary() -> None:
    expected_parent = "cc61a74edea5321b9654a22af2e589a56c6dc19b"
    assert PLAN.GENERATION == DOWNLOAD.GENERATION == VERIFY.GENERATION == "202608272016"
    assert PLAN.BASE_COMMIT == DOWNLOAD.BASE_COMMIT == VERIFY.BASE_COMMIT == expected_parent
    assert PLAN.PREVIOUS.GENERATION == DOWNLOAD.PREVIOUS.GENERATION == VERIFY.PREVIOUS.GENERATION == "202608272016"
    assert PLAN.PREVIOUS.BASE_COMMIT == DOWNLOAD.PREVIOUS.BASE_COMMIT == VERIFY.PREVIOUS.BASE_COMMIT == expected_parent
    assert VERIFY.PREVIOUS.FIXED_GENERATED_AT == "2026-08-27T19:16:00Z"
    assert VERIFY.DUCKDB_VERSION == "1.3.2"
    assert VERIFY.REFERENCE_REPOSITORY == "Ventusltd/data-gb-electricity"
    assert VERIFY.REFERENCE_COMMIT == "7c492745c974f6b8610cb1209f996b1553abb498"


def test_source_manifest() -> None:
    path = ROOT / "manifests/202608272016-bounded-companies-house-candidate.json"
    manifest = json.loads(path.read_text())
    assert manifest["generation"] == "202608272016"
    assert manifest["base_commit"] == "cc61a74edea5321b9654a22af2e589a56c6dc19b"
    assert manifest["deployment_state"] == "not-authorised"
    assert manifest["limits"]["maximum_document_bytes"] == EXTRACT.MAX_DOCUMENT_BYTES
    assert manifest["limits"]["maximum_other_member_bytes"] == EXTRACT.MAX_OTHER_MEMBER_BYTES
    assert manifest["data_discipline"]["declared_key"] == ["company_number"]
    assert manifest["data_discipline"]["engine"] == {"name": "duckdb", "version": "1.3.2", "threads": 1}
    assert manifest["data_discipline"]["foreign_data_copied"] is False
    assert manifest["discipline_references"]["data_repository"]["commit"] == VERIFY.REFERENCE_COMMIT
    assert manifest["publication"]["stable_path_must_change"] is False
    assert manifest["publication"]["promotion_eligible"] is False
    assert len(manifest["source_files"]) == 7
    for receipt in [*manifest["source_files"], *manifest["dependencies"]]:
        source = ROOT / receipt["path"]
        assert source.is_file(), receipt
        if receipt["sha256"] != "SELF":
            assert hashlib.sha256(source.read_bytes()).hexdigest() == receipt["sha256"], receipt


def test_document_ceiling() -> None:
    assert EXTRACT.MAX_DOCUMENT_BYTES == 128_000_000
    assert EXTRACT.MAX_OTHER_MEMBER_BYTES == 32_000_000
    for suffix in (".xhtml", ".html", ".xml"):
        EXTRACT.validate_member(member(f"Prod_01234567_T01{suffix}", EXTRACT.MAX_DOCUMENT_BYTES - 1), counters())
        EXTRACT.validate_member(member(f"Prod_01234567_T01{suffix}", EXTRACT.MAX_DOCUMENT_BYTES), counters())
        rejected(
            lambda suffix=suffix: EXTRACT.validate_member(
                member(f"Prod_01234567_T01{suffix}", EXTRACT.MAX_DOCUMENT_BYTES + 1), counters()
            ),
            "per-document ceiling",
        )
    rejected(
        lambda: EXTRACT.validate_member(member("opaque.bin", EXTRACT.MAX_OTHER_MEMBER_BYTES + 1), counters()),
        "per-document ceiling",
    )
    assert EXTRACT.PREVIOUS.MAX_MEMBER_BYTES == EXTRACT.MAX_DOCUMENT_BYTES


def test_inherited_bomb_guards() -> None:
    assert EXTRACT.MAX_TOTAL_EXPANDED_BYTES == 60_000_000_000
    assert EXTRACT.MAX_COMPRESSION_RATIO == 250
    assert EXTRACT.MAX_MEMBERS == 2_000_000
    assert EXTRACT.MAX_NESTING == 1
    EXTRACT.validate_member(member("Prod_01234567_T01.xhtml", 2_500, 10), counters())
    rejected(
        lambda: EXTRACT.validate_member(member("Prod_01234567_T01.xhtml", 2_501, 10), counters()),
        "compression ratio",
    )
    EXTRACT.validate_member(
        member("Prod_01234567_T01.xhtml", 1, 1),
        counters(EXTRACT.MAX_TOTAL_EXPANDED_BYTES - 1),
    )
    rejected(
        lambda: EXTRACT.validate_member(
            member("Prod_01234567_T01.xhtml", 2, 2),
            counters(EXTRACT.MAX_TOTAL_EXPANDED_BYTES - 1),
        ),
        "expanded-byte ceiling",
    )
    rejected(
        lambda: EXTRACT.validate_member(member("../escape.xhtml", 1, 1), counters()),
        "unsafe",
    )


def analytical_record(number: str) -> dict:
    return {
        "company_name": f"FIXTURE {number} LIMITED",
        "company_number": number,
        "company_status": "Active",
        "sic_codes": ["35110 - Production of electricity"],
        "accounts_date": "2025-12-31",
        "total_assets": 15_000_000,
        "net_assets": "8000000.25",
        "turnover": None,
        "cash": 500_000.5,
        "assets_gte_10m": True,
        "energy_relevant_large_company": True,
        "btm_tags": ["INDUSTRIAL_SIC_B_TO_E"],
        "repd_name_candidates": [],
        "probable_project_spv": False,
        "classification": "ENERGY_RELEVANT_LARGE_COMPANY",
        "financial_currency": "GBP",
        "news_identity_policy": "NEWS_MAY_ANNOTATE_BUT_NEVER_ESTABLISH_IDENTITY",
    }


def analytical_fixture(root: Path, records: list[dict]) -> dict:
    files = {}
    for name in sorted(VERIFY.PREVIOUS.EXPECTED_CARTRIDGES):
        path = root / f"{name}-v1.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "companies-house-cartridge-v1",
                    "snapshot_id": "202608272016",
                    "records": records,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        files[name] = {
            "path": path.name,
            "records": len(records),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return {"files": files, "companies": len(records)}


def test_analytical_contract() -> str:
    record = analytical_record("01234567")
    row = VERIFY.analytical_row(record)
    assert row[1] == "01234567"
    assert row[6] == Decimal("15000000.00")
    assert row[7] == Decimal("8000000.25")
    assert row[8] is None
    assert row[9] == Decimal("500000.50")
    assert VERIFY.PARQUET_KEY == ("company_number",)
    assert VERIFY.PARQUET_COLUMNS[6] == ("total_assets", "DECIMAL(38,2)", True)
    rejected(lambda: VERIFY.money(True, "fixture"), "not a monetary")
    malformed = dict(record)
    malformed["assets_gte_10m"] = "true"
    rejected(lambda: VERIFY.analytical_row(malformed), "is not boolean")
    try:
        VERIFY.load_duckdb()
    except RuntimeError as exc:
        if "is required" not in str(exc):
            raise
        return "SKIPPED_LOCAL_DUCKDB_UNAVAILABLE"
    with tempfile.TemporaryDirectory() as temporary:
        first = Path(temporary) / "first"
        second = Path(temporary) / "second"
        first.mkdir()
        second.mkdir()
        first_manifest = analytical_fixture(first, [record])
        second_manifest = analytical_fixture(second, [record])
        first_audit = VERIFY.write_analytical_parquet(first, first_manifest)
        second_audit = VERIFY.write_analytical_parquet(second, second_manifest)
        assert first_audit["rows"] == first_audit["distinct_keys"] == 1
        assert first_audit["null_keys"] == first_audit["duplicate_key_groups"] == 0
        assert (first / VERIFY.PARQUET_PATH).read_bytes() == (second / VERIFY.PARQUET_PATH).read_bytes()
        comparable_first = json.loads((first / VERIFY.AUDIT_PATH).read_text())
        comparable_second = json.loads((second / VERIFY.AUDIT_PATH).read_text())
        assert comparable_first == comparable_second
        copied = first / "copied.parquet"
        shutil.copyfile(first / VERIFY.PARQUET_PATH, copied)
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == first_audit["parquet"]["sha256"]
    return "PASS"


def test_company_number_domain_and_rights_separation() -> None:
    accepted = ("00000006", "SC123456", "NI123456", "OC123456", "R0000001", "AB12CD34")
    rejected_numbers = ("", "1234567", "123456789", "SC12345", "SC1234567", "AB-12345")
    for number in accepted:
        assert VERIFY.PREVIOUS.COMPANY_NUMBER.fullmatch(number), number
    for number in rejected_numbers:
        assert not VERIFY.PREVIOUS.COMPANY_NUMBER.fullmatch(number), number
    source = (ROOT / "build/python/202608272016-verify-companies-house-candidate.py").read_text()
    assert '"usage_context"] = "NON_COMMERCIAL_OPEN_SOURCE"' in source
    assert '"source_licence"] = PREVIOUS.OGL' in source
    assert '"source_rights_are_distinct_from_usage_context"] = True' in source
    discipline = source.split('manifest["data_discipline"] = {', 1)[1].split("}", 1)[0]
    assert "licensing_posture" not in discipline


def main() -> None:
    test_generation_boundary()
    test_source_manifest()
    test_company_number_domain_and_rights_separation()
    test_document_ceiling()
    test_inherited_bomb_guards()
    analytical_status = test_analytical_contract()
    print(
        json.dumps(
            {
                "status": "PASS",
                "generation": "202608272016",
                "document_ceiling_bytes": EXTRACT.MAX_DOCUMENT_BYTES,
                "aggregate_ceiling_bytes": EXTRACT.MAX_TOTAL_EXPANDED_BYTES,
                "compression_ratio_ceiling": EXTRACT.MAX_COMPRESSION_RATIO,
                "analytical_contract": analytical_status,
                "network_requests": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
