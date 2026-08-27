#!/usr/bin/env python3
"""Source-only contracts for the 202608272035 Companies successor."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN = load("build/python/202608272035-freeze-companies-house-plan.py", "companies_plan_2035_test")
DOWNLOAD = load("build/python/202608272035-download-planned-archive.py", "companies_download_2035_test")
EXTRACT = load("build/python/202608272035-extract-bounded-accounts.py", "companies_extract_2035_test")
VERIFY = load("build/python/202608272035-verify-companies-house-candidate.py", "companies_verify_2035_test")
BASE_FIXTURE = load("tests/test_202608271507_bounded_companies_house.py", "companies_1507_fixture_for_2035")


def rejected(callable_, contains: str) -> None:
    try:
        callable_()
    except RuntimeError as exc:
        assert contains.lower() in str(exc).lower(), (contains, str(exc))
        return
    raise AssertionError(f"Expected RuntimeError containing {contains!r}")


def test_generation_and_fixed_plan() -> None:
    assert PLAN.GENERATION == DOWNLOAD.GENERATION == EXTRACT.GENERATION == VERIFY.GENERATION == "202608272035"
    assert PLAN.BASE_COMMIT == DOWNLOAD.BASE_COMMIT == VERIFY.BASE_COMMIT == "1f91f8efced903aa82e62acf56b9af2db476cfdb"
    assert PLAN.FIXED_GENERATED_AT == DOWNLOAD.FIXED_GENERATED_AT == EXTRACT.FIXED_GENERATED_AT == VERIFY.FIXED_GENERATED_AT
    assert PLAN.EXPECTED_FILES == DOWNLOAD.EXPECTED_FILES
    assert PLAN.EXPECTED_TOTAL_BYTES == DOWNLOAD.EXPECTED_TOTAL_BYTES == 7_046_921_879

    expected_by_url = {row["url"]: row for row in PLAN.EXPECTED_FILES}
    plan = PLAN.fixed_plan(lambda request: dict(expected_by_url[request[1]]))
    assert plan["planned_at"] == PLAN.FIXED_GENERATED_AT
    assert plan["files"] == list(PLAN.EXPECTED_FILES)
    assert [row["filename"] for row in plan["files"]] == [
        "Accounts_Monthly_Data-May2026.zip",
        "Accounts_Monthly_Data-June2026.zip",
        "Accounts_Monthly_Data-July2026.zip",
        "BasicCompanyDataAsOneFile-2026-08-01.zip",
    ]

    def drifted(request):
        row = dict(expected_by_url[request[1]])
        if row["filename"].endswith("May2026.zip"):
            row["etag"] = '"drifted"'
        return row

    rejected(lambda: PLAN.fixed_plan(drifted), "closure drifted")


def ixbrl_payload(asset_value: int) -> bytes:
    filler = "0123456789abcdef" * 160
    return (
        "<root>"
        '<context id="current"><instant>2025-12-31</instant></context>'
        f'<totalassets contextRef="current">{asset_value}</totalassets>'
        f"<filler>{filler}</filler>"
        "</root>"
    ).encode()


def test_extractor_company_number_end_to_end() -> None:
    accepted = ("00000006", "SC123456", "R0000001", "AB12CD34")
    for number in accepted:
        assert EXTRACT.COMPANY_NUMBER.fullmatch(number)
        row, parser = EXTRACT.parse_document(f"Prod_{number}_2025-12-31_T01.xhtml", ixbrl_payload(15_000_000))
        assert parser == "xml"
        assert row and row["company_number"] == number
    for number in ("", "1234567", "123456789", "SC12345", "AB-12345"):
        assert not EXTRACT.COMPANY_NUMBER.fullmatch(number)
        row, parser = EXTRACT.parse_document(f"Prod_{number}_2025-12-31_T01.xhtml", ixbrl_payload(15_000_000))
        assert row is None and parser == "no-company-number"
    for misleading_name in (
        "Prod_BAD_20251231_T01.xhtml",
        "Prod_1234567_20251231_T01.xhtml",
        "unrelated_ACCOUNTS_T01.xhtml",
        "prefix_Prod_R0000001_T01.xhtml",
        "Prod_ſC123456_T01.xhtml",
        "Prod_ıC123456_T01.xhtml",
    ):
        row, parser = EXTRACT.parse_document(misleading_name, ixbrl_payload(15_000_000))
        assert row is None and parser == "no-company-number"

    with tempfile.TemporaryDirectory(prefix="companies-2035-extract-") as temporary:
        root = Path(temporary)
        archive = root / "Accounts_Monthly_Data-Fixture2026.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
            handle.writestr("Prod_R0000001_2025-12-31_T01.xhtml", ixbrl_payload(15_000_001))
            handle.writestr("Prod_AB12CD34_2025-12-31_T01.xhtml", ixbrl_payload(15_000_002))
        output = root / "accounts.ndjson"
        report_path = root / "report.json"
        report = EXTRACT.extract(archive, output, report_path)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert [row["company_number"] for row in rows] == ["AB12CD34", "R0000001"]
        assert report["records"] == 2
        assert report["completed_at"] == EXTRACT.FIXED_GENERATED_AT
        assert json.loads(report_path.read_text()) == report


def relationship(ref: str, match_type: str = "EXACT_OPERATOR_NAME", **changes) -> dict:
    value = {
        "repd_ref": ref,
        "match_type": match_type,
        "gg_project_id": f"GG2050-REPD-{ref}",
        "project": f"PROJECT {ref}",
        "operator": "FIXTURE OPERATOR",
        "technology": "solar",
        "capacity_mw": "12.345678",
        "status": "Operational",
        "latitude": 52.1,
        "longitude": -1.2,
        "atlas_url": f"https://globalgrid2050.com/repd_grid_atlasv8/?repd_ref={ref}",
    }
    value.update(changes)
    return value


def record(number: str = "R0000001", relationships: list[dict] | None = None) -> dict:
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
        "repd_name_candidates": relationships if relationships is not None else [relationship("10001")],
        "probable_project_spv": False,
        "classification": "REPD_NAME_CANDIDATE",
        "financial_currency": "GBP",
        "news_identity_policy": "NEWS_MAY_ANNOTATE_BUT_NEVER_ESTABLISH_IDENTITY",
    }


def cartridge_fixture(root: Path, records: list[dict]) -> dict:
    files = {}
    canonical = sorted(records, key=lambda row: row["company_number"])
    for name in sorted(VERIFY.PARENT.PREVIOUS.EXPECTED_CARTRIDGES):
        path = root / f"{name}-v1.json"
        path.write_text(
            json.dumps(
                {"schema": "companies-house-cartridge-v1", "snapshot_id": VERIFY.GENERATION, "records": canonical},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        files[name] = {
            "path": path.name,
            "records": len(canonical),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return {"files": files, "companies": len(canonical)}


def test_relationship_key_law() -> None:
    one = record(relationships=[relationship("10001"), relationship("10002")])
    rows = VERIFY.relationship_rows([one])
    assert len(rows) == 2
    assert str(rows[0][8]) == "12.345678"
    assert [(row[1], row[2], row[3]) for row in rows] == [
        ("R0000001", "10001", "EXACT_OPERATOR_NAME"),
        ("R0000001", "10002", "EXACT_OPERATOR_NAME"),
    ]
    distinct_match = record(
        relationships=[relationship("10001", "EXACT_OPERATOR_NAME"), relationship("10001", "EXACT_PROJECT_NAME")]
    )
    assert len(VERIFY.relationship_rows([distinct_match])) == 2
    repeated = relationship("10001")
    rejected(lambda: VERIFY.relationship_rows([record(relationships=[repeated, dict(repeated)])]), "duplicate")
    rejected(
        lambda: VERIFY.relationship_rows(
            [record(relationships=[relationship("10001"), relationship("10001", operator="DRIFT")])]
        ),
        "drift",
    )
    rejected(lambda: VERIFY.relationship_rows([record(relationships=[relationship("")])]), "blank")
    rejected(lambda: VERIFY.relationship_rows([record(relationships=[relationship("10001", match_type=None)])]), "null")
    rejected(lambda: VERIFY.relationship_rows([record(relationships=[relationship(" 10001")])]), "whitespace")


def replace_parquet(source: Path, query: str, compression: str = "ZSTD") -> None:
    duckdb = VERIFY.load_duckdb()
    target = source.with_name(f"tampered-{source.name}")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"COPY ({query}) TO '{VERIFY.sql_path(target)}' (FORMAT PARQUET, COMPRESSION {compression})"
        )
    finally:
        connection.close()
    shutil.move(target, source)


def test_actual_landed_two_grain_readback() -> None:
    fixture = record(relationships=[relationship("10001"), relationship("10002")])
    with tempfile.TemporaryDirectory(prefix="companies-2035-parquet-") as temporary:
        base = Path(temporary)
        first = base / "first"
        second = base / "second"
        first.mkdir()
        second.mkdir()
        first_audit = VERIFY.build_analytical_datasets(first, cartridge_fixture(first, [fixture]))
        second_audit = VERIFY.build_analytical_datasets(second, cartridge_fixture(second, [fixture]))
        companies = first_audit["datasets"]["companies"]
        relationships = first_audit["datasets"]["company_repd_candidates"]
        assert companies["rows"] == companies["distinct_keys"] == 1
        assert relationships["rows"] == relationships["distinct_keys"] == 2
        assert companies["null_keys"] == relationships["null_keys"] == 0
        assert companies["duplicate_key_groups"] == relationships["duplicate_key_groups"] == 0
        assert companies["typed_column_mismatches"] == relationships["typed_column_mismatches"] == 0
        assert companies["compression_codecs"] == relationships["compression_codecs"] == ["ZSTD"]
        assert companies["declared_key"] == ["company_number"]
        assert relationships["declared_key"] == ["company_number", "repd_ref", "match_type"]
        for name in (VERIFY.COMPANY_PARQUET, VERIFY.RELATIONSHIP_PARQUET):
            assert (first / name).read_bytes() == (second / name).read_bytes()
        assert first_audit == second_audit

        company_rows = VERIFY.company_rows([fixture])
        relationship_rows = VERIFY.relationship_rows([fixture])
        company_path = first / VERIFY.COMPANY_PARQUET
        company_sql = f"SELECT * REPLACE ('WRONG NAME' AS company_name) FROM read_parquet('{VERIFY.sql_path(company_path)}')"
        replace_parquet(company_path, company_sql)
        rejected(
            lambda: VERIFY.audit_parquet(
                company_path,
                VERIFY.COMPANY_COLUMNS,
                ("company_number",),
                "record_json",
                company_rows,
            ),
            "readback",
        )

        relationship_path = first / VERIFY.RELATIONSHIP_PARQUET
        relation_sql = f"SELECT * FROM read_parquet('{VERIFY.sql_path(relationship_path)}')"
        replace_parquet(relationship_path, relation_sql, compression="SNAPPY")
        rejected(
            lambda: VERIFY.audit_parquet(
                relationship_path,
                VERIFY.RELATIONSHIP_COLUMNS,
                ("company_number", "repd_ref", "match_type"),
                "relationship_json",
                relationship_rows,
            ),
            "compression",
        )


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def successor_seal_fixture(root: Path):
    plan_path, evidence, repd, raw, basic, accounts, _old_rest, basic_report = BASE_FIXTURE.write_verifier_fixture(root)
    plan = json.loads(plan_path.read_text())
    plan["generation"] = VERIFY.GENERATION
    plan["base_commit"] = VERIFY.BASE_COMMIT
    plan["planned_at"] = VERIFY.FIXED_GENERATED_AT
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    for path in sorted(evidence.glob("receipt-*.json")):
        receipt = json.loads(path.read_text())
        receipt["generation"] = VERIFY.GENERATION
        receipt["base_commit"] = VERIFY.BASE_COMMIT
        receipt["plan_sha256"] = plan_sha
        receipt["retrieved_at"] = VERIFY.FIXED_GENERATED_AT
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    for path in sorted(evidence.glob("extraction-*.json")):
        report = json.loads(path.read_text())
        report["generation"] = VERIFY.GENERATION
        report["completed_at"] = VERIFY.FIXED_GENERATED_AT
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    report = json.loads(basic_report.read_text())
    report["generation"] = VERIFY.GENERATION
    report["completed_at"] = VERIFY.FIXED_GENERATED_AT
    basic_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    rest = root / "fixed-rest-evidence.json"
    PLAN.fixed_rest_evidence(rest)
    return plan_path, evidence, repd, raw, basic, accounts, rest, basic_report


def test_full_successor_seal_and_verify() -> None:
    with tempfile.TemporaryDirectory(prefix="companies-2035-seal-") as temporary:
        root = Path(temporary)
        plan_path, evidence, repd, raw, basic, accounts, rest, basic_report = successor_seal_fixture(root)
        original_plan_sha = VERIFY.EXPECTED_PLAN_SHA256
        VERIFY.EXPECTED_PLAN_SHA256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        try:
            first = root / "candidate-a"
            second = root / "candidate-b"
            for output in (first, second):
                VERIFY.seal(
                    raw,
                    output,
                    plan_path,
                    evidence,
                    evidence,
                    repd,
                    basic,
                    accounts,
                    rest,
                    basic_report,
                    "a" * 40,
                )
            assert tree_bytes(first) == tree_bytes(second)
            result = VERIFY.verify(first)
            assert result["status"] == "PASS", result
            manifest = json.loads((first / "manifest-v1.json").read_text())
            assert manifest["analytical_dataset"]["rows"] == 1
            assert manifest["relationship_dataset"]["rows"] == 1
            assert manifest["data_discipline"] == VERIFY.DATA_DISCIPLINE
            assert manifest["source_licences"] == VERIFY.MATERIALISED_SOURCES
        finally:
            VERIFY.EXPECTED_PLAN_SHA256 = original_plan_sha


def test_source_manifest_and_workflow() -> None:
    source_path = ROOT / "manifests/202608272035-bounded-companies-house-candidate.json"
    source = json.loads(source_path.read_text())
    assert source["generation"] == "202608272035"
    assert source["base_commit"] == VERIFY.BASE_COMMIT
    assert source["usage_context"] == "NON_COMMERCIAL_OPEN_SOURCE"
    assert source["source_rights_are_distinct_from_usage_context"] is True
    assert source["data_discipline"]["company_declared_key"] == ["company_number"]
    assert source["data_discipline"]["relationship_declared_key"] == ["company_number", "repd_ref", "match_type"]
    assert source["data_discipline"]["foreign_repository_files_committed"] is False
    assert source["data_discipline"]["foreign_data_materialised"] is True
    assert source["field_lineage"] == VERIFY.FIELD_LINEAGE
    assert source["runtime_sources"]["repd"]["commit"] == VERIFY.PIPELINENEWS_COMMIT
    assert source["source_licences"]["repd"]["source_page"] == VERIFY.REPD_RIGHTS["source_page"]
    assert source["source_licences"]["repd"]["catalogue_url"] == VERIFY.REPD_RIGHTS["catalogue_url"]
    assert source["source_licences"]["repd"]["catalogue_licence_id"] == "uk-ogl"
    assert source["fixed_archive_plan"]["total_bytes"] == PLAN.EXPECTED_TOTAL_BYTES
    assert source["fixed_archive_plan"]["plan_json_sha256"] == VERIFY.EXPECTED_PLAN_SHA256
    assert source["fixed_archive_plan"]["rest_non_use_evidence_sha256"] == VERIFY.EXPECTED_REST_EVIDENCE_SHA256
    for receipt in [*source["source_files"], *source["dependencies"]]:
        path = ROOT / receipt["path"]
        assert path.is_file(), receipt
        if receipt["sha256"] != "SELF":
            assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"], receipt

    workflow = (ROOT / ".github/workflows/202608272035-bounded-companies-house-candidate.yml").read_text()
    assert "workflow_dispatch" not in workflow
    assert 'test "$GITHUB_EVENT_NAME" = push' in workflow
    assert 'test "$GITHUB_REF" = refs/heads/main' in workflow
    assert 'test "$(git rev-list --parents -n 1 HEAD | wc -w)" -eq 2' in workflow
    assert 'test "$(git rev-parse HEAD^)" = "$BASE_COMMIT"' in workflow
    assert '--force-with-lease="$candidate_ref:"' in workflow
    assert 'HEAD:refs/heads/main' not in workflow
    assert "sparse-checkout-cone-mode: false" in workflow
    assert "/data/manifests/202608261927-build-manifest-v9-1.json" in workflow
    assert "data/current" in workflow
    assert "pages" in workflow and "releases" in workflow


def main() -> None:
    test_generation_and_fixed_plan()
    test_extractor_company_number_end_to_end()
    test_relationship_key_law()
    test_actual_landed_two_grain_readback()
    test_full_successor_seal_and_verify()
    test_source_manifest_and_workflow()
    print(
        json.dumps(
            {
                "status": "PASS",
                "generation": VERIFY.GENERATION,
                "company_number_domain": VERIFY.COMPANY_NUMBER.pattern,
                "company_key": ["company_number"],
                "relationship_key": ["company_number", "repd_ref", "match_type"],
                "archive_bytes": PLAN.EXPECTED_TOTAL_BYTES,
                "network_requests": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
