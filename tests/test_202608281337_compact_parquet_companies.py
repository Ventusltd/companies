#!/usr/bin/env python3
"""Deterministic contracts for the relationship/report-only Companies successor."""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import tempfile
import zipfile
from contextlib import contextmanager, redirect_stderr
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPACT = load(
    "build/python/202608281337-compact-parquet-companies.py",
    "companies_compact_202608281337_test",
)
FIXTURE = load(
    "tests/test_202608272155_sharded_cartridges.py",
    "companies_fixture_202608272155_for_compact",
)


def rejected(callable_, contains: str) -> None:
    try:
        callable_()
    except RuntimeError as exc:
        assert contains.casefold() in str(exc).casefold(), (contains, str(exc))
        return
    raise AssertionError(f"Expected RuntimeError containing {contains!r}")


def expected_schema(columns: tuple[tuple[str, str, bool], ...]) -> list[dict]:
    return [
        {"name": name, "type": type_name, "nullable": nullable}
        for name, type_name, nullable in columns
    ]


def expected_readback(columns: tuple[tuple[str, str, bool], ...]) -> list[dict]:
    return [{"name": name, "type": type_name} for name, type_name, _nullable in columns]


def expected_contract_schema(columns: tuple[tuple[str, str, bool], ...]) -> list[dict]:
    return [
        {"name": name, "duckdb_type": type_name, "nullable": nullable}
        for name, type_name, nullable in columns
    ]


def tiny_records() -> list[dict]:
    solar = FIXTURE.record(1)
    solar["repd_name_candidates"][0]["technology"] = "solar"
    wind = FIXTURE.record(2)
    wind["repd_name_candidates"][0]["technology"] = "wind_onshore"
    return [solar, wind]


def project_map(records: list[dict]) -> dict[str, dict]:
    return {
        str(edge["repd_ref"]): {"technology": edge["technology"]}
        for record in records
        for edge in record["repd_name_candidates"]
    }


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def doctor_fixture(root: Path) -> None:
    paths = set(COMPACT.SOURCE_BOUNDARY) | set(COMPACT.DEPENDENCY_SHA256)
    for relative in sorted(paths):
        source = ROOT / relative
        assert source.is_file(), relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def test_relationship_report_contract_and_doctor_fail_closed() -> None:
    contract_path = ROOT / COMPACT.CONTRACT_PATH
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert COMPACT.GENERATION == "202608272155"
    assert COMPACT.RESUME_GENERATION == "202608281337"
    assert COMPACT.DUCKDB_VERSION == "1.3.2"
    assert COMPACT.EXPECTED_SELECTED_COMPANIES == 294_904
    assert COMPACT.MAXIMUM_FILE_BYTES == 20_000_000
    assert COMPACT.MAXIMUM_TOTAL_BYTES == 30_000_000
    assert not hasattr(COMPACT, "COMPANY_PARQUET")
    assert contract["schema"] == "companies-house-relationship-report-contract-v1"
    assert contract["parquet_compression"] == "ZSTD"
    assert contract["expected_companies_selected"] == COMPACT.EXPECTED_SELECTED_COMPANIES
    assert contract["source_boundary"] == list(COMPACT.SOURCE_BOUNDARY)
    assert contract["dependency_sha256"] == COMPACT.DEPENDENCY_SHA256
    assert contract["maximum_file_bytes"] == COMPACT.MAXIMUM_FILE_BYTES
    assert contract["maximum_total_bytes"] == COMPACT.MAXIMUM_TOTAL_BYTES
    assert contract["relationship_schema"] == expected_contract_schema(COMPACT.RELATIONSHIP_COLUMNS)
    assert contract["solar_relationship_schema"] == expected_contract_schema(
        COMPACT.RELATIONSHIP_COLUMNS
    )
    assert contract["outputs"] == {
        "audit": COMPACT.AUDIT_PATH.as_posix(),
        "company_repd_candidates": COMPACT.RELATIONSHIP_PARQUET.as_posix(),
        "manifest": COMPACT.MANIFEST_PATH.as_posix(),
        "report": COMPACT.REPORT_PATH.as_posix(),
        "solar_company_repd_relationships": COMPACT.SOLAR_PARQUET.as_posix(),
    }
    assert contract["hard_gates"]["company_master_files"] == 0
    assert contract["hard_gates"]["company_master_rows"] == 0
    assert contract["hard_gates"]["bridge_columns_per_table"] == 3
    assert contract["hard_gates"]["companies_selected"] == COMPACT.EXPECTED_SELECTED_COMPANIES
    assert contract["hard_gates"]["descriptive_edge_columns"] == 0
    assert contract["hard_gates"]["embedded_relationship_json_fields"] == 0
    assert contract["hard_gates"]["exact_solar_subset"] is True
    assert contract["hard_gates"]["logical_json_cartridges"] == 0
    assert contract["hard_gates"]["raw_company_json_files"] == 0
    assert contract["hard_gates"]["raw_archives"] == 0
    assert contract["hard_gates"]["duplicate_corpus_builds"] == 0
    assert contract["hard_gates"]["promotion_eligible"] is False
    assert contract["hard_gates"]["per_row_digest_columns"] == 0
    assert contract["hard_gates"]["row_level_provenance_columns"] == 0
    assert COMPACT.RELATIONSHIP_COLUMNS == (
        ("company_number", "VARCHAR", False),
        ("repd_ref", "VARCHAR", False),
        ("evidence_type", "VARCHAR", False),
    )
    assert tuple(name for name, _type, _nullable in COMPACT.RELATIONSHIP_COLUMNS) == (
        COMPACT.RELATIONSHIP_KEY
    )
    assert not set(COMPACT.RELATIONSHIP_KEY) & COMPACT.FORBIDDEN_EDGE_COLUMNS

    assert COMPACT.doctor(ROOT) == {
        "status": "PASS",
        "generation": COMPACT.GENERATION,
        "resume_generation": COMPACT.RESUME_GENERATION,
        "source_files": len(COMPACT.SOURCE_BOUNDARY),
    }

    with tempfile.TemporaryDirectory(prefix="companies-relationship-doctor-") as temporary:
        fixture_root = Path(temporary)
        doctor_fixture(fixture_root)
        assert COMPACT.doctor(fixture_root)["status"] == "PASS"

        missing = fixture_root / COMPACT.SOURCE_BOUNDARY[0]
        missing.unlink()
        rejected(lambda: COMPACT.doctor(fixture_root), "source boundary is incomplete")
        shutil.copyfile(ROOT / COMPACT.SOURCE_BOUNDARY[0], missing)

        dependency = fixture_root / sorted(COMPACT.DEPENDENCY_SHA256)[0]
        dependency.write_bytes(dependency.read_bytes() + b"\n# drift\n")
        rejected(lambda: COMPACT.doctor(fixture_root), "pinned dependency drifted")
        shutil.copyfile(ROOT / dependency.relative_to(fixture_root), dependency)

        fixture_contract = fixture_root / COMPACT.CONTRACT_PATH
        drifted_contract = json.loads(fixture_contract.read_text(encoding="utf-8"))
        drifted_contract["maximum_total_bytes"] += 1
        fixture_contract.write_text(COMPACT.pretty_json(drifted_contract), encoding="utf-8")
        rejected(lambda: COMPACT.doctor(fixture_root), "contract drifted")


def assert_dataset_contract(dataset: dict, rows: int) -> None:
    assert dataset["status"] == "PASS"
    assert dataset["format"] == "parquet"
    assert dataset["compression"] == "zstd"
    assert dataset["compression_codecs"] == ["ZSTD"]
    assert dataset["declared_key"] == list(COMPACT.RELATIONSHIP_KEY)
    assert dataset["rows"] == dataset["distinct_keys"] == rows
    assert dataset["null_keys"] == 0
    assert dataset["duplicate_key_groups"] == 0
    assert dataset["required_column_null_rows"] == 0
    assert dataset["typed_column_mismatches"] == 0
    assert dataset["schema_contract"] == expected_schema(COMPACT.RELATIONSHIP_COLUMNS)
    assert dataset["schema_readback"] == expected_readback(COMPACT.RELATIONSHIP_COLUMNS)
    assert dataset["file"]["bytes"] < COMPACT.MAXIMUM_FILE_BYTES
    assert Path(dataset["file"]["path"]).suffix == ".parquet"
    assert dataset["evidence_class"] == "CANDIDATE"
    assert dataset["identity_posture"] == "CANDIDATE_ONLY_NOT_CONFIRMED_OWNERSHIP"


def test_two_deterministic_relationship_parquets_and_solar_exact_subset() -> None:
    records = tiny_records()
    projects = project_map(records)
    with tempfile.TemporaryDirectory(prefix="companies-relationship-parquet-") as temporary:
        base = Path(temporary)
        first = base / "first"
        second = base / "second"
        first.mkdir()
        second.mkdir()
        first_audit = COMPACT.build_datasets(first, records, projects)
        second_audit = COMPACT.build_datasets(second, list(reversed(records)), projects)

        assert first_audit == second_audit
        assert tree_bytes(first) == tree_bytes(second)
        assert set(tree_bytes(first)) == {
            COMPACT.RELATIONSHIP_PARQUET.as_posix(),
            COMPACT.SOLAR_PARQUET.as_posix(),
        }
        datasets = first_audit["datasets"]
        assert set(datasets) == {
            "company_repd_candidates",
            "solar_company_repd_relationships",
        }
        assert_dataset_contract(datasets["company_repd_candidates"], 2)
        assert_dataset_contract(datasets["solar_company_repd_relationships"], 1)
        assert (
            sum(path.stat().st_size for path in first.iterdir())
            < COMPACT.MAXIMUM_TOTAL_BYTES
        )

        all_rows = COMPACT.read_relationship_rows(first / COMPACT.RELATIONSHIP_PARQUET)
        landed_solar_rows = COMPACT.read_relationship_rows(first / COMPACT.SOLAR_PARQUET)
        assert landed_solar_rows == COMPACT.solar_rows(all_rows, projects)
        assert all_rows == [
            ("00000001", "10001", "EXACT_OPERATOR_NAME"),
            ("00000002", "10002", "EXACT_OPERATOR_NAME"),
        ]
        assert landed_solar_rows == [("00000001", "10001", "EXACT_OPERATOR_NAME")]
        assert first_audit["relational_integrity"] == {
            "pinned_repd_join": True,
            "unknown_repd_refs": 0,
            "solar_rows_outside_parent": 0,
            "solar_rows_outside_predicate": 0,
            "expected_solar_rows_missing": 0,
            "solar_predicate": "pinned_repd.technology = 'solar'",
        }
        column_names = {name for name, _type, _nullable in COMPACT.RELATIONSHIP_COLUMNS}
        assert column_names == set(COMPACT.RELATIONSHIP_KEY)
        assert column_names.isdisjoint(COMPACT.FORBIDDEN_EDGE_COLUMNS)

    with tempfile.TemporaryDirectory(prefix="companies-solar-subset-tamper-") as temporary:
        root = Path(temporary)
        COMPACT.build_datasets(root, records, projects)
        all_rows = COMPACT.read_relationship_rows(root / COMPACT.RELATIONSHIP_PARQUET)
        solar_path = root / COMPACT.SOLAR_PARQUET
        solar_path.unlink()
        COMPACT.ENGINE.write_parquet(
            solar_path,
            COMPACT.RELATIONSHIP_COLUMNS,
            all_rows,
            COMPACT.RELATIONSHIP_KEY,
        )
        rejected(
            lambda: COMPACT.audit_relational_integrity(
                root / COMPACT.RELATIONSHIP_PARQUET,
                solar_path,
                projects,
            ),
            "exact pinned-REPD relational subset",
        )
        solar_path.unlink()
        COMPACT.ENGINE.write_parquet(
            solar_path,
            COMPACT.RELATIONSHIP_COLUMNS,
            [all_rows[1]],
            COMPACT.RELATIONSHIP_KEY,
        )
        rejected(
            lambda: COMPACT.audit_relational_integrity(
                root / COMPACT.RELATIONSHIP_PARQUET,
                solar_path,
                projects,
            ),
            "exact pinned-REPD relational subset",
        )

    duplicate = FIXTURE.record(1)
    with tempfile.TemporaryDirectory(prefix="companies-relationship-duplicate-") as temporary:
        root = Path(temporary)
        rejected(
            lambda: COMPACT.build_datasets(
                root,
                [duplicate, dict(duplicate)],
                project_map([duplicate]),
            ),
            "duplicate",
        )

    wind_only = FIXTURE.record(2)
    wind_only["repd_name_candidates"][0]["technology"] = "wind_onshore"
    with tempfile.TemporaryDirectory(prefix="companies-relationship-no-solar-") as temporary:
        root = Path(temporary)
        rejected(
            lambda: COMPACT.build_datasets(root, [wind_only], project_map([wind_only])),
            "solar company–REPD relationship dataset is empty",
        )


def test_bridge_keys_and_pinned_technology_fail_closed() -> None:
    assert COMPACT.edge_tuple(
        "00000001", "10001", "EXACT_OPERATOR_NAME"
    ) == ("00000001", "10001", "EXACT_OPERATOR_NAME")
    rejected(
        lambda: COMPACT.edge_tuple("invalid", "10001", "EXACT_OPERATOR_NAME"),
        "bridge identity",
    )
    rejected(
        lambda: COMPACT.edge_tuple("00000001", "10001 ", "EXACT_OPERATOR_NAME"),
        "bridge identity",
    )
    rejected(
        lambda: COMPACT.edge_tuple("00000001", "10001", "INVENTED_MATCH"),
        "bridge identity",
    )

    fuzzy = FIXTURE.record(1)
    fuzzy["repd_name_candidates"][0]["technology"] = "Solar Photovoltaics"
    rejected(
        lambda: COMPACT.relationship_rows([fuzzy], project_map([fuzzy])),
        "pinned REPD technology drifted",
    )
    mismatched_projects = project_map([FIXTURE.record(1)])
    mismatched_projects["10001"]["technology"] = "wind_onshore"
    rejected(
        lambda: COMPACT.relationship_rows([FIXTURE.record(1)], mismatched_projects),
        "pinned REPD technology drifted",
    )

    with tempfile.TemporaryDirectory(prefix="companies-relationship-schema-drift-") as temporary:
        root = Path(temporary)
        record = FIXTURE.record(1)
        COMPACT.build_datasets(root, [record], project_map([record]))
        source = root / COMPACT.RELATIONSHIP_PARQUET
        tampered = root / "tampered.parquet"
        duckdb = COMPACT.ENGINE.load_duckdb()
        connection = duckdb.connect(":memory:")
        try:
            connection.execute("SET threads = 1")
            source_sql = COMPACT.ENGINE.sql_path(source)
            tampered_sql = COMPACT.ENGINE.sql_path(tampered)
            connection.execute(
                "COPY (SELECT *, 'forbidden' AS relationship_repository "
                f"FROM read_parquet('{source_sql}')) TO '{tampered_sql}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        finally:
            connection.close()
        rejected(
            lambda: COMPACT.read_relationship_rows(tampered),
            "column closure drifted",
        )


def test_one_million_key_only_edges_fit_the_file_cap() -> None:
    with tempfile.TemporaryDirectory(prefix="companies-relationship-scale-") as temporary:
        path = Path(temporary) / "million-key-only-edges.parquet"
        duckdb = COMPACT.ENGINE.load_duckdb()
        connection = duckdb.connect(":memory:")
        try:
            connection.execute("SET threads = 1")
            escaped = COMPACT.ENGINE.sql_path(path)
            connection.execute(
                "COPY (SELECT lpad(i::VARCHAR, 8, '0') AS company_number, "
                "(1000000 + i)::VARCHAR AS repd_ref, "
                "'EXACT_OPERATOR_NAME'::VARCHAR AS evidence_type "
                "FROM range(1000000) t(i)) "
                f"TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
            )
            assert connection.execute(
                f"SELECT count(*) FROM read_parquet('{escaped}')"
            ).fetchone()[0] == 1_000_000
            assert connection.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{escaped}')"
            ).fetchall() == [
                ("company_number", "VARCHAR", "YES", None, None, None),
                ("repd_ref", "VARCHAR", "YES", None, None, None),
                ("evidence_type", "VARCHAR", "YES", None, None, None),
            ]
            assert {
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT compression FROM parquet_metadata('{escaped}')"
                ).fetchall()
            } == {"ZSTD"}
        finally:
            connection.close()
        assert path.stat().st_size < COMPACT.MAXIMUM_FILE_BYTES


def write_basic_zip(path: Path, rows: list[str], header: str | None = None) -> None:
    header = header or (
        "CompanyName,CompanyNumber,CompanyStatus,SICCode.SicText_1,"
        "SICCode.SicText_2,SICCode.SicText_3,SICCode.SicText_4"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("BasicCompanyData-fixture.csv", "\n".join([header, *rows]) + "\n")


def test_transient_basic_csv_scan_counts_selection_and_normalized_edges() -> None:
    rows = [
        "SUNLIGHT OPERATOR LIMITED,00000011,Active,,,,",
        "WIND RIDGE LIMITED,00000012,Active,,,,",
        "INDUSTRIAL WORKS LIMITED,00000013,Active,24100 - Manufacture of basic iron and steel,,,",
        "UNRELATED RETAIL LIMITED,00000014,Active,47190 - Other retail sale,,,",
    ]
    projects_payload = {
        "projects": [
            {
                "repd_ref": "20001",
                "gg_project_id": "GG2050-REPD-20001",
                "name": "Amber Field",
                "operator": "Sunlight Operator Limited",
                "technology": "solar",
                "capacity_mw": 25,
                "status": "Operational",
                "geometry_status": "valid",
                "latitude": 52.1,
                "longitude": -1.2,
            },
            {
                "repd_ref": "20002",
                "gg_project_id": "GG2050-REPD-20002",
                "name": "Copper Moor",
                "operator": "Wind Ridge Limited",
                "technology": "wind_onshore",
                "capacity_mw": 30,
                "status": "Operational",
                "geometry_status": "valid",
                "latitude": 53.1,
                "longitude": -2.2,
            },
        ]
    }
    account_facts = {
        "00000013": {
            "accounts_date": "2025-12-31",
            "total_assets": 15_000_000,
            "net_assets": 8_000_000,
            "turnover": None,
            "cash": None,
        }
    }
    with tempfile.TemporaryDirectory(prefix="companies-transient-basic-scan-") as temporary:
        root = Path(temporary)
        archive = root / "BasicCompanyData-fixture.zip"
        repd = root / "repd"
        repd.mkdir()
        (repd / "projects.json").write_text(
            json.dumps(projects_payload), encoding="utf-8"
        )
        write_basic_zip(
            archive,
            rows,
            (
                "Company Name,Company Number,Company Status,SIC Code Sic Text 1,"
                "SIC Code Sic Text 2,SIC Code Sic Text 3,SIC Code Sic Text 4"
            ),
        )

        original_heartbeat = COMPACT.BASIC_SCAN_HEARTBEAT_ROWS
        heartbeat_stream = io.StringIO()
        COMPACT.BASIC_SCAN_HEARTBEAT_ROWS = 2
        try:
            with redirect_stderr(heartbeat_stream):
                raw_records, summary = COMPACT.select_relationship_records(
                    archive, account_facts, repd
                )
        finally:
            COMPACT.BASIC_SCAN_HEARTBEAT_ROWS = original_heartbeat
        heartbeats = [
            json.loads(line) for line in heartbeat_stream.getvalue().splitlines()
        ]
        assert [event["basic_company_rows_scanned"] for event in heartbeats] == [2, 4]
        assert all(event["event"] == "basic_company_scan_progress" for event in heartbeats)
        assert heartbeats[-1] == {
            "event": "basic_company_scan_progress",
            "basic_company_rows_scanned": 4,
            "selected_companies": 3,
            "companies_with_repd_candidates": 2,
            "candidate_relationship_rows": 2,
        }
        assert summary == {
            "basic_company_rows_scanned": 4,
            "selected_companies": 3,
            "assets_gte_10m_companies": 1,
            "energy_relevant_large_companies": 1,
            "probable_project_spvs": 1,
            "companies_with_repd_candidates": 2,
            "candidate_relationship_rows": 2,
            "btm_tag_counts": {
                "BTM_METALS_ENGINEERING": 1,
                "INDUSTRIAL_SIC_B_TO_E": 1,
            },
        }, summary
        assert summary["basic_company_rows_scanned"] > summary["selected_companies"]
        assert [record["company_number"] for record in raw_records] == [
            "00000011",
            "00000012",
        ]

        projects, _manifest = COMPACT.LEGACY.repd_closure(repd)
        enriched = COMPACT.enrich_relationship_records(raw_records, projects)
        relationship_rows = COMPACT.relationship_rows(enriched, projects)
        solar_relationship_rows = COMPACT.solar_rows(relationship_rows, projects)
        assert relationship_rows == [
            ("00000011", "20001", "EXACT_OPERATOR_NAME"),
            ("00000012", "20002", "EXACT_OPERATOR_NAME"),
        ]
        assert solar_relationship_rows == [
            ("00000011", "20001", "EXACT_OPERATOR_NAME")
        ]

        duplicate_archive = root / "BasicCompanyData-duplicate.zip"
        write_basic_zip(duplicate_archive, [rows[0], rows[0]])
        rejected(
            lambda: COMPACT.select_relationship_records(
                duplicate_archive, account_facts, repd
            ),
            "duplicated selected company",
        )


def closure_fixture(root: Path, evidence: list[dict] | None = None) -> dict:
    manifest = {"evidence": evidence or []}
    for relative in (
        COMPACT.MANIFEST_PATH,
        COMPACT.RELATIONSHIP_PARQUET,
        COMPACT.SOLAR_PARQUET,
        COMPACT.REPORT_PATH,
        COMPACT.AUDIT_PATH,
    ):
        (root / relative).write_bytes(f"fixture:{relative}\n".encode())
    return manifest


def test_exact_closure_rejects_company_master_raw_json_and_symlinks() -> None:
    with tempfile.TemporaryDirectory(prefix="companies-relationship-closure-pass-") as temporary:
        root = Path(temporary)
        files, total = COMPACT.exact_file_closure(root, closure_fixture(root))
        assert len(files) == 5
        assert 0 < total < COMPACT.MAXIMUM_TOTAL_BYTES

    with tempfile.TemporaryDirectory(prefix="companies-relationship-company-master-") as temporary:
        root = Path(temporary)
        company_master = root / "companies-v1.parquet"
        company_master.write_bytes(b"forbidden company master")
        manifest = closure_fixture(root, evidence=[{"path": company_master.name}])
        rejected(
            lambda: COMPACT.exact_file_closure(root, manifest),
            "company-master Parquet leaked",
        )

    with tempfile.TemporaryDirectory(prefix="companies-relationship-raw-") as temporary:
        root = Path(temporary)
        raw = root / "source.zip"
        raw.write_bytes(b"raw")
        manifest = closure_fixture(root, evidence=[{"path": raw.name}])
        rejected(
            lambda: COMPACT.exact_file_closure(root, manifest),
            "database or transport data leaked",
        )

    with tempfile.TemporaryDirectory(prefix="companies-relationship-database-") as temporary:
        root = Path(temporary)
        database = root / "companies.duckdb"
        database.write_bytes(b"forbidden database")
        manifest = closure_fixture(root, evidence=[{"path": database.name}])
        rejected(
            lambda: COMPACT.exact_file_closure(root, manifest),
            "database or transport data leaked",
        )

    with tempfile.TemporaryDirectory(prefix="companies-relationship-json-") as temporary:
        root = Path(temporary)
        manifest = closure_fixture(root)
        (root / "selected-companies.json").write_text("{}\n", encoding="utf-8")
        rejected(lambda: COMPACT.exact_file_closure(root, manifest), "file closure drifted")

    with tempfile.TemporaryDirectory(prefix="companies-relationship-link-") as temporary:
        root = Path(temporary)
        manifest = closure_fixture(root)
        (root / "linked.parquet").symlink_to(root / COMPACT.RELATIONSHIP_PARQUET)
        rejected(lambda: COMPACT.exact_file_closure(root, manifest), "symlink")


@contextmanager
def compact_limits(file_bytes: int, total_bytes: int):
    original_file = COMPACT.MAXIMUM_FILE_BYTES
    original_total = COMPACT.MAXIMUM_TOTAL_BYTES
    COMPACT.MAXIMUM_FILE_BYTES = file_bytes
    COMPACT.MAXIMUM_TOTAL_BYTES = total_bytes
    try:
        yield
    finally:
        COMPACT.MAXIMUM_FILE_BYTES = original_file
        COMPACT.MAXIMUM_TOTAL_BYTES = original_total


def test_compact_byte_policy_is_a_hard_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="companies-relationship-size-") as temporary:
        root = Path(temporary)
        manifest = closure_fixture(root)
        _files, measured_total = COMPACT.exact_file_closure(root, manifest)
        largest = max(path.stat().st_size for path in root.iterdir())

        with compact_limits(largest - 1, measured_total + 1):
            rejected(lambda: COMPACT.exact_file_closure(root, manifest), "byte gate failed")
        with compact_limits(largest + 1, measured_total - 1):
            rejected(lambda: COMPACT.exact_file_closure(root, manifest), "byte gate failed")


@contextmanager
def expected_company_count(value: int):
    original = COMPACT.EXPECTED_SELECTED_COMPANIES
    COMPACT.EXPECTED_SELECTED_COMPANIES = value
    try:
        yield
    finally:
        COMPACT.EXPECTED_SELECTED_COMPANIES = original


@contextmanager
def pinned_fixture_sources(root: Path):
    plan_path, evidence_root, repd, _raw, basic, accounts, rest, basic_report = (
        FIXTURE.successor_seal_fixture(root)
    )
    (repd / "projects.json").write_text(
        json.dumps(
            {
                "projects": [
                    {"repd_ref": "10001", "technology": "solar"},
                    {"repd_ref": "10002", "technology": "wind_onshore"},
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    plan = COMPACT.LEGACY.load_plan(plan_path)
    plan["_path"] = str(plan_path)
    receipts = COMPACT.LEGACY.collect_receipts(evidence_root, plan)
    extractions = COMPACT.LEGACY.collect_extractions(evidence_root, receipts)
    projects, repd_manifest = COMPACT.LEGACY.repd_closure(repd)
    replacements = {
        "EXPECTED_PLAN_SHA256": COMPACT.digest(plan_path),
        "EXPECTED_REST_EVIDENCE_SHA256": COMPACT.digest(rest),
        "EXPECTED_REPD_PATHS": [row["path"] for row in repd_manifest["files"]],
        "EXPECTED_REPD_CLOSURE_SHA256": repd_manifest["sha256"],
        "EXPECTED_REPD_TOTAL_BYTES": sum(row["bytes"] for row in repd_manifest["files"]),
        "EXPECTED_REPD_PROJECTS": repd_manifest["projects"],
    }
    originals = {name: getattr(COMPACT.BASE, name) for name in replacements}
    for name, value in replacements.items():
        setattr(COMPACT.BASE, name, value)
    try:
        yield {
            "plan_path": plan_path,
            "evidence_root": evidence_root,
            "receipts": receipts,
            "extractions": extractions,
            "repd_manifest": repd_manifest,
            "projects": projects,
            "repd": repd,
            "basic_archive": next(basic.glob("*.zip")),
            "accounts": accounts,
            "rest": rest,
            "basic_report": basic_report,
        }
    finally:
        for name, value in originals.items():
            setattr(COMPACT.BASE, name, value)


def write_full_tiny_candidate(
    output: Path,
    records: list[dict],
    source_commit: str,
    sources: dict,
) -> dict:
    output.mkdir()
    evidence = COMPACT.BASE.copy_evidence(
        output,
        sources["plan_path"],
        sources["evidence_root"],
        sources["evidence_root"],
        sources["receipts"],
        sources["extractions"],
        sources["rest"],
        sources["basic_report"],
    )
    audit = COMPACT.build_datasets(output, records, sources["projects"])
    (output / COMPACT.AUDIT_PATH).write_text(COMPACT.pretty_json(audit), encoding="utf-8")
    relationship_count = audit["datasets"]["company_repd_candidates"]["rows"]
    solar_count = audit["datasets"]["solar_company_repd_relationships"]["rows"]
    distinct_companies = len({record["company_number"] for record in records})
    selection = {
        "basic_company_rows_scanned": len(records) + 1,
        "selected_companies": len(records),
        "assets_gte_10m_companies": len(records),
        "energy_relevant_large_companies": len(records),
        "probable_project_spvs": 0,
        "companies_with_repd_candidates": distinct_companies,
        "candidate_relationship_rows": relationship_count,
        "btm_tag_counts": {"INDUSTRIAL_SIC_B_TO_E": len(records)},
    }
    report = {
        "schema": "companies-house-cross-repository-relationship-report-v1",
        "generation": COMPACT.GENERATION,
        "resume_generation": COMPACT.RESUME_GENERATION,
        "generated_at": COMPACT.FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "basic_company_rows_scanned": selection["basic_company_rows_scanned"],
        "companies_selected": len(records),
        "companies_with_repd_candidates": distinct_companies,
        "company_repd_candidates": relationship_count,
        "solar_company_repd_relationships": solar_count,
        "selection_summary": selection,
        "durable_output": {
            "primary_product": "CROSS_REPOSITORY_RELATIONSHIP_REPORT",
            "bridge_columns_per_table": 3,
            "company_master_files": 0,
            "company_master_rows": 0,
            "descriptive_edge_columns": 0,
            "embedded_relationship_json_fields": 0,
            "per_row_digest_columns": 0,
            "raw_company_files": 0,
            "relationship_tables": [
                COMPACT.RELATIONSHIP_PARQUET.as_posix(),
                COMPACT.SOLAR_PARQUET.as_posix(),
            ],
            "row_level_provenance_columns": 0,
        },
        "datasets": audit["datasets"],
    }
    (output / COMPACT.REPORT_PATH).write_text(COMPACT.pretty_json(report), encoding="utf-8")
    rest_evidence = COMPACT.LEGACY.load_rest_evidence(sources["rest"])
    accounts_records = sum(
        1
        for line in sources["accounts"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    manifest = {
        "schema": "companies-house-relationship-report-candidate-v1",
        "generation": COMPACT.GENERATION,
        "resume_generation": COMPACT.RESUME_GENERATION,
        "generated_at": COMPACT.FIXED_GENERATED_AT,
        "source_commit": source_commit,
        "supersedes_failed_run_id": COMPACT.SUPERSEDED_FAILED_RUN_ID,
        "deployment_state": "not-authorised",
        "promotion_eligible": False,
        "coverage": COMPACT.BASE.COVERAGE,
        "threshold_gbp": 10_000_000,
        "financial_currency": "GBP",
        "basic_company_rows_scanned": selection["basic_company_rows_scanned"],
        "companies_selected": len(records),
        "companies_with_repd_candidates": distinct_companies,
        "company_repd_candidates": relationship_count,
        "solar_company_repd_relationships": solar_count,
        "privacy": COMPACT.BASE.PRIVACY,
        "usage_context": "NON_COMMERCIAL_OPEN_SOURCE",
        "source_licences": COMPACT.ENGINE.MATERIALISED_SOURCES,
        "source_rights_are_distinct_from_usage_context": True,
        "filing_truth_caveat": COMPACT.FILING_TRUTH_CAVEAT,
        "relationship_truth_caveat": COMPACT.RELATIONSHIP_TRUTH_CAVEAT,
        "publication": COMPACT.PUBLICATION,
        "inputs": {
            "acquisition_run_id": COMPACT.EXPECTED_ACQUISITION_RUN_ID,
            "acquisition_source_commit": COMPACT.EXPECTED_ACQUISITION_SOURCE_COMMIT,
            "retained_artifacts": COMPACT.RETAINED_ARTIFACTS,
            "source_parent_commit": COMPACT.EXPECTED_MAIN_PARENT_COMMIT,
            "companies_base_commit": COMPACT.BASE.BASE_COMMIT,
            "pipelinenews_commit": COMPACT.EXPECTED_PIPELINENEWS_COMMIT,
            "download_plan_sha256": COMPACT.BASE.EXPECTED_PLAN_SHA256,
            "basic_archive_sha256": COMPACT.digest(sources["basic_archive"]),
            "basic_validation_sha256": COMPACT.digest(sources["basic_report"]),
            "accounts_latest_sha256": COMPACT.digest(sources["accounts"]),
            "accounts_latest_records": accounts_records,
            "repd": sources["repd_manifest"],
            "repd_runtime_read": {
                "repository": "Ventusltd/pipelinenews",
                "commit": COMPACT.EXPECTED_PIPELINENEWS_COMMIT,
                "path": "data/projects",
                "mode": "read-only sparse checkout",
                "foreign_repository_files_committed": False,
                "foreign_data_materialised": True,
            },
            "optional_rest": {
                "enabled": rest_evidence["enabled"],
                "status": rest_evidence["status"],
                "evidence_sha256": COMPACT.BASE.EXPECTED_REST_EVIDENCE_SHA256,
            },
            "news": {"included": False, "identity_policy": "annotation-only"},
        },
        "datasets": audit["datasets"],
        "report": COMPACT.receipt(output / COMPACT.REPORT_PATH, output),
        "evidence": evidence,
        "audit": COMPACT.receipt(output / COMPACT.AUDIT_PATH, output),
        "output_policy": {
            "canonical_relationship_format": "PARQUET",
            "aggregate_report_format": "JSON",
            "duckdb_version": COMPACT.DUCKDB_VERSION,
            "relationship_tables": 2,
            "bridge_columns_per_table": 3,
            "company_master_files": 0,
            "company_master_rows": 0,
            "descriptive_edge_columns": 0,
            "embedded_relationship_json_fields": 0,
            "logical_json_cartridges": 0,
            "per_row_digest_columns": 0,
            "raw_company_json_files": 0,
            "raw_archives": 0,
            "row_level_provenance_columns": 0,
            "duplicate_corpus_builds": 0,
            "maximum_file_bytes": COMPACT.MAXIMUM_FILE_BYTES,
            "maximum_candidate_total_bytes": COMPACT.MAXIMUM_TOTAL_BYTES,
            "exact_file_closure_enforced": True,
        },
    }
    assert set(manifest) == COMPACT.MANIFEST_KEYS
    assert set(manifest["inputs"]) == COMPACT.INPUT_KEYS
    (output / COMPACT.MANIFEST_PATH).write_text(
        COMPACT.pretty_json(manifest), encoding="utf-8"
    )
    return manifest


def test_verify_full_tiny_report_manifest_with_pinned_count_override() -> None:
    records = tiny_records()
    source_commit = "d" * 40
    with tempfile.TemporaryDirectory(prefix="companies-relationship-verify-") as temporary:
        root = Path(temporary)
        with pinned_fixture_sources(root) as sources, expected_company_count(len(records)):
            candidate = root / "candidate"
            manifest = write_full_tiny_candidate(candidate, records, source_commit, sources)
            result = COMPACT.verify(candidate, source_commit, sources["repd"])
            assert result["status"] == "PASS"
            assert result["basic_company_rows_scanned"] == 3
            assert result["companies_selected"] == 2
            assert result["companies_with_repd_candidates"] == 2
            assert result["company_repd_candidates"] == 2
            assert result["solar_company_repd_relationships"] == 1
            assert result["candidate_files"] == 15
            assert 0 < result["candidate_bytes"] < COMPACT.MAXIMUM_TOTAL_BYTES
            assert len(manifest["evidence"]) == 10
            assert manifest["output_policy"]["company_master_files"] == 0
            assert manifest["output_policy"]["company_master_rows"] == 0
            assert manifest["output_policy"]["bridge_columns_per_table"] == 3
            assert manifest["output_policy"]["descriptive_edge_columns"] == 0
            assert manifest["output_policy"]["embedded_relationship_json_fields"] == 0
            assert manifest["output_policy"]["per_row_digest_columns"] == 0
            assert manifest["output_policy"]["row_level_provenance_columns"] == 0
            assert not (candidate / "companies-v1.parquet").exists()
            report = json.loads((candidate / COMPACT.REPORT_PATH).read_text(encoding="utf-8"))
            assert report["durable_output"] == {
                "primary_product": "CROSS_REPOSITORY_RELATIONSHIP_REPORT",
                "bridge_columns_per_table": 3,
                "company_master_files": 0,
                "company_master_rows": 0,
                "descriptive_edge_columns": 0,
                "embedded_relationship_json_fields": 0,
                "per_row_digest_columns": 0,
                "raw_company_files": 0,
                "relationship_tables": [
                    COMPACT.RELATIONSHIP_PARQUET.as_posix(),
                    COMPACT.SOLAR_PARQUET.as_posix(),
                ],
                "row_level_provenance_columns": 0,
            }
            assert (candidate / COMPACT.AUDIT_PATH).is_file()

            original_manifest = (candidate / COMPACT.MANIFEST_PATH).read_text(
                encoding="utf-8"
            )
            drifted = json.loads(original_manifest)
            drifted["inputs"]["pipelinenews_commit"] = "e" * 40
            (candidate / COMPACT.MANIFEST_PATH).write_text(
                COMPACT.pretty_json(drifted), encoding="utf-8"
            )
            rejected(
                lambda: COMPACT.verify(candidate, source_commit, sources["repd"]),
                "input provenance drifted",
            )
            (candidate / COMPACT.MANIFEST_PATH).write_text(
                original_manifest, encoding="utf-8"
            )

            drifted = json.loads(original_manifest)
            drifted["basic_company_rows_scanned"] += 1
            (candidate / COMPACT.MANIFEST_PATH).write_text(
                COMPACT.pretty_json(drifted), encoding="utf-8"
            )
            rejected(
                lambda: COMPACT.verify(candidate, source_commit, sources["repd"]),
                "aggregate selection report drifted",
            )
            (candidate / COMPACT.MANIFEST_PATH).write_text(
                original_manifest, encoding="utf-8"
            )

            rejected(
                lambda: COMPACT.verify(
                    candidate, "not-a-source-commit", sources["repd"]
                ),
                "source commit is invalid",
            )
        assert COMPACT.EXPECTED_SELECTED_COMPANIES == 294_904


def main() -> None:
    test_relationship_report_contract_and_doctor_fail_closed()
    test_two_deterministic_relationship_parquets_and_solar_exact_subset()
    test_bridge_keys_and_pinned_technology_fail_closed()
    test_one_million_key_only_edges_fit_the_file_cap()
    test_transient_basic_csv_scan_counts_selection_and_normalized_edges()
    test_exact_closure_rejects_company_master_raw_json_and_symlinks()
    test_compact_byte_policy_is_a_hard_gate()
    test_verify_full_tiny_report_manifest_with_pinned_count_override()
    print(
        json.dumps(
            {
                "status": "PASS",
                "generation": COMPACT.GENERATION,
                "resume_generation": COMPACT.RESUME_GENERATION,
                "durable_product": "CROSS_REPOSITORY_RELATIONSHIP_REPORT",
                "relationship_tables": 2,
                "company_master_files": 0,
                "embedded_relationship_json_fields": 0,
                "compression": "ZSTD",
                "relationship_key": list(COMPACT.RELATIONSHIP_KEY),
                "network_requests": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
