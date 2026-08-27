#!/usr/bin/env python3
"""Seal and verify the 202608271547 JSON + Parquet candidate closure."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

GENERATION = "202608271547"
BASE_COMMIT = "625101ef325f3d67fc866e3822bd76f1fcbb2e49"
FIXED_GENERATED_AT = "2026-08-27T14:47:00Z"
DUCKDB_VERSION = "1.3.2"
PARQUET_PATH = "companies-v1.parquet"
AUDIT_PATH = "parquet-audit-v1.json"
PARQUET_GRAIN = "one row per distinct company in the candidate cartridge union"
PARQUET_KEY = ("company_number",)
REFERENCE_REPOSITORY = "Ventusltd/data-gb-electricity"
REFERENCE_COMMIT = "7c492745c974f6b8610cb1209f996b1553abb498"
PARENT = Path(__file__).with_name("202608271507-verify-companies-house-candidate.py")

# The record_json column preserves the exact sealed public record. Selected typed
# columns make the candidate directly useful in DuckDB without weakening that
# lossless projection. Money uses DECIMAL, never an inferred floating type.
PARQUET_COLUMNS = (
    ("generation", "VARCHAR", False),
    ("company_number", "VARCHAR", False),
    ("company_name", "VARCHAR", False),
    ("company_status", "VARCHAR", True),
    ("classification", "VARCHAR", False),
    ("accounts_date", "DATE", True),
    ("total_assets", "DECIMAL(38,2)", True),
    ("net_assets", "DECIMAL(38,2)", True),
    ("turnover", "DECIMAL(38,2)", True),
    ("cash", "DECIMAL(38,2)", True),
    ("assets_gte_10m", "BOOLEAN", False),
    ("energy_relevant_large_company", "BOOLEAN", False),
    ("probable_project_spv", "BOOLEAN", False),
    ("financial_currency", "VARCHAR", False),
    ("sic_codes_json", "VARCHAR", False),
    ("btm_tags_json", "VARCHAR", False),
    ("repd_name_candidates_json", "VARCHAR", False),
    ("record_json", "VARCHAR", False),
)

spec = importlib.util.spec_from_file_location("companies_verify_202608271507", PARENT)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608271507 verifier")
PREVIOUS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREVIOUS)
PREVIOUS.GENERATION = GENERATION
PREVIOUS.BASE_COMMIT = BASE_COMMIT
PREVIOUS.FIXED_GENERATED_AT = FIXED_GENERATED_AT
ORIGINAL_SEAL = PREVIOUS.seal
ORIGINAL_VERIFY = PREVIOUS.verify


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def money(value, label: str) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RuntimeError(f"{label} is not a monetary number")
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"{label} is not a bounded decimal") from exc
    if not result.is_finite() or len(result.as_tuple().digits) > 38:
        raise RuntimeError(f"{label} is outside DECIMAL(38,2)")
    return result


def public_boolean(record: dict, key: str, number: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"{number}.{key} is not boolean")
    return value


def analytical_row(record: dict) -> tuple:
    number = str(record.get("company_number", ""))
    if not PREVIOUS.COMPANY_NUMBER.fullmatch(number):
        raise RuntimeError("Parquet projection received an invalid company number")
    name = record.get("company_name")
    classification = record.get("classification")
    currency = record.get("financial_currency")
    if not isinstance(name, str) or not name or classification not in PREVIOUS.CLASSIFICATIONS or currency != "GBP":
        raise RuntimeError(f"Parquet projection contract failed for company {number}")
    for key in ("sic_codes", "btm_tags", "repd_name_candidates"):
        if not isinstance(record.get(key), list):
            raise RuntimeError(f"{number}.{key} is not a list")
    return (
        GENERATION,
        number,
        name,
        record.get("company_status") or None,
        classification,
        record.get("accounts_date") or None,
        money(record.get("total_assets"), f"{number}.total_assets"),
        money(record.get("net_assets"), f"{number}.net_assets"),
        money(record.get("turnover"), f"{number}.turnover"),
        money(record.get("cash"), f"{number}.cash"),
        public_boolean(record, "assets_gte_10m", number),
        public_boolean(record, "energy_relevant_large_company", number),
        public_boolean(record, "probable_project_spv", number),
        currency,
        canonical_json(record.get("sic_codes", [])),
        canonical_json(record.get("btm_tags", [])),
        canonical_json(record.get("repd_name_candidates", [])),
        canonical_json(record),
    )


def cartridge_union(root: Path, manifest: dict) -> list[dict]:
    canonical: dict[str, str] = {}
    records_by_number: dict[str, dict] = {}
    for name in sorted(PREVIOUS.EXPECTED_CARTRIDGES):
        receipt = manifest["files"].get(name, {})
        path = root / str(receipt.get("path", "__missing__"))
        payload = json.loads(path.read_text())
        for record in payload.get("records", []):
            number = str(record.get("company_number", ""))
            serialised = canonical_json(record)
            if number in canonical and canonical[number] != serialised:
                raise RuntimeError(f"Cross-cartridge drift before Parquet projection: {number}")
            canonical[number] = serialised
            records_by_number[number] = record
    records = [records_by_number[number] for number in sorted(records_by_number)]
    if len(records) != manifest.get("companies") or not records:
        raise RuntimeError("Parquet projection does not close over the JSON company universe")
    return records


def universe_digest(pairs: list[tuple[str, str]]) -> str:
    value = hashlib.sha256()
    for number, serialised in pairs:
        value.update(number.encode("utf-8"))
        value.update(b"\0")
        value.update(serialised.encode("utf-8"))
        value.update(b"\n")
    return value.hexdigest()


def load_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise RuntimeError(f"duckdb=={DUCKDB_VERSION} is required for the analytical candidate") from exc
    if duckdb.__version__ != DUCKDB_VERSION:
        raise RuntimeError(f"DuckDB version drift: expected {DUCKDB_VERSION}, received {duckdb.__version__}")
    return duckdb


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def parquet_schema_contract() -> list[dict]:
    return [{"name": name, "type": type_name, "nullable": nullable} for name, type_name, nullable in PARQUET_COLUMNS]


def parquet_audit(root: Path, expected_manifest: dict | None = None) -> dict:
    duckdb = load_duckdb()
    path = root / PARQUET_PATH
    if not path.is_file():
        raise RuntimeError("Analytical Parquet file is missing")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        escaped = sql_path(path)
        description = connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{escaped}')").fetchall()
        actual_schema = [
            {"name": row[0], "type": row[1], "nullable": str(row[2]).upper() == "YES"}
            for row in description
        ]
        # DuckDB's DESCRIBE may report all Parquet fields nullable. Field names
        # and physical types are the interoperable schema gate; nullability is
        # enforced independently below for every required column.
        expected_types = [(name, type_name) for name, type_name, _nullable in PARQUET_COLUMNS]
        actual_types = [(row["name"], row["type"]) for row in actual_schema]
        if actual_types != expected_types:
            raise RuntimeError(f"Parquet schema drift: {actual_types!r}")
        codecs = sorted(
            str(row[0]).upper()
            for row in connection.execute(
                f"SELECT DISTINCT compression FROM parquet_metadata('{escaped}')"
            ).fetchall()
        )
        if codecs != ["ZSTD"]:
            raise RuntimeError(f"Parquet compression drift: {codecs!r}")
        row = connection.execute(
            f"""
            SELECT
              count(*)::BIGINT,
              count(DISTINCT company_number)::BIGINT,
              count(*) FILTER (WHERE company_number IS NULL OR company_number = '')::BIGINT,
              count(*) FILTER (WHERE generation <> ? OR financial_currency <> 'GBP')::BIGINT,
              count(*) FILTER (
                WHERE company_name IS NULL OR company_name = ''
                   OR classification IS NULL OR classification = ''
                   OR assets_gte_10m IS NULL
                   OR energy_relevant_large_company IS NULL
                   OR probable_project_spv IS NULL
                   OR sic_codes_json IS NULL
                   OR btm_tags_json IS NULL
                   OR repd_name_candidates_json IS NULL
                   OR record_json IS NULL
              )::BIGINT
            FROM read_parquet('{escaped}')
            """,
            [GENERATION],
        ).fetchone()
        rows, distinct_keys, null_keys, contract_errors, required_nulls = map(int, row)
        duplicate_groups = int(
            connection.execute(
                f"SELECT count(*) FROM (SELECT company_number FROM read_parquet('{escaped}') GROUP BY company_number HAVING count(*) > 1)"
            ).fetchone()[0]
        )
        pairs = [
            (str(number), str(record_json))
            for number, record_json in connection.execute(
                f"SELECT company_number, record_json FROM read_parquet('{escaped}') ORDER BY company_number"
            ).fetchall()
        ]
    finally:
        connection.close()
    if rows < 1 or rows != distinct_keys or null_keys or duplicate_groups or contract_errors or required_nulls:
        raise RuntimeError("DuckDB idempotency/readback gate failed")
    result = {
        "schema": "companies-house-parquet-audit-v1",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "format": "parquet",
        "compression": codecs[0].lower(),
        "grain": PARQUET_GRAIN,
        "declared_key": list(PARQUET_KEY),
        "rows": rows,
        "distinct_keys": distinct_keys,
        "null_keys": null_keys,
        "duplicate_key_groups": duplicate_groups,
        "contract_errors": contract_errors + required_nulls,
        "schema_contract": parquet_schema_contract(),
        "schema_readback": actual_schema,
        "record_universe_sha256": universe_digest(pairs),
        "parquet": {"path": PARQUET_PATH, "bytes": path.stat().st_size, "sha256": digest(path)},
        "engine": {"name": "duckdb", "version": DUCKDB_VERSION, "threads": 1},
        "reference": {
            "repository": REFERENCE_REPOSITORY,
            "commit": REFERENCE_COMMIT,
            "conventions_only": True,
            "foreign_data_copied": False,
        },
    }
    if expected_manifest is not None:
        expected = expected_manifest.get("analytical_dataset", {})
        for key in (
            "format",
            "compression",
            "grain",
            "declared_key",
            "rows",
            "distinct_keys",
            "null_keys",
            "duplicate_key_groups",
            "schema_contract",
            "record_universe_sha256",
        ):
            if expected.get(key) != result.get(key):
                raise RuntimeError(f"Analytical manifest drift: {key}")
        for key in ("path", "bytes", "sha256"):
            if expected.get("file", {}).get(key) != result["parquet"].get(key):
                raise RuntimeError(f"Analytical Parquet receipt drift: {key}")
    return result


def write_analytical_parquet(root: Path, manifest: dict) -> dict:
    duckdb = load_duckdb()
    records = cartridge_union(root, manifest)
    rows = [analytical_row(record) for record in records]
    path = root / PARQUET_PATH
    if path.exists():
        raise RuntimeError("Parquet touched partition must be written from an empty target")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        fields = ",".join(f'"{name}" {type_name}' for name, type_name, _nullable in PARQUET_COLUMNS)
        connection.execute(f"CREATE TABLE companies ({fields}, PRIMARY KEY(company_number))")
        placeholders = ",".join("?" for _ in PARQUET_COLUMNS)
        connection.executemany(f"INSERT INTO companies VALUES ({placeholders})", rows)
        if int(connection.execute("SELECT count(*) FROM companies").fetchone()[0]) != len(rows):
            raise RuntimeError("DuckDB staging row closure failed")
        escaped = sql_path(path)
        connection.execute(
            f"COPY (SELECT * FROM companies ORDER BY company_number) TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
        )
    finally:
        connection.close()
    audit = parquet_audit(root)
    json_pairs = [(row[1], row[-1]) for row in rows]
    if audit["record_universe_sha256"] != universe_digest(json_pairs):
        raise RuntimeError("Parquet readback differs from the canonical JSON universe")
    audit_path = root / AUDIT_PATH
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def seal(*args, **kwargs) -> dict:
    # The inherited sealer invokes its verifier internally. Keep that first
    # check scoped to the inherited JSON closure, then extend and verify the
    # whole successor closure independently.
    active_verify = PREVIOUS.verify
    PREVIOUS.verify = ORIGINAL_VERIFY
    try:
        ORIGINAL_SEAL(*args, **kwargs)
    finally:
        PREVIOUS.verify = active_verify
    output = kwargs.get("output")
    if output is None and len(args) >= 2:
        output = args[1]
    root = Path(output)
    manifest_path = root / "manifest-v1.json"
    manifest = json.loads(manifest_path.read_text())
    audit = write_analytical_parquet(root, manifest)
    manifest["analytical_dataset"] = {
        "format": audit["format"],
        "compression": audit["compression"],
        "grain": audit["grain"],
        "declared_key": audit["declared_key"],
        "rows": audit["rows"],
        "distinct_keys": audit["distinct_keys"],
        "null_keys": audit["null_keys"],
        "duplicate_key_groups": audit["duplicate_key_groups"],
        "schema_contract": audit["schema_contract"],
        "record_universe_sha256": audit["record_universe_sha256"],
        "file": audit["parquet"],
        "source_json_projection_retained": True,
    }
    audit_path = root / AUDIT_PATH
    manifest["audits"] = [
        {"path": AUDIT_PATH, "bytes": audit_path.stat().st_size, "sha256": digest(audit_path)}
    ]
    manifest["data_discipline"] = {
        "owning_repository": "Ventusltd/companies",
        "reference_repository": REFERENCE_REPOSITORY,
        "reference_commit": REFERENCE_COMMIT,
        "conventions_only": True,
        "foreign_data_copied": False,
        "licensing_posture": "non-commercial-open-source",
        "touched_partition_policy": "full-generation-rewrite-from-empty-target",
        "file_count_and_bytes_are_monitors_not_truth": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result = verify(root)
    if result["status"] != "PASS":
        raise RuntimeError(f"Successor candidate verification failed: {result['errors']!r}")
    return manifest


def verify(root: Path) -> dict:
    inherited = ORIGINAL_VERIFY(root)
    errors = list(inherited.get("errors", []))
    companies = int(inherited.get("companies", 0))
    total_bytes = int(inherited.get("bytes", 0))
    try:
        manifest_path = root / "manifest-v1.json"
        manifest = json.loads(manifest_path.read_text())
        discipline = manifest.get("data_discipline", {})
        if discipline != {
            "owning_repository": "Ventusltd/companies",
            "reference_repository": REFERENCE_REPOSITORY,
            "reference_commit": REFERENCE_COMMIT,
            "conventions_only": True,
            "foreign_data_copied": False,
            "licensing_posture": "non-commercial-open-source",
            "touched_partition_policy": "full-generation-rewrite-from-empty-target",
            "file_count_and_bytes_are_monitors_not_truth": True,
        }:
            errors.append("data discipline")
        audit = parquet_audit(root, manifest)
        if audit["rows"] != companies:
            errors.append("Parquet/JSON company closure")
        json_records = cartridge_union(root, manifest)
        json_universe = universe_digest(
            [(str(record["company_number"]), canonical_json(record)) for record in json_records]
        )
        if audit["record_universe_sha256"] != json_universe:
            errors.append("Parquet/JSON semantic closure")
        if audit["parquet"]["bytes"] > PREVIOUS.MAXIMUM_FILE_BYTES:
            errors.append("Parquet file byte ceiling")
        audit_receipts = manifest.get("audits")
        audit_path = root / AUDIT_PATH
        expected_audit = {"path": AUDIT_PATH, "bytes": audit_path.stat().st_size, "sha256": digest(audit_path)}
        if audit_receipts != [expected_audit]:
            errors.append("Parquet audit receipt")
        else:
            stored_audit = json.loads(audit_path.read_text())
            if stored_audit != audit:
                errors.append("Parquet audit semantics")
        total_bytes += (root / PARQUET_PATH).stat().st_size + audit_path.stat().st_size
        expected_paths = {"manifest-v1.json", PARQUET_PATH, AUDIT_PATH}
        expected_paths.update(str(receipt["path"]) for receipt in manifest.get("files", {}).values())
        expected_paths.update(str(receipt["path"]) for receipt in manifest.get("evidence", []))
        actual_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
        if actual_paths != expected_paths:
            errors.append("candidate file closure")
        if total_bytes > PREVIOUS.MAXIMUM_TOTAL_BYTES:
            errors.append("candidate byte ceiling including Parquet")
    except Exception as exc:
        errors.append(f"analytical dataset: {exc}")
    return {
        "schema": "companies-house-bounded-verification-v2",
        "generation": GENERATION,
        "status": "FAIL" if errors else "PASS",
        "companies": companies,
        "bytes": total_bytes,
        "errors": errors[:100],
    }


# Route the inherited CLI through the successor functions while retaining its
# mature argument parser and error handling.
PREVIOUS.seal = seal
PREVIOUS.verify = verify


if __name__ == "__main__":
    raise SystemExit(PREVIOUS.main())
