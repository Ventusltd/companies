#!/usr/bin/env python3
"""Create a quarantined semantics overlay for the immutable 1547 candidate."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

GENERATION = "202608271634"
BASE_COMMIT = "4012964c3ab1e2f559e4836d697b99a74c7291e2"
PARENT_GENERATION = "202608271547"
FIXED_GENERATED_AT = "2026-08-27T15:34:00Z"
USAGE_CONTEXT = "NON_COMMERCIAL_OPEN_SOURCE"
SOURCE_LICENCE = "Open Government Licence v3.0"
SOURCE_LICENCE_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
SOURCE_ATTRIBUTION = (
    "Contains public sector information licensed under the Open Government Licence v3.0. "
    "Source: Companies House."
)
PARENT_SOURCE_MANIFEST_SHA256 = "a03dbdd740213a0d6751c2bb74a3bea3f895e29a4c81345eb085b4c42b39b111"
DUCKDB_VERSION = "1.3.2"
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SCRIPT_ROOT = Path(__file__).resolve().parents[2]
PARENT_VERIFIER = SCRIPT_ROOT / "build/python/202608271547-verify-companies-house-candidate.py"

spec = importlib.util.spec_from_file_location("companies_verify_202608271547_for_1634", PARENT_VERIFIER)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608271547 verifier")
PARENT_VERIFY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT_VERIFY)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise RuntimeError(f"duckdb=={DUCKDB_VERSION} is required") from exc
    if duckdb.__version__ != DUCKDB_VERSION:
        raise RuntimeError(f"DuckDB version drift: expected {DUCKDB_VERSION}, received {duckdb.__version__}")
    return duckdb


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def universe_digest(pairs: list[tuple[str, str]]) -> str:
    value = hashlib.sha256()
    for company_number, record_json in pairs:
        value.update(company_number.encode("utf-8"))
        value.update(b"\0")
        value.update(record_json.encode("utf-8"))
        value.update(b"\n")
    return value.hexdigest()


def load_parent_source_manifest(path: Path) -> tuple[dict, dict]:
    if digest(path) != PARENT_SOURCE_MANIFEST_SHA256:
        raise RuntimeError("The 202608271547 source manifest drifted")
    source = json.loads(path.read_text())
    if (
        source.get("generation") != PARENT_GENERATION
        or source.get("deployment_state") != "not-authorised"
        or source.get("limits", {}).get("maximum_document_bytes") != 128_000_000
        or source.get("limits", {}).get("maximum_other_member_bytes") != 32_000_000
        or source.get("limits", {}).get("maximum_expanded_bytes_per_archive") != 60_000_000_000
        or source.get("limits", {}).get("maximum_compression_ratio") != 250
        or source.get("limits", {}).get("maximum_members_per_archive") != 2_000_000
        or source.get("limits", {}).get("maximum_nested_zip_bytes") != 100_000_000
        or source.get("limits", {}).get("maximum_zip_nesting") != 1
    ):
        raise RuntimeError("The inherited ZIP guard contract drifted")
    extractor = next(
        (row for row in source.get("source_files", []) if row.get("path") == "build/python/202608271547-extract-bounded-accounts.py"),
        None,
    )
    if not extractor or extractor.get("sha256") != "add4395ae057e81bf13f39fe7a01afe92d91ff75ea1884e240a745fe2dc271af":
        raise RuntimeError("The inherited bounded extractor receipt drifted")
    return source, {
        "maximum_document_bytes": 128_000_000,
        "maximum_other_member_bytes": 32_000_000,
        "maximum_expanded_bytes_per_archive": 60_000_000_000,
        "maximum_compression_ratio": 250,
        "maximum_members_per_archive": 2_000_000,
        "maximum_nested_zip_bytes": 100_000_000,
        "maximum_zip_nesting": 1,
        "extractor_sha256": extractor["sha256"],
        "source_manifest_sha256": PARENT_SOURCE_MANIFEST_SHA256,
    }


def require_parent_candidate(root: Path, expected_source_commit: str) -> dict:
    legacy = PARENT_VERIFY.verify(root)
    if legacy.get("status") != "PASS":
        raise RuntimeError(f"The inherited candidate verifier failed: {legacy.get('errors', [])!r}")
    manifest = json.loads((root / "manifest-v1.json").read_text())
    ogl = manifest.get("licence", {})
    if (
        manifest.get("generation") != PARENT_GENERATION
        or manifest.get("deployment_state") != "not-authorised"
        or manifest.get("promotion_eligible") is not False
        or manifest.get("inputs", {}).get("generation_source_commit") != expected_source_commit
        or ogl.get("name") != SOURCE_LICENCE
        or ogl.get("url") != SOURCE_LICENCE_URL
        or ogl.get("attribution") != SOURCE_ATTRIBUTION
    ):
        raise RuntimeError("The inherited candidate provenance or OGL contract drifted")
    return manifest


def independent_data_law(root: Path, manifest: dict) -> dict:
    """Re-prove the declared company grain directly from JSON and Parquet."""
    duckdb = load_duckdb()
    parquet_receipt = manifest.get("analytical_dataset", {}).get("file", {})
    parquet_path = root / str(parquet_receipt.get("path", "__missing__"))
    if (
        not parquet_path.is_file()
        or parquet_path.stat().st_size != parquet_receipt.get("bytes")
        or digest(parquet_path) != parquet_receipt.get("sha256")
    ):
        raise RuntimeError("The inherited Parquet file receipt failed")
    records = PARENT_VERIFY.cartridge_union(root, manifest)
    json_pairs = [(str(record["company_number"]), canonical_json(record)) for record in records]
    expected_typed_rows = [PARENT_VERIFY.analytical_row(record) for record in records]
    json_universe = universe_digest(json_pairs)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        escaped = sql_path(parquet_path)
        typed_columns = PARENT_VERIFY.PARQUET_COLUMNS
        fields = ",".join(f'"{name}" {type_name}' for name, type_name, _nullable in typed_columns)
        connection.execute(f"CREATE TABLE expected_companies ({fields}, PRIMARY KEY(company_number))")
        placeholders = ",".join("?" for _ in typed_columns)
        connection.executemany(f"INSERT INTO expected_companies VALUES ({placeholders})", expected_typed_rows)
        codecs = sorted(
            str(row[0]).upper()
            for row in connection.execute(
                f"SELECT DISTINCT compression FROM parquet_metadata('{escaped}')"
            ).fetchall()
        )
        row = connection.execute(
            f"""
            SELECT
              count(*)::BIGINT,
              count(DISTINCT company_number)::BIGINT,
              count(*) FILTER (WHERE company_number IS NULL OR company_number = '')::BIGINT
            FROM read_parquet('{escaped}')
            """
        ).fetchone()
        rows, distinct_keys, null_keys = map(int, row)
        duplicate_key_groups = int(
            connection.execute(
                f"SELECT count(*) FROM (SELECT company_number FROM read_parquet('{escaped}') GROUP BY company_number HAVING count(*) > 1)"
            ).fetchone()[0]
        )
        parquet_pairs = [
            (str(number), str(record_json))
            for number, record_json in connection.execute(
                f"SELECT company_number, record_json FROM read_parquet('{escaped}') ORDER BY company_number"
            ).fetchall()
        ]
        typed_differences = " OR ".join(
            f'p."{name}" IS DISTINCT FROM e."{name}"' for name, _type, _nullable in typed_columns
        )
        mismatched_typed_rows = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM read_parquet('{escaped}') p
                FULL OUTER JOIN expected_companies e
                  ON p.company_number = e.company_number
                WHERE p.company_number IS NULL
                   OR e.company_number IS NULL
                   OR {typed_differences}
                """
            ).fetchone()[0]
        )
    finally:
        connection.close()
    parquet_universe = universe_digest(parquet_pairs)
    if codecs != ["ZSTD"]:
        raise RuntimeError(f"Parquet compression metadata is not exactly ZSTD: {codecs!r}")
    if rows < 1 or rows != distinct_keys or null_keys != 0 or duplicate_key_groups != 0:
        raise RuntimeError("Parquet declared-key law failed")
    if rows != len(records) or json_universe != parquet_universe:
        raise RuntimeError("JSON and Parquet semantic universes differ")
    if mismatched_typed_rows != 0:
        raise RuntimeError("Typed Parquet columns differ from the canonical JSON projection")
    declared = manifest.get("analytical_dataset", {})
    if (
        declared.get("rows") != rows
        or declared.get("distinct_keys") != distinct_keys
        or declared.get("null_keys") != null_keys
        or declared.get("duplicate_key_groups") != duplicate_key_groups
        or declared.get("record_universe_sha256") != parquet_universe
        or declared.get("declared_key") != ["company_number"]
    ):
        raise RuntimeError("The inherited analytical manifest differs from direct readback")
    return {
        "status": "PASS",
        "format": "parquet",
        "compression_codecs": codecs,
        "grain": "one row per distinct company in the candidate cartridge union",
        "declared_key": ["company_number"],
        "rows": rows,
        "distinct_keys": distinct_keys,
        "null_keys": null_keys,
        "duplicate_key_groups": duplicate_key_groups,
        "typed_column_mismatches": mismatched_typed_rows,
        "typed_columns_verified": [name for name, _type, _nullable in PARENT_VERIFY.PARQUET_COLUMNS],
        "json_record_universe_sha256": json_universe,
        "parquet_record_universe_sha256": parquet_universe,
        "parquet": {
            "path": parquet_receipt["path"],
            "bytes": parquet_path.stat().st_size,
            "sha256": digest(parquet_path),
        },
        "engine": {"name": "duckdb", "version": DUCKDB_VERSION, "threads": 1},
    }


def candidate_proof(
    parent_root: Path,
    parent_commit: str,
    parent_source_commit: str,
    source_manifest_path: Path,
) -> dict:
    if not COMMIT_SHA.fullmatch(parent_commit) or not COMMIT_SHA.fullmatch(parent_source_commit):
        raise RuntimeError("Parent commits must be exact SHAs")
    parent_manifest = require_parent_candidate(parent_root, parent_source_commit)
    _source_manifest, zip_guards = load_parent_source_manifest(source_manifest_path)
    data_law = independent_data_law(parent_root, parent_manifest)
    return {
        "schema": "companies-house-candidate-semantics-proof-v1",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "usage_context": USAGE_CONTEXT,
        "source_licence": SOURCE_LICENCE,
        "source_licence_url": SOURCE_LICENCE_URL,
        "source_attribution": SOURCE_ATTRIBUTION,
        "parent_candidate": {
            "generation": PARENT_GENERATION,
            "branch": f"candidate/{PARENT_GENERATION}",
            "commit": parent_commit,
            "source_commit": parent_source_commit,
            "path": f"data/candidates/{PARENT_GENERATION}/",
            "manifest_bytes": (parent_root / "manifest-v1.json").stat().st_size,
            "manifest_sha256": digest(parent_root / "manifest-v1.json"),
        },
        "data_law": data_law,
        "zip_guards": zip_guards,
        "script_network_requests": 0,
        "successor_foreign_repository_access": False,
    }


def normalise(
    parent_root: Path,
    output: Path,
    parent_commit: str,
    parent_source_commit: str,
    source_manifest_path: Path,
) -> dict:
    if output.exists():
        raise RuntimeError("The timestamped overlay output already exists")
    proof = candidate_proof(parent_root, parent_commit, parent_source_commit, source_manifest_path)
    output.mkdir(parents=True)
    proof_path = output / "verification-v1.json"
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    manifest = {
        "schema": "companies-house-candidate-semantics-overlay-v1",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "promotion_eligible": False,
        "usage_context": USAGE_CONTEXT,
        "source_licence": SOURCE_LICENCE,
        "source_licence_url": SOURCE_LICENCE_URL,
        "source_attribution": SOURCE_ATTRIBUTION,
        "coverage": "SEMANTIC_NORMALISATION_OF_IMMUTABLE_PARENT_CANDIDATE",
        "parent_candidate": proof["parent_candidate"],
        "data_discipline": {
            "owning_repository": "Ventusltd/companies",
            "format": "parquet",
            "compression": "zstd",
            "grain": proof["data_law"]["grain"],
            "declared_key": ["company_number"],
            "actual_compression_metadata_verified": True,
            "json_parquet_semantic_closure_verified": True,
            "rows_equal_distinct_non_null_keys": True,
            "foreign_data_copied": False,
        },
        "zip_guards": proof["zip_guards"],
        "files": [
            {
                "path": "verification-v1.json",
                "bytes": proof_path.stat().st_size,
                "sha256": digest(proof_path),
            }
        ],
        "publication": {
            "candidate_path": f"data/candidates/{GENERATION}/",
            "candidate_branch": f"candidate/{GENERATION}",
            "stable_path": "data/current/",
            "stable_path_must_change": False,
            "pages_must_change": False,
        },
    }
    manifest_path = output / "manifest-v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result = verify_overlay(output, parent_root, parent_source_commit, source_manifest_path, parent_commit)
    if result["status"] != "PASS":
        raise RuntimeError(f"The semantics overlay failed verification: {result['errors']!r}")
    return manifest


def verify_overlay(
    overlay_root: Path,
    parent_root: Path,
    parent_source_commit: str,
    source_manifest_path: Path,
    expected_parent_commit: str | None = None,
) -> dict:
    errors: list[str] = []
    try:
        manifest_path = overlay_root / "manifest-v1.json"
        proof_path = overlay_root / "verification-v1.json"
        manifest = json.loads(manifest_path.read_text())
        proof = json.loads(proof_path.read_text())
        parent_commit = str(manifest.get("parent_candidate", {}).get("commit", ""))
        if expected_parent_commit is not None and parent_commit != expected_parent_commit:
            errors.append("parent candidate commit")
        expected_proof = candidate_proof(parent_root, parent_commit, parent_source_commit, source_manifest_path)
        if proof != expected_proof:
            errors.append("proof semantics")
        if manifest.get("schema") != "companies-house-candidate-semantics-overlay-v1":
            errors.append("overlay schema")
        if manifest.get("generation") != GENERATION or manifest.get("generated_at") != FIXED_GENERATED_AT:
            errors.append("generation")
        if manifest.get("deployment_state") != "not-authorised" or manifest.get("promotion_eligible") is not False:
            errors.append("quarantine")
        if (
            manifest.get("usage_context") != USAGE_CONTEXT
            or manifest.get("source_licence") != SOURCE_LICENCE
            or manifest.get("source_licence_url") != SOURCE_LICENCE_URL
            or manifest.get("source_attribution") != SOURCE_ATTRIBUTION
        ):
            errors.append("usage/source licence separation")
        discipline = manifest.get("data_discipline", {})
        if "licensing_posture" in discipline or discipline.get("owning_repository") != "Ventusltd/companies":
            errors.append("data discipline semantics")
        if discipline.get("actual_compression_metadata_verified") is not True:
            errors.append("compression metadata proof")
        if discipline.get("json_parquet_semantic_closure_verified") is not True:
            errors.append("JSON/Parquet proof")
        if discipline.get("rows_equal_distinct_non_null_keys") is not True:
            errors.append("declared-key proof")
        expected_receipt = {
            "path": "verification-v1.json",
            "bytes": proof_path.stat().st_size,
            "sha256": digest(proof_path),
        }
        if manifest.get("files") != [expected_receipt]:
            errors.append("proof receipt")
        actual_paths = {path.relative_to(overlay_root).as_posix() for path in overlay_root.rglob("*") if path.is_file()}
        if actual_paths != {"manifest-v1.json", "verification-v1.json"}:
            errors.append("overlay file closure")
        publication = manifest.get("publication", {})
        if publication.get("stable_path_must_change") is not False or publication.get("pages_must_change") is not False:
            errors.append("stable publication boundary")
    except Exception as exc:
        errors.append(str(exc))
    return {
        "schema": "companies-house-candidate-semantics-overlay-verification-v1",
        "generation": GENERATION,
        "status": "FAIL" if errors else "PASS",
        "errors": errors[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--normalise", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--parent", required=True, type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--parent-commit", required=True)
    parser.add_argument("--parent-source-commit", default=BASE_COMMIT)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.normalise:
            if args.output is None:
                raise RuntimeError("Normalise mode requires --output")
            manifest = normalise(
                args.parent,
                args.output,
                args.parent_commit,
                args.parent_source_commit,
                args.source_manifest,
            )
            result = {"schema": manifest["schema"], "generation": GENERATION, "status": "PASS"}
        else:
            if args.input is None:
                raise RuntimeError("Verify mode requires --input")
            result = verify_overlay(
                args.input,
                args.parent,
                args.parent_source_commit,
                args.source_manifest,
                args.parent_commit,
            )
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered)
        print(rendered, end="")
        return 0 if result.get("status") == "PASS" else 1
    except Exception as exc:
        failure = {
            "schema": "companies-house-candidate-semantics-overlay-verification-v1",
            "generation": GENERATION,
            "status": "FAIL",
            "errors": [str(exc)],
        }
        rendered = json.dumps(failure, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered)
        print(rendered, end="", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
