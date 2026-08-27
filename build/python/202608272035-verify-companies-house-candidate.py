#!/usr/bin/env python3
"""Seal and verify both landed Companies grains for generation 202608272035."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

GENERATION = "202608272035"
BASE_COMMIT = "1f91f8efced903aa82e62acf56b9af2db476cfdb"
FIXED_GENERATED_AT = "2026-08-27T19:35:00Z"
PIPELINENEWS_COMMIT = "35f35ada161223fb3ee19e525664ee7f17df1ddd"
DUCKDB_VERSION = "1.3.2"
COMPANY_NUMBER = re.compile(r"^[A-Z0-9]{8}$")
COMPANY_PARQUET = "companies-v1.parquet"
RELATIONSHIP_PARQUET = "company-repd-candidates-v1.parquet"
AUDIT_PATH = "parquet-audit-v2.json"
EXPECTED_PLAN_SHA256 = "1f12a49779d5408ee2aa14b89ff5925b4fd7a83d1a1b6445fac539d8017202c7"
EXPECTED_REST_EVIDENCE_SHA256 = "7342dae046cbd6e1ad4b5b50f9c0f1ebadb5e16575c4aaa15a91833e9bbee2b2"
PARENT_PATH = Path(__file__).with_name("202608272016-verify-companies-house-candidate.py")

spec = importlib.util.spec_from_file_location("companies_verify_202608272016_for_2035", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272016 verifier")
PARENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT)
PARENT.GENERATION = GENERATION
PARENT.BASE_COMMIT = BASE_COMMIT
PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PREVIOUS.GENERATION = GENERATION
PARENT.PREVIOUS.BASE_COMMIT = BASE_COMMIT
PARENT.PREVIOUS.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.PREVIOUS.PIPELINENEWS_COMMIT = PIPELINENEWS_COMMIT
PARENT.PREVIOUS.COMPANY_NUMBER = COMPANY_NUMBER
BASE_VERIFY = PARENT.ORIGINAL_VERIFY

COMPANY_COLUMNS = tuple(PARENT.PARQUET_COLUMNS)
RELATIONSHIP_COLUMNS = (
    ("generation", "VARCHAR", False),
    ("company_number", "VARCHAR", False),
    ("repd_ref", "VARCHAR", False),
    ("match_type", "VARCHAR", False),
    ("gg_project_id", "VARCHAR", True),
    ("project", "VARCHAR", True),
    ("operator", "VARCHAR", True),
    ("technology", "VARCHAR", True),
    ("capacity_mw", "DECIMAL(38,6)", True),
    ("status", "VARCHAR", True),
    ("latitude", "DOUBLE", True),
    ("longitude", "DOUBLE", True),
    ("atlas_url", "VARCHAR", True),
    ("relationship_json", "VARCHAR", False),
)

REPD_RIGHTS = {
    "name": "Open Government Licence v3.0",
    "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    "attribution": (
        "Contains public sector information licensed under the Open Government Licence v3.0. "
        "Renewable Energy Planning Database source: Department for Energy Security and Net Zero; "
        "data managed by Barbour ABI."
    ),
    "source_page": "https://www.gov.uk/government/publications/renewable-energy-planning-database-quarterly-extract",
    "publication_updated": "2026-08-03",
    "catalogue_url": "https://www.data.gov.uk/dataset/a5b0ed13-c960-49ce-b1f6-3a6bbe0db1b7/repd",
    "catalogue_licence_id": "uk-ogl",
    "rights_caveat": (
        "OGL applies except where otherwise stated; personal data and third-party rights may be outside its scope, "
        "and data-protection duties still apply."
    ),
}
MATERIALISED_SOURCES = {
    "companies_house": {
        "dataset": "Companies House basic company and monthly accounts bulk data",
        "source_owner": "Companies House",
        "licence": PARENT.PREVIOUS.OGL,
    },
    "repd": {
        "dataset": "DESNZ Renewable Energy Planning Database Q2 2026",
        "source_owner": "Department for Energy Security and Net Zero",
        "data_manager": "Barbour ABI",
        "runtime_repository": "Ventusltd/pipelinenews",
        "runtime_commit": PIPELINENEWS_COMMIT,
        "runtime_path": "data/projects",
        "upstream_manifest": "data/manifests/202608261927-build-manifest-v9-1.json",
        "upstream_manifest_sha256": "67976a1bbcaf383ed7121b13060db3b864db9ce33dfc721a88b59c8ca8b8e06c",
        "licence": REPD_RIGHTS,
    },
}
FIELD_LINEAGE = {
    "companies_house_bulk": [
        "company_number",
        "company_name",
        "company_status",
        "sic_codes",
        "accounts_date",
        "total_assets",
        "net_assets",
        "turnover",
        "cash",
    ],
    "repd_materialised": [
        "repd_name_candidates[].repd_ref",
        "repd_name_candidates[].gg_project_id",
        "repd_name_candidates[].project",
        "repd_name_candidates[].operator",
        "repd_name_candidates[].technology",
        "repd_name_candidates[].capacity_mw",
        "repd_name_candidates[].status",
        "repd_name_candidates[].latitude",
        "repd_name_candidates[].longitude",
    ],
    "locally_derived": [
        "classification",
        "assets_gte_10m",
        "energy_relevant_large_company",
        "probable_project_spv",
        "btm_tags",
        "repd_name_candidates",
        "repd_name_candidates[].match_type",
        "repd_name_candidates[].atlas_url",
        "financial_currency",
        "news_identity_policy",
    ],
}
DATA_DISCIPLINE = {
    "owning_repository": "Ventusltd/companies",
    "format": "parquet",
    "compression": "zstd",
    "company_grain": "one row per distinct company in the candidate cartridge union",
    "company_declared_key": ["company_number"],
    "relationship_grain": "one evidence-qualified REPD candidate relationship",
    "relationship_declared_key": ["company_number", "repd_ref", "match_type"],
    "touched_partition_policy": "full-generation-rewrite-from-empty-target",
    "actual_landed_file_readback": True,
    "typed_projection_readback": True,
    "file_count_and_bytes_are_monitors_not_truth": True,
    "foreign_repository_files_committed": False,
    "foreign_data_materialised": True,
    "foreign_runtime_access": "read-only exact-commit exact-path sparse checkout",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def load_duckdb():
    return PARENT.load_duckdb()


def bounded_decimal(value, label: str) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RuntimeError(f"{label} is not numeric")
    try:
        result = Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"{label} is not a bounded decimal") from exc
    if not result.is_finite() or len(result.as_tuple().digits) > 38:
        raise RuntimeError(f"{label} is outside DECIMAL(38,6)")
    return result


def schema_contract(columns: tuple[tuple[str, str, bool], ...]) -> list[dict]:
    return [{"name": name, "type": type_name, "nullable": nullable} for name, type_name, nullable in columns]


def dataset_digest(rows: list[tuple[tuple[str, ...], str]]) -> str:
    value = hashlib.sha256()
    for key, record_json in sorted(rows):
        value.update("\0".join(key).encode("utf-8"))
        value.update(b"\0")
        value.update(record_json.encode("utf-8"))
        value.update(b"\n")
    return value.hexdigest()


def canonical_company_records(root: Path, manifest: dict) -> list[dict]:
    files = manifest.get("files", {})
    if set(files) != set(PARENT.PREVIOUS.EXPECTED_CARTRIDGES):
        raise RuntimeError("Cartridge closure is unexpected")
    canonical: dict[str, str] = {}
    records_by_number: dict[str, dict] = {}
    for name in sorted(PARENT.PREVIOUS.EXPECTED_CARTRIDGES):
        receipt = files[name]
        path = root / str(receipt.get("path", "__missing__"))
        payload = json.loads(path.read_text())
        records = payload.get("records")
        if not isinstance(records, list):
            raise RuntimeError(f"Cartridge records are malformed: {name}")
        seen: set[str] = set()
        for record in records:
            number = record.get("company_number")
            if not isinstance(number, str) or not COMPANY_NUMBER.fullmatch(number):
                raise RuntimeError(f"Invalid company number in {name}")
            if number in seen:
                raise RuntimeError(f"Duplicate company number in {name}: {number}")
            seen.add(number)
            serialised = canonical_json(record)
            if number in canonical and canonical[number] != serialised:
                raise RuntimeError(f"Cross-cartridge company drift: {number}")
            canonical[number] = serialised
            records_by_number[number] = record
    if not records_by_number or len(records_by_number) != manifest.get("companies"):
        raise RuntimeError("Company universe does not match the manifest")
    return [records_by_number[number] for number in sorted(records_by_number)]


def relationship_rows(records: list[dict]) -> list[tuple]:
    rows: list[tuple] = []
    seen: dict[tuple[str, str, str], str] = {}
    companies = {str(record["company_number"]) for record in records}
    for record in records:
        number = record["company_number"]
        relationships = record.get("repd_name_candidates")
        if not isinstance(relationships, list):
            raise RuntimeError(f"{number}.repd_name_candidates is not a list")
        for relationship in relationships:
            if not isinstance(relationship, dict):
                raise RuntimeError(f"REPD relationship is not an object for {number}")
            raw_ref = relationship.get("repd_ref")
            raw_match = relationship.get("match_type")
            if not isinstance(raw_ref, str) or not raw_ref.strip():
                raise RuntimeError(f"Relationship repd_ref is null or blank for {number}")
            if not isinstance(raw_match, str) or not raw_match.strip():
                raise RuntimeError(f"Relationship match_type is null or blank for {number}")
            if raw_ref != raw_ref.strip() or raw_match != raw_match.strip():
                raise RuntimeError(f"Relationship key contains surrounding whitespace for {number}")
            ref = raw_ref.strip()
            match_type = raw_match.strip()
            key = (number, ref, match_type)
            relation_json = canonical_json(relationship)
            if key in seen:
                qualifier = "drift" if seen[key] != relation_json else "duplicate"
                raise RuntimeError(f"Relationship key {qualifier}: {'/'.join(key)}")
            if number not in companies:
                raise RuntimeError(f"Relationship company key is outside the company universe: {number}")
            seen[key] = relation_json
            rows.append(
                (
                    GENERATION,
                    number,
                    ref,
                    match_type,
                    relationship.get("gg_project_id") or None,
                    relationship.get("project") or None,
                    relationship.get("operator") or None,
                    relationship.get("technology") or None,
                    bounded_decimal(relationship.get("capacity_mw"), f"{number}/{ref}.capacity_mw"),
                    relationship.get("status") or None,
                    float(relationship["latitude"]) if relationship.get("latitude") is not None else None,
                    float(relationship["longitude"]) if relationship.get("longitude") is not None else None,
                    relationship.get("atlas_url") or None,
                    relation_json,
                )
            )
    if not rows:
        raise RuntimeError("REPD candidate relationship dataset is empty")
    return sorted(rows, key=lambda row: (row[1], row[2], row[3]))


def company_rows(records: list[dict]) -> list[tuple]:
    return [PARENT.analytical_row(record) for record in records]


def write_parquet(
    path: Path,
    columns: tuple[tuple[str, str, bool], ...],
    rows: list[tuple],
    key: tuple[str, ...],
) -> None:
    if path.exists():
        raise RuntimeError("Touched Parquet partition must be written from an empty target")
    duckdb = load_duckdb()
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        fields = ",".join(f'"{name}" {type_name}' for name, type_name, _nullable in columns)
        primary_key = ",".join(f'"{name}"' for name in key)
        connection.execute(f"CREATE TABLE staged ({fields}, PRIMARY KEY({primary_key}))")
        placeholders = ",".join("?" for _ in columns)
        connection.executemany(f"INSERT INTO staged VALUES ({placeholders})", rows)
        if int(connection.execute("SELECT count(*) FROM staged").fetchone()[0]) != len(rows):
            raise RuntimeError("DuckDB staging row closure failed")
        order = ",".join(f'"{name}"' for name in key)
        escaped = sql_path(path)
        connection.execute(
            f"COPY (SELECT * FROM staged ORDER BY {order}) TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
        )
    finally:
        connection.close()


def audit_parquet(
    path: Path,
    columns: tuple[tuple[str, str, bool], ...],
    key: tuple[str, ...],
    record_json_column: str,
    expected_rows: list[tuple],
) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Landed Parquet file is missing: {path.name}")
    duckdb = load_duckdb()
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        escaped = sql_path(path)
        description = connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{escaped}')").fetchall()
        actual_types = [(str(row[0]), str(row[1])) for row in description]
        expected_types = [(name, type_name) for name, type_name, _nullable in columns]
        if actual_types != expected_types:
            raise RuntimeError(f"Parquet schema drift for {path.name}: {actual_types!r}")
        codecs = sorted(
            str(row[0]).upper()
            for row in connection.execute(f"SELECT DISTINCT compression FROM parquet_metadata('{escaped}')").fetchall()
        )
        if codecs != ["ZSTD"]:
            raise RuntimeError(f"Parquet compression is not exactly ZSTD for {path.name}: {codecs!r}")
        key_null = " OR ".join(f'"{name}" IS NULL OR CAST("{name}" AS VARCHAR) = \'\'' for name in key)
        group_key = ",".join(f'"{name}"' for name in key)
        rows, null_keys = map(
            int,
            connection.execute(
                f"SELECT count(*)::BIGINT, count(*) FILTER (WHERE {key_null})::BIGINT FROM read_parquet('{escaped}')"
            ).fetchone(),
        )
        distinct_keys = int(
            connection.execute(
                f"SELECT count(*) FROM (SELECT {group_key} FROM read_parquet('{escaped}') GROUP BY {group_key})"
            ).fetchone()[0]
        )
        duplicate_groups = int(
            connection.execute(
                f"SELECT count(*) FROM (SELECT {group_key} FROM read_parquet('{escaped}') "
                f"GROUP BY {group_key} HAVING count(*) > 1)"
            ).fetchone()[0]
        )
        required_checks = []
        for name, type_name, nullable in columns:
            if nullable:
                continue
            condition = f'"{name}" IS NULL'
            if type_name == "VARCHAR":
                condition += f' OR "{name}" = \'\''
            required_checks.append(f"({condition})")
        required_nulls = int(
            connection.execute(
                f"SELECT count(*) FROM read_parquet('{escaped}') WHERE {' OR '.join(required_checks)}"
            ).fetchone()[0]
        )
        fields = ",".join(f'"{name}" {type_name}' for name, type_name, _nullable in columns)
        expected_key = ",".join(f'"{name}"' for name in key)
        connection.execute(f"CREATE TABLE expected ({fields}, PRIMARY KEY({expected_key}))")
        placeholders = ",".join("?" for _ in columns)
        connection.executemany(f"INSERT INTO expected VALUES ({placeholders})", expected_rows)
        join = " AND ".join(f'a."{name}" = e."{name}"' for name in key)
        mismatch = " OR ".join(f'a."{name}" IS DISTINCT FROM e."{name}"' for name, _type, _nullable in columns)
        first_key = key[0]
        typed_mismatches = int(
            connection.execute(
                f"SELECT count(*) FROM read_parquet('{escaped}') a FULL OUTER JOIN expected e ON {join} "
                f'WHERE a."{first_key}" IS NULL OR e."{first_key}" IS NULL OR {mismatch}'
            ).fetchone()[0]
        )
        selected = ",".join(f'CAST("{name}" AS VARCHAR)' for name in key)
        pairs = [
            (tuple(str(value) for value in row[:-1]), str(row[-1]))
            for row in connection.execute(
                f'SELECT {selected}, "{record_json_column}" FROM read_parquet(\'{escaped}\') ORDER BY {group_key}'
            ).fetchall()
        ]
    finally:
        connection.close()
    expected_pairs = []
    indexes = {name: index for index, (name, _type, _nullable) in enumerate(columns)}
    for row in expected_rows:
        expected_pairs.append(
            (tuple(str(row[indexes[name]]) for name in key), str(row[indexes[record_json_column]]))
        )
    semantic_digest = dataset_digest(pairs)
    if (
        rows < 1
        or rows != len(expected_rows)
        or rows != distinct_keys
        or null_keys
        or duplicate_groups
        or required_nulls
        or typed_mismatches
        or semantic_digest != dataset_digest(expected_pairs)
    ):
        raise RuntimeError(f"DuckDB actual-landed readback failed for {path.name}")
    return {
        "status": "PASS",
        "format": "parquet",
        "compression": "zstd",
        "compression_codecs": codecs,
        "declared_key": list(key),
        "rows": rows,
        "distinct_keys": distinct_keys,
        "null_keys": null_keys,
        "duplicate_key_groups": duplicate_groups,
        "required_column_null_rows": required_nulls,
        "typed_column_mismatches": typed_mismatches,
        "schema_contract": schema_contract(columns),
        "schema_readback": [{"name": name, "type": type_name} for name, type_name in actual_types],
        "record_universe_sha256": semantic_digest,
        "file": {"path": path.name, "bytes": path.stat().st_size, "sha256": digest(path)},
    }


def build_analytical_datasets(root: Path, manifest: dict) -> dict:
    records = canonical_company_records(root, manifest)
    companies = company_rows(records)
    relationships = relationship_rows(records)
    write_parquet(root / COMPANY_PARQUET, COMPANY_COLUMNS, companies, ("company_number",))
    write_parquet(
        root / RELATIONSHIP_PARQUET,
        RELATIONSHIP_COLUMNS,
        relationships,
        ("company_number", "repd_ref", "match_type"),
    )
    company_audit = audit_parquet(
        root / COMPANY_PARQUET,
        COMPANY_COLUMNS,
        ("company_number",),
        "record_json",
        companies,
    )
    relationship_audit = audit_parquet(
        root / RELATIONSHIP_PARQUET,
        RELATIONSHIP_COLUMNS,
        ("company_number", "repd_ref", "match_type"),
        "relationship_json",
        relationships,
    )
    return {
        "schema": "companies-house-parquet-audit-v2",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "engine": {"name": "duckdb", "version": DUCKDB_VERSION, "threads": 1},
        "datasets": {
            "companies": {
                **company_audit,
                "grain": "one row per distinct company in the candidate cartridge union",
            },
            "company_repd_candidates": {
                **relationship_audit,
                "grain": "one evidence-qualified REPD candidate relationship",
                "identity_posture": "CANDIDATE_RELATIONSHIP_ONLY_NOT_PRIMARY_PROJECT_BINDING",
            },
        },
    }


def annotate_cartridges(root: Path, manifest: dict) -> None:
    for name in sorted(PARENT.PREVIOUS.EXPECTED_CARTRIDGES):
        receipt = manifest["files"][name]
        path = root / receipt["path"]
        payload = json.loads(path.read_text())
        payload["usage_context"] = "NON_COMMERCIAL_OPEN_SOURCE"
        payload["source_rights_are_distinct_from_usage_context"] = True
        payload["licence_scope"] = "Companies House fields only; REPD-derived fields use materialised_sources.repd"
        payload["materialised_sources"] = MATERIALISED_SOURCES
        payload["field_lineage"] = FIELD_LINEAGE
        path.write_text(canonical_json(payload) + "\n")
        receipt.update({"records": len(payload["records"]), "bytes": path.stat().st_size, "sha256": digest(path)})


def seal(
    raw_root: Path,
    output: Path,
    plan_path: Path,
    receipts_root: Path,
    reports_root: Path,
    repd_root: Path,
    basic_root: Path,
    accounts_path: Path,
    rest_evidence_path: Path,
    basic_report_path: Path,
    source_commit: str,
) -> dict:
    if digest(plan_path) != EXPECTED_PLAN_SHA256:
        raise RuntimeError("The source-pinned archive plan drifted")
    if digest(rest_evidence_path) != EXPECTED_REST_EVIDENCE_SHA256:
        raise RuntimeError("The deterministic REST non-use evidence drifted")
    PARENT.seal(
        raw_root,
        output,
        plan_path,
        receipts_root,
        reports_root,
        repd_root,
        basic_root,
        accounts_path,
        rest_evidence_path,
        basic_report_path,
        source_commit,
    )
    root = Path(output)
    manifest_path = root / "manifest-v1.json"
    manifest = json.loads(manifest_path.read_text())
    # The inherited seal was independently checked before this successor replaces
    # its one-grain analytical closure with a full two-grain rewrite.
    (root / PARENT.PARQUET_PATH).unlink()
    (root / PARENT.AUDIT_PATH).unlink()
    manifest.pop("analytical_dataset", None)
    manifest.pop("audits", None)
    annotate_cartridges(root, manifest)
    # Retain the inherited v1 cartridge-container schema: its verifier accepts
    # additive fields, while the two landed analytical datasets declare their
    # own explicit v2 audit schema below.
    manifest["schema"] = "companies-house-bounded-candidate-v1"
    manifest["usage_context"] = "NON_COMMERCIAL_OPEN_SOURCE"
    manifest["source_licence"] = PARENT.PREVIOUS.OGL
    manifest["source_licences"] = MATERIALISED_SOURCES
    manifest["source_rights_are_distinct_from_usage_context"] = True
    manifest["field_lineage"] = FIELD_LINEAGE
    manifest["data_discipline"] = DATA_DISCIPLINE
    manifest["inputs"]["repd_runtime_read"] = {
        "repository": "Ventusltd/pipelinenews",
        "commit": PIPELINENEWS_COMMIT,
        "path": "data/projects",
        "mode": "read-only sparse checkout",
        "foreign_repository_files_committed": False,
        "foreign_data_materialised": True,
    }
    manifest["publication"] = {
        "candidate_path": f"data/candidates/{GENERATION}/",
        "candidate_branch": f"candidate/{GENERATION}",
        "stable_path": "data/current/",
        "stable_path_must_change": False,
        "pages_must_change": False,
        "promotion_eligible": False,
    }
    audit = build_analytical_datasets(root, manifest)
    audit_path = root / AUDIT_PATH
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    manifest["analytical_dataset"] = audit["datasets"]["companies"]
    manifest["relationship_dataset"] = audit["datasets"]["company_repd_candidates"]
    manifest["audits"] = [{"path": AUDIT_PATH, "bytes": audit_path.stat().st_size, "sha256": digest(audit_path)}]
    manifest["candidate_outputs"] = {
        "json_cartridges": len(PARENT.PREVIOUS.EXPECTED_CARTRIDGES),
        "company_parquet": COMPANY_PARQUET,
        "relationship_parquet": RELATIONSHIP_PARQUET,
        "duckdb_audit": AUDIT_PATH,
        "exact_candidate_file_closure_enforced": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result = verify(root)
    if result["status"] != "PASS":
        raise RuntimeError(f"Successor candidate verification failed: {result['errors']!r}")
    return manifest


def verify(root: Path) -> dict:
    errors: list[str] = []
    companies = 0
    try:
        inherited = BASE_VERIFY(root)
        errors.extend(inherited.get("errors", []))
        manifest_path = root / "manifest-v1.json"
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest.get("schema") != "companies-house-bounded-candidate-v1"
            or manifest.get("generation") != GENERATION
            or manifest.get("generated_at") != FIXED_GENERATED_AT
            or manifest.get("deployment_state") != "not-authorised"
            or manifest.get("promotion_eligible") is not False
        ):
            errors.append("candidate identity/quarantine")
        if (
            manifest.get("usage_context") != "NON_COMMERCIAL_OPEN_SOURCE"
            or manifest.get("source_licence") != PARENT.PREVIOUS.OGL
            or manifest.get("source_licences") != MATERIALISED_SOURCES
            or manifest.get("source_rights_are_distinct_from_usage_context") is not True
            or manifest.get("field_lineage") != FIELD_LINEAGE
        ):
            errors.append("usage context/source rights/field lineage")
        if manifest.get("data_discipline") != DATA_DISCIPLINE:
            errors.append("data discipline")
        publication = manifest.get("publication", {})
        if publication != {
            "candidate_path": f"data/candidates/{GENERATION}/",
            "candidate_branch": f"candidate/{GENERATION}",
            "stable_path": "data/current/",
            "stable_path_must_change": False,
            "pages_must_change": False,
            "promotion_eligible": False,
        }:
            errors.append("publication boundary")
        runtime = manifest.get("inputs", {}).get("repd_runtime_read", {})
        if runtime != {
            "repository": "Ventusltd/pipelinenews",
            "commit": PIPELINENEWS_COMMIT,
            "path": "data/projects",
            "mode": "read-only sparse checkout",
            "foreign_repository_files_committed": False,
            "foreign_data_materialised": True,
        }:
            errors.append("REPD runtime provenance")
        if digest(root / "evidence/download-plan.json") != EXPECTED_PLAN_SHA256:
            errors.append("source-pinned archive plan")
        if digest(root / "evidence/rest-api.json") != EXPECTED_REST_EVIDENCE_SHA256:
            errors.append("deterministic REST non-use evidence")
        for name in sorted(PARENT.PREVIOUS.EXPECTED_CARTRIDGES):
            path = root / str(manifest.get("files", {}).get(name, {}).get("path", "__missing__"))
            payload = json.loads(path.read_text())
            if (
                payload.get("usage_context") != "NON_COMMERCIAL_OPEN_SOURCE"
                or payload.get("source_rights_are_distinct_from_usage_context") is not True
                or payload.get("materialised_sources") != MATERIALISED_SOURCES
                or payload.get("field_lineage") != FIELD_LINEAGE
            ):
                errors.append(f"{name}: materialised source provenance")
        records = canonical_company_records(root, manifest)
        companies = len(records)
        expected_companies = company_rows(records)
        expected_relationships = relationship_rows(records)
        company_audit = audit_parquet(
            root / COMPANY_PARQUET,
            COMPANY_COLUMNS,
            ("company_number",),
            "record_json",
            expected_companies,
        )
        relationship_audit = audit_parquet(
            root / RELATIONSHIP_PARQUET,
            RELATIONSHIP_COLUMNS,
            ("company_number", "repd_ref", "match_type"),
            "relationship_json",
            expected_relationships,
        )
        expected_audit = {
            "schema": "companies-house-parquet-audit-v2",
            "generation": GENERATION,
            "generated_at": FIXED_GENERATED_AT,
            "deployment_state": "not-authorised",
            "status": "PASS",
            "engine": {"name": "duckdb", "version": DUCKDB_VERSION, "threads": 1},
            "datasets": {
                "companies": {
                    **company_audit,
                    "grain": "one row per distinct company in the candidate cartridge union",
                },
                "company_repd_candidates": {
                    **relationship_audit,
                    "grain": "one evidence-qualified REPD candidate relationship",
                    "identity_posture": "CANDIDATE_RELATIONSHIP_ONLY_NOT_PRIMARY_PROJECT_BINDING",
                },
            },
        }
        if manifest.get("analytical_dataset") != expected_audit["datasets"]["companies"]:
            errors.append("company Parquet manifest/readback")
        if manifest.get("relationship_dataset") != expected_audit["datasets"]["company_repd_candidates"]:
            errors.append("relationship Parquet manifest/readback")
        audit_path = root / AUDIT_PATH
        if json.loads(audit_path.read_text()) != expected_audit:
            errors.append("stored DuckDB audit semantics")
        expected_audit_receipt = {"path": AUDIT_PATH, "bytes": audit_path.stat().st_size, "sha256": digest(audit_path)}
        if manifest.get("audits") != [expected_audit_receipt]:
            errors.append("DuckDB audit receipt")
        expected_paths = {"manifest-v1.json", COMPANY_PARQUET, RELATIONSHIP_PARQUET, AUDIT_PATH}
        expected_paths.update(str(receipt["path"]) for receipt in manifest.get("files", {}).values())
        expected_paths.update(str(receipt["path"]) for receipt in manifest.get("evidence", []))
        actual_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
        if actual_paths != expected_paths:
            errors.append("candidate file closure")
        if any((root / name).stat().st_size > PARENT.PREVIOUS.MAXIMUM_FILE_BYTES for name in (COMPANY_PARQUET, RELATIONSHIP_PARQUET)):
            errors.append("Parquet file byte ceiling")
        if sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) > PARENT.PREVIOUS.MAXIMUM_TOTAL_BYTES:
            errors.append("candidate total byte ceiling")
    except Exception as exc:
        errors.append(str(exc))
    return {
        "schema": "companies-house-bounded-verification-v4",
        "generation": GENERATION,
        "status": "FAIL" if errors else "PASS",
        "companies": companies,
        "errors": errors[:100],
    }


PARENT.PREVIOUS.seal = seal
PARENT.PREVIOUS.verify = verify


if __name__ == "__main__":
    raise SystemExit(PARENT.PREVIOUS.main())
