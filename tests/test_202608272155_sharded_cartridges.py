#!/usr/bin/env python3
"""Deterministic shard and Parquet contracts for the 202608272155 successor."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = load(
    "build/python/202608272155-verify-companies-house-candidate.py",
    "companies_verify_202608272155_test",
)
PLAN = load(
    "build/python/202608272155-freeze-companies-house-plan.py",
    "companies_plan_202608272155_test",
)
BASE_FIXTURE = load(
    "tests/test_202608271507_bounded_companies_house.py",
    "companies_fixture_202608271507_for_2155",
)


def rejected(callable_, contains: str) -> None:
    try:
        callable_()
    except RuntimeError as exc:
        assert contains.lower() in str(exc).lower(), (contains, str(exc))
        return
    raise AssertionError(f"Expected RuntimeError containing {contains!r}")


def relationship(ref: str) -> dict:
    return {
        "repd_ref": ref,
        "match_type": "EXACT_OPERATOR_NAME",
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


def record(index: int, padding: int = 0, company_name: str | None = None) -> dict:
    number = f"{index:08d}"
    value = {
        "company_name": company_name or f"FIXTURE {number} LIMITED",
        "company_number": number,
        "company_status": "Active",
        "sic_codes": ["35110 - Production of electricity"],
        "accounts_date": "2025-12-31",
        "total_assets": 15_000_000 + index,
        "net_assets": "8000000.25",
        "turnover": None,
        "cash": 500_000.5,
        "assets_gte_10m": True,
        "energy_relevant_large_company": True,
        "btm_tags": ["INDUSTRIAL_SIC_B_TO_E"],
        "repd_name_candidates": [relationship(str(10_000 + index))],
        "probable_project_spv": False,
        "classification": "REPD_NAME_CANDIDATE",
        "financial_currency": "GBP",
        "news_identity_policy": "NEWS_MAY_ANNOTATE_BUT_NEVER_ESTABLISH_IDENTITY",
    }
    if padding:
        # Deliberately inert, non-personal fixture material used only to exercise
        # byte partitioning without manufacturing thousands of company rows.
        value["fixture_padding"] = "x" * padding
    return value


@contextmanager
def shard_target_for_test(value: int):
    """Temporarily lower both executable and declared limits, then restore them."""
    original_target = VERIFY.SHARD_TARGET_BYTES
    original_policy = VERIFY.SHARD_POLICY["target_bytes_including_envelope_and_lf"]
    VERIFY.SHARD_TARGET_BYTES = value
    VERIFY.SHARD_POLICY["target_bytes_including_envelope_and_lf"] = value
    try:
        yield
    finally:
        VERIFY.SHARD_TARGET_BYTES = original_target
        VERIFY.SHARD_POLICY["target_bytes_including_envelope_and_lf"] = original_policy


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def refresh_physical_receipt(root: Path, receipt: dict) -> None:
    path = root / receipt["path"]
    receipt["bytes"] = path.stat().st_size
    receipt["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_generation_and_partition_contract() -> None:
    assert VERIFY.GENERATION == "202608272155"
    assert VERIFY.MANIFEST_SCHEMA == "companies-house-bounded-candidate-v2"
    assert VERIFY.SHARD_SCHEMA == "companies-house-cartridge-shard-v2"
    assert VERIFY.PARTITION_SCHEME == "company-number-ordered-greedy-byte-bound-v1"
    assert VERIFY.DECLARED_KEY == ["company_number"]
    assert VERIFY.DUCKDB_VERSION == "1.3.2"
    assert VERIFY.DATA_DISCIPLINE["logical_json_partitioning"] == VERIFY.PARTITION_SCHEME
    assert VERIFY.DATA_DISCIPLINE["published_file_maximum_bytes"] == 90_000_000
    assert VERIFY.DATA_DISCIPLINE["candidate_total_maximum_bytes"] == 200_000_000
    assert VERIFY.DATA_DISCIPLINE["aggregate_file_count_and_bytes"] == (
        "MONITORS_WITH_HARD_PUBLICATION_RESOURCE_GATES"
    )


def build_deterministic_fixture(root: Path, records: list[dict]) -> dict[str, dict]:
    root.mkdir()
    cartridges = {}
    for logical_name in sorted(VERIFY.EXPECTED_CARTRIDGES):
        cartridges[logical_name] = VERIFY.write_logical_cartridge(root, logical_name, records)
    audit = VERIFY.build_analytical_datasets(root, records)
    (root / VERIFY.AUDIT_PATH).write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return cartridges


def test_forced_multishard_exact_bytes_and_deterministic_tree() -> None:
    records = [record(index, padding=7_000) for index in range(1, 6)]
    test_target = 14_000
    with shard_target_for_test(test_target), tempfile.TemporaryDirectory(
        prefix="companies-2155-forced-shards-"
    ) as temporary:
        base = Path(temporary)

        # Prove the partition prediction is the exact final encoded file size,
        # not an estimate based on payload rows alone.
        logical_name = sorted(VERIFY.EXPECTED_CARTRIDGES)[0]
        predicted_groups, predicted_union_digest = VERIFY.partition_records(logical_name, records)
        assert len(predicted_groups) > 1
        assert predicted_union_digest == VERIFY.record_digest(records)
        assert sum(len(group) for group, _encoded, _size in predicted_groups) == len(records)
        for ordinal, (group, encoded, predicted_size) in enumerate(predicted_groups):
            rendered = VERIFY.render_shard_from_encoded(logical_name, ordinal, encoded)
            assert len(group) >= 1
            assert len(rendered) == predicted_size <= test_target

        first = base / "candidate-a"
        second = base / "candidate-b"
        first_cartridges = build_deterministic_fixture(first, records)
        second_cartridges = build_deterministic_fixture(second, records)
        assert first_cartridges == second_cartridges
        assert tree_bytes(first) == tree_bytes(second)

        for logical_name, entry in first_cartridges.items():
            assert len(entry["shards"]) > 1
            assert entry["records"] == entry["distinct_keys"] == len(records)
            assert entry["record_universe_sha256"] == VERIFY.record_digest(records)
            predicted, predicted_union_digest = VERIFY.partition_records(logical_name, records)
            assert predicted_union_digest == entry["record_universe_sha256"]
            assert [row[2] for row in predicted] == [row["bytes"] for row in entry["shards"]]
            for receipt in entry["shards"]:
                path = first / receipt["path"]
                assert path.stat().st_size == receipt["bytes"] <= test_target
                assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"]
            recovered, metrics = VERIFY.read_logical_cartridge(first, logical_name, entry)
            assert recovered == records
            assert metrics == {
                "shards": len(entry["shards"]),
                "shard_receipts": entry["shards"],
                "records": len(records),
                "distinct_keys": len(records),
                "bytes": sum(row["bytes"] for row in entry["shards"]),
                "record_universe_sha256": VERIFY.record_digest(records),
            }


def one_cartridge(root: Path, records: list[dict]) -> tuple[str, dict]:
    logical_name = sorted(VERIFY.EXPECTED_CARTRIDGES)[0]
    return logical_name, VERIFY.write_logical_cartridge(root, logical_name, records)


def test_missing_and_tampered_shards_fail_closed() -> None:
    records = [record(1), record(2)]
    with tempfile.TemporaryDirectory(prefix="companies-2155-missing-") as temporary:
        root = Path(temporary)
        logical_name, entry = one_cartridge(root, records)
        (root / entry["shards"][0]["path"]).unlink()
        rejected(lambda: VERIFY.read_logical_cartridge(root, logical_name, entry), "missing")

    with tempfile.TemporaryDirectory(prefix="companies-2155-tampered-") as temporary:
        root = Path(temporary)
        logical_name, entry = one_cartridge(root, records)
        path = root / entry["shards"][0]["path"]
        content = path.read_bytes()
        assert b"FIXTURE" in content
        path.write_bytes(content.replace(b"FIXTURE", b"MIXTURE", 1))
        rejected(lambda: VERIFY.read_logical_cartridge(root, logical_name, entry), "physical receipt")


def test_reordered_and_noncontiguous_shards_fail_closed() -> None:
    records = [record(1), record(2), record(3)]
    with tempfile.TemporaryDirectory(prefix="companies-2155-reordered-") as temporary:
        root = Path(temporary)
        logical_name, entry = one_cartridge(root, records)
        receipt = entry["shards"][0]
        path = root / receipt["path"]
        payload = json.loads(path.read_text())
        assert len(payload["records"]) == 3
        payload["records"].reverse()
        path.write_text(VERIFY.canonical_json(payload) + "\n")
        refresh_physical_receipt(root, receipt)
        rejected(lambda: VERIFY.read_logical_cartridge(root, logical_name, entry), "strictly increasing")

    with tempfile.TemporaryDirectory(prefix="companies-2155-noncontiguous-") as temporary:
        root = Path(temporary)
        logical_name, entry = one_cartridge(root, records)
        entry["shards"][0]["ordinal"] = 1
        rejected(lambda: VERIFY.read_logical_cartridge(root, logical_name, entry), "contiguous")


def test_range_and_digest_receipts_fail_closed() -> None:
    records = [record(1), record(2)]
    with tempfile.TemporaryDirectory(prefix="companies-2155-range-") as temporary:
        root = Path(temporary)
        logical_name, entry = one_cartridge(root, records)
        entry["shards"][0]["first_company_number"] = "99999999"
        rejected(lambda: VERIFY.read_logical_cartridge(root, logical_name, entry), "range receipt")

    with tempfile.TemporaryDirectory(prefix="companies-2155-shard-digest-") as temporary:
        root = Path(temporary)
        logical_name, entry = one_cartridge(root, records)
        entry["shards"][0]["record_universe_sha256"] = "0" * 64
        rejected(lambda: VERIFY.read_logical_cartridge(root, logical_name, entry), "range receipt")

    with tempfile.TemporaryDirectory(prefix="companies-2155-union-digest-") as temporary:
        root = Path(temporary)
        logical_name, entry = one_cartridge(root, records)
        entry["record_universe_sha256"] = "0" * 64
        rejected(lambda: VERIFY.read_logical_cartridge(root, logical_name, entry), "ordered union")


def test_cross_cartridge_drift_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="companies-2155-cross-cartridge-") as temporary:
        root = Path(temporary)
        cartridges = {}
        logical_names = sorted(VERIFY.EXPECTED_CARTRIDGES)
        for ordinal, logical_name in enumerate(logical_names):
            fixture = record(1, company_name="DRIFTED FIXTURE LIMITED" if ordinal == 1 else None)
            cartridges[logical_name] = VERIFY.write_logical_cartridge(root, logical_name, [fixture])
        manifest = {"cartridges": cartridges, "companies": 1}
        rejected(lambda: VERIFY.canonical_company_records(root, manifest), "cross-cartridge record drift")


def expected_schema(columns: tuple[tuple[str, str, bool], ...]) -> list[dict]:
    return [{"name": name, "type": type_name, "nullable": nullable} for name, type_name, nullable in columns]


def expected_readback(columns: tuple[tuple[str, str, bool], ...]) -> list[dict]:
    return [{"name": name, "type": type_name} for name, type_name, _nullable in columns]


def test_small_fixture_preserves_duckdb_parquet_grains_and_schemas() -> None:
    records = [record(1), record(2)]
    with tempfile.TemporaryDirectory(prefix="companies-2155-parquet-") as temporary:
        root = Path(temporary)
        audit = VERIFY.build_analytical_datasets(root, records)
        assert audit["status"] == "PASS"
        assert audit["engine"] == {"name": "duckdb", "version": "1.3.2", "threads": 1}

        companies = audit["datasets"]["companies"]
        relationships = audit["datasets"]["company_repd_candidates"]
        assert companies["declared_key"] == ["company_number"]
        assert relationships["declared_key"] == ["company_number", "repd_ref", "match_type"]
        assert companies["rows"] == companies["distinct_keys"] == len(records)
        assert relationships["rows"] == relationships["distinct_keys"] == len(records)
        for dataset in (companies, relationships):
            assert dataset["status"] == "PASS"
            assert dataset["compression_codecs"] == ["ZSTD"]
            assert dataset["null_keys"] == 0
            assert dataset["duplicate_key_groups"] == 0
            assert dataset["required_column_null_rows"] == 0
            assert dataset["typed_column_mismatches"] == 0
        assert companies["schema_contract"] == expected_schema(VERIFY.COMPANY_COLUMNS)
        assert companies["schema_readback"] == expected_readback(VERIFY.COMPANY_COLUMNS)
        assert relationships["schema_contract"] == expected_schema(VERIFY.RELATIONSHIP_COLUMNS)
        assert relationships["schema_readback"] == expected_readback(VERIFY.RELATIONSHIP_COLUMNS)
        assert companies["grain"] == "one row per distinct company in the candidate cartridge union"
        assert relationships["grain"] == "one evidence-qualified REPD candidate relationship"
        assert relationships["identity_posture"] == "CANDIDATE_RELATIONSHIP_ONLY_NOT_PRIMARY_PROJECT_BINDING"
        assert (root / VERIFY.COMPANY_PARQUET).is_file()
        assert (root / VERIFY.RELATIONSHIP_PARQUET).is_file()


def successor_seal_fixture(root: Path):
    """Translate the mature one-row fixture onto the exact 2155 source contract."""
    plan_path, evidence, repd, raw, basic, accounts, _old_rest, basic_report = (
        BASE_FIXTURE.write_verifier_fixture(root)
    )
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
    raw_manifest_path = raw / "manifest-v1.json"
    raw_manifest = json.loads(raw_manifest_path.read_text())
    for name, receipt in raw_manifest["files"].items():
        cartridge_path = raw / receipt["path"]
        payload = json.loads(cartridge_path.read_text())
        payload["snapshot_id"] = VERIFY.GENERATION
        payload["generated_at"] = VERIFY.FIXED_GENERATED_AT
        cartridge_path.write_text(VERIFY.canonical_json(payload) + "\n")
        receipt["records"] = len(payload["records"])
        receipt["sha256"] = hashlib.sha256(cartridge_path.read_bytes()).hexdigest()
    raw_manifest.update(
        {
            "snapshot_id": VERIFY.GENERATION,
            "refresh_policy": "annual-overwrite",
            "threshold_gbp": 10_000_000,
            "privacy": {
                "directors": False,
                "individual_psc": False,
                "residential_addresses": False,
            },
        }
    )
    raw_manifest_path.write_text(VERIFY.canonical_json(raw_manifest) + "\n")
    return plan_path, evidence, repd, raw, basic, accounts, rest, basic_report


def test_exact_boundary_and_single_record_overflow() -> None:
    fixture = record(1, padding=2_000)
    logical_name = sorted(VERIFY.EXPECTED_CARTRIDGES)[0]
    # The declared target is itself in the canonical envelope. Anchor it to a
    # same-width value before measuring the exact boundary.
    with shard_target_for_test(9_999):
        exact = len(VERIFY.render_shard(logical_name, 0, [fixture]))
        with shard_target_for_test(exact):
            groups, _digest = VERIFY.partition_records(logical_name, [fixture])
            assert len(groups) == 1 and groups[0][2] == exact
        with shard_target_for_test(exact - 1):
            rejected(
                lambda: VERIFY.partition_records(logical_name, [fixture]),
                "one record exceeds",
            )


def test_full_direct_seal_verify_and_structured_resource_failures() -> None:
    """Exercise the complete direct path, not merely shard helper functions."""
    with tempfile.TemporaryDirectory(prefix="companies-2155-full-seal-") as temporary:
        root = Path(temporary)
        plan_path, evidence, repd, raw, basic, accounts, rest, basic_report = (
            successor_seal_fixture(root)
        )
        original_plan_sha = VERIFY.EXPECTED_PLAN_SHA256
        original_rest_sha = VERIFY.EXPECTED_REST_EVIDENCE_SHA256
        original_repd_paths = VERIFY.EXPECTED_REPD_PATHS
        original_repd_sha = VERIFY.EXPECTED_REPD_CLOSURE_SHA256
        original_repd_bytes = VERIFY.EXPECTED_REPD_TOTAL_BYTES
        original_repd_projects = VERIFY.EXPECTED_REPD_PROJECTS
        VERIFY.EXPECTED_PLAN_SHA256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        VERIFY.EXPECTED_REST_EVIDENCE_SHA256 = hashlib.sha256(rest.read_bytes()).hexdigest()
        _projects, repd_manifest = VERIFY.LEGACY.repd_closure(repd)
        VERIFY.EXPECTED_REPD_PATHS = [row["path"] for row in repd_manifest["files"]]
        VERIFY.EXPECTED_REPD_CLOSURE_SHA256 = repd_manifest["sha256"]
        VERIFY.EXPECTED_REPD_TOTAL_BYTES = sum(row["bytes"] for row in repd_manifest["files"])
        VERIFY.EXPECTED_REPD_PROJECTS = repd_manifest["projects"]
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
                result = VERIFY.verify(output)
                assert result["status"] == "PASS", result
            assert tree_bytes(first) == tree_bytes(second)
            manifest = json.loads((first / "manifest-v2.json").read_text())
            assert manifest["schema"] == VERIFY.MANIFEST_SCHEMA
            assert manifest["usage_context"] == "NON_COMMERCIAL_OPEN_SOURCE"
            assert manifest["source_rights_are_distinct_from_usage_context"] is True
            assert manifest["deployment_state"] == "not-authorised"
            assert manifest["publication"]["promotion_eligible"] is False
            assert manifest["analytical_dataset"]["rows"] == 1
            assert manifest["relationship_dataset"]["rows"] == 1
            assert set(manifest["cartridges"]) == VERIFY.EXPECTED_CARTRIDGES

            rights = root / "rights-tamper"
            shutil.copytree(first, rights)
            rights_manifest = json.loads((rights / "manifest-v2.json").read_text())
            logical_name = sorted(VERIFY.EXPECTED_CARTRIDGES)[0]
            receipt = rights_manifest["cartridges"][logical_name]["shards"][0]
            shard_path = rights / receipt["path"]
            payload = json.loads(shard_path.read_text())
            payload["usage_context"] = "COMMERCIAL"
            shard_path.write_text(VERIFY.canonical_json(payload) + "\n")
            receipt["bytes"] = shard_path.stat().st_size
            receipt["sha256"] = hashlib.sha256(shard_path.read_bytes()).hexdigest()
            (rights / "manifest-v2.json").write_text(
                json.dumps(rights_manifest, indent=2, sort_keys=True) + "\n"
            )
            rights_result = VERIFY.verify(rights)
            assert rights_result["status"] == "FAIL"
            assert any("rights" in error.lower() or "payload" in error.lower() for error in rights_result["errors"])

            original_total = VERIFY.MAXIMUM_TOTAL_BYTES
            VERIFY.MAXIMUM_TOTAL_BYTES = 1
            try:
                total_result = VERIFY.verify(first)
            finally:
                VERIFY.MAXIMUM_TOTAL_BYTES = original_total
            assert total_result["status"] == "FAIL"
            assert any("candidate total byte ceiling" in error for error in total_result["errors"])

            original_file = VERIFY.MAXIMUM_FILE_BYTES
            VERIFY.MAXIMUM_FILE_BYTES = 1
            try:
                file_result = VERIFY.verify(first)
            finally:
                VERIFY.MAXIMUM_FILE_BYTES = original_file
            assert file_result["status"] == "FAIL"
            assert any("published file byte ceiling" in error for error in file_result["errors"])
        finally:
            VERIFY.EXPECTED_PLAN_SHA256 = original_plan_sha
            VERIFY.EXPECTED_REST_EVIDENCE_SHA256 = original_rest_sha
            VERIFY.EXPECTED_REPD_PATHS = original_repd_paths
            VERIFY.EXPECTED_REPD_CLOSURE_SHA256 = original_repd_sha
            VERIFY.EXPECTED_REPD_TOTAL_BYTES = original_repd_bytes
            VERIFY.EXPECTED_REPD_PROJECTS = original_repd_projects


def main() -> None:
    test_generation_and_partition_contract()
    test_forced_multishard_exact_bytes_and_deterministic_tree()
    test_missing_and_tampered_shards_fail_closed()
    test_reordered_and_noncontiguous_shards_fail_closed()
    test_range_and_digest_receipts_fail_closed()
    test_cross_cartridge_drift_fails_closed()
    test_small_fixture_preserves_duckdb_parquet_grains_and_schemas()
    test_exact_boundary_and_single_record_overflow()
    test_full_direct_seal_verify_and_structured_resource_failures()
    print(
        json.dumps(
            {
                "status": "PASS",
                "generation": VERIFY.GENERATION,
                "partition_scheme": VERIFY.PARTITION_SCHEME,
                "forced_multishard": True,
                "company_key": ["company_number"],
                "relationship_key": ["company_number", "repd_ref", "match_type"],
                "duckdb": VERIFY.DUCKDB_VERSION,
                "network_requests": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
