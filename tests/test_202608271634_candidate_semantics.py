#!/usr/bin/env python3
"""Deterministic contract for the 202608271634 semantics overlay."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


NORMALISE = load(
    "companies_candidate_semantics_202608271634",
    "build/python/202608271634-normalise-companies-candidate.py",
)
LEGACY_FIXTURES = load(
    "companies_legacy_fixtures_for_202608271634",
    "tests/test_202608271507_bounded_companies_house.py",
)


def rejected(callable_, contains: str) -> None:
    try:
        callable_()
    except RuntimeError as exc:
        assert contains.lower() in str(exc).lower(), (contains, str(exc))
        return
    raise AssertionError(f"Expected RuntimeError containing {contains!r}")


def test_source_manifest() -> None:
    path = ROOT / "manifests/202608271634-companies-candidate-semantics.json"
    manifest = json.loads(path.read_text())
    assert manifest["generation"] == "202608271634"
    assert manifest["base_commit"] == "4012964c3ab1e2f559e4836d697b99a74c7291e2"
    assert manifest["deployment_state"] == "not-authorised"
    assert manifest["usage_context"] == "NON_COMMERCIAL_OPEN_SOURCE"
    assert manifest["source_licence"] == "Open Government Licence v3.0"
    assert manifest["source_attribution"] == NORMALISE.SOURCE_ATTRIBUTION
    assert manifest["publication"]["required_source_branch"] == "main"
    assert len(manifest["source_files"]) == 4
    for receipt in [*manifest["source_files"], *manifest["dependencies"]]:
        source = ROOT / receipt["path"]
        assert source.is_file(), receipt
        if receipt["sha256"] != "SELF":
            assert hashlib.sha256(source.read_bytes()).hexdigest() == receipt["sha256"], receipt


def upgrade_fixture_to_1547(root: Path):
    values = LEGACY_FIXTURES.write_verifier_fixture(root)
    plan_path, evidence, repd, raw, basic, accounts, rest_evidence, basic_report = values
    plan = json.loads(plan_path.read_text())
    plan["generation"] = "202608271547"
    plan["base_commit"] = "625101ef325f3d67fc866e3822bd76f1fcbb2e49"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    for path in sorted(evidence.glob("receipt-*.json")):
        payload = json.loads(path.read_text())
        payload["generation"] = "202608271547"
        payload["base_commit"] = "625101ef325f3d67fc866e3822bd76f1fcbb2e49"
        payload["plan_sha256"] = plan_sha
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    for path in sorted(evidence.glob("extraction-*.json")):
        payload = json.loads(path.read_text())
        payload["generation"] = "202608271547"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    rest = json.loads(rest_evidence.read_text())
    rest["generation"] = "202608271547"
    rest_evidence.write_text(json.dumps(rest, indent=2, sort_keys=True) + "\n")
    report = json.loads(basic_report.read_text())
    report["generation"] = "202608271547"
    basic_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return plan_path, evidence, repd, raw, basic, accounts, rest_evidence, basic_report


def build_parent_candidate(root: Path) -> Path:
    inputs = upgrade_fixture_to_1547(root)
    parent = root / "parent-candidate"
    NORMALISE.PARENT_VERIFY.seal(
        inputs[3],
        parent,
        inputs[0],
        inputs[1],
        inputs[1],
        inputs[2],
        inputs[4],
        inputs[5],
        inputs[6],
        inputs[7],
        NORMALISE.BASE_COMMIT,
    )
    assert NORMALISE.PARENT_VERIFY.verify(parent)["status"] == "PASS"
    return parent


def rewrite_parquet(root: Path, select_sql: str, compression: str) -> None:
    duckdb = NORMALISE.load_duckdb()
    source = root / NORMALISE.PARENT_VERIFY.PARQUET_PATH
    target = root / "replacement.parquet"
    connection = duckdb.connect(":memory:")
    try:
        escaped_source = NORMALISE.sql_path(source)
        escaped_target = NORMALISE.sql_path(target)
        connection.execute(
            f"COPY ({select_sql.replace('{source}', escaped_source)}) TO '{escaped_target}' "
            f"(FORMAT PARQUET, COMPRESSION {compression}, ROW_GROUP_SIZE 122880)"
        )
    finally:
        connection.close()
    source.unlink()
    target.rename(source)
    manifest_path = root / "manifest-v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["analytical_dataset"]["file"]["bytes"] = source.stat().st_size
    manifest["analytical_dataset"]["file"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def test_overlay(root: Path) -> None:
    parent = build_parent_candidate(root)
    source_manifest = ROOT / "manifests/202608271547-bounded-companies-house-candidate.json"
    first = root / "overlay-a"
    second = root / "overlay-b"
    parent_commit = "b" * 40
    NORMALISE.normalise(parent, first, parent_commit, NORMALISE.BASE_COMMIT, source_manifest)
    NORMALISE.normalise(parent, second, parent_commit, NORMALISE.BASE_COMMIT, source_manifest)
    first_files = {path.relative_to(first).as_posix(): path.read_bytes() for path in first.rglob("*") if path.is_file()}
    second_files = {path.relative_to(second).as_posix(): path.read_bytes() for path in second.rglob("*") if path.is_file()}
    assert first_files == second_files
    result = NORMALISE.verify_overlay(first, parent, NORMALISE.BASE_COMMIT, source_manifest, parent_commit)
    assert result["status"] == "PASS", result
    manifest = json.loads((first / "manifest-v1.json").read_text())
    proof = json.loads((first / "verification-v1.json").read_text())
    assert manifest["usage_context"] == "NON_COMMERCIAL_OPEN_SOURCE"
    assert manifest["source_licence"] == "Open Government Licence v3.0"
    assert manifest["source_attribution"] == NORMALISE.SOURCE_ATTRIBUTION
    assert "licensing_posture" not in manifest["data_discipline"]
    assert proof["data_law"]["compression_codecs"] == ["ZSTD"]
    assert proof["data_law"]["rows"] == proof["data_law"]["distinct_keys"] == 1
    assert proof["data_law"]["null_keys"] == proof["data_law"]["duplicate_key_groups"] == 0
    assert proof["data_law"]["typed_column_mismatches"] == 0
    assert "total_assets" in proof["data_law"]["typed_columns_verified"]
    assert proof["data_law"]["json_record_universe_sha256"] == proof["data_law"]["parquet_record_universe_sha256"]
    assert proof["script_network_requests"] == 0
    assert proof["successor_foreign_repository_access"] is False
    assert proof["zip_guards"]["maximum_expanded_bytes_per_archive"] == 60_000_000_000
    assert proof["zip_guards"]["maximum_compression_ratio"] == 250
    assert manifest["publication"]["stable_path_must_change"] is False

    uncompressed = root / "uncompressed-parent"
    shutil.copytree(parent, uncompressed)
    rewrite_parquet(uncompressed, "SELECT * FROM read_parquet('{source}')", "UNCOMPRESSED")
    uncompressed_manifest = json.loads((uncompressed / "manifest-v1.json").read_text())
    rejected(
        lambda: NORMALISE.independent_data_law(uncompressed, uncompressed_manifest),
        "compression metadata",
    )

    divergent = root / "divergent-parent"
    shutil.copytree(parent, divergent)
    rewrite_parquet(
        divergent,
        "SELECT * REPLACE ('{}' AS record_json) FROM read_parquet('{source}')",
        "ZSTD",
    )
    divergent_manifest = json.loads((divergent / "manifest-v1.json").read_text())
    rejected(
        lambda: NORMALISE.independent_data_law(divergent, divergent_manifest),
        "semantic universes differ",
    )

    typed_divergent = root / "typed-divergent-parent"
    shutil.copytree(parent, typed_divergent)
    rewrite_parquet(
        typed_divergent,
        "SELECT * REPLACE (total_assets + 1 AS total_assets) FROM read_parquet('{source}')",
        "ZSTD",
    )
    typed_divergent_manifest = json.loads((typed_divergent / "manifest-v1.json").read_text())
    rejected(
        lambda: NORMALISE.independent_data_law(typed_divergent, typed_divergent_manifest),
        "typed parquet columns differ",
    )


def main() -> None:
    test_source_manifest()
    with tempfile.TemporaryDirectory() as temporary:
        test_overlay(Path(temporary))
    print(
        json.dumps(
            {
                "status": "PASS",
                "generation": "202608271634",
                "usage_context": "NON_COMMERCIAL_OPEN_SOURCE",
                "source_licence": "Open Government Licence v3.0",
                "parquet_codec_readback": "PASS",
                "json_parquet_semantic_closure": "PASS",
                "fixture_network_requests": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
