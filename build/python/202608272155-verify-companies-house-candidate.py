#!/usr/bin/env python3
"""Direct 202608272155 sealer for bounded JSON shards and two Parquet grains."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import re
import shutil
import sys
import urllib.parse
from pathlib import Path

GENERATION = "202608272155"
BASE_COMMIT = "edc8d5d08ca6e224af0a907af90d0ed253d1c60d"
FIXED_GENERATED_AT = "2026-08-27T21:55:00Z"
EXPECTED_PLAN_SHA256 = "4451ed5da8cc2f9246f2e6cc06f120faec8efeb8e19c3bac3919975073e7025e"
EXPECTED_REST_EVIDENCE_SHA256 = "a6f6334f4d878644183cd2261caa258a16c8bbdd9f5bf547b75cfc44b77dac6f"
PARENT_PATH = Path(__file__).with_name("202608272120-verify-companies-house-candidate.py")

spec = importlib.util.spec_from_file_location("companies_verify_202608272120_pure_helpers_for_2155", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272120 helper closure")
PARENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PARENT)

# Import schemas and pure validators only. The 2120/2035/2016 seal and verify
# functions are deliberately never called: their monolithic JSON verifier fails
# before the two landed Parquet grains can be produced.
PARENT.GENERATION = GENERATION
PARENT.BASE_COMMIT = BASE_COMMIT
PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
PARENT.EXPECTED_PLAN_SHA256 = EXPECTED_PLAN_SHA256
PARENT.EXPECTED_REST_EVIDENCE_SHA256 = EXPECTED_REST_EVIDENCE_SHA256
ENGINE = PARENT.BASE
ENGINE.GENERATION = GENERATION
ENGINE.BASE_COMMIT = BASE_COMMIT
ENGINE.FIXED_GENERATED_AT = FIXED_GENERATED_AT
ENGINE.EXPECTED_PLAN_SHA256 = EXPECTED_PLAN_SHA256
ENGINE.EXPECTED_REST_EVIDENCE_SHA256 = EXPECTED_REST_EVIDENCE_SHA256
ENGINE.PARENT.GENERATION = GENERATION
ENGINE.PARENT.BASE_COMMIT = BASE_COMMIT
ENGINE.PARENT.FIXED_GENERATED_AT = FIXED_GENERATED_AT
ENGINE.PARENT.PREVIOUS.GENERATION = GENERATION
ENGINE.PARENT.PREVIOUS.BASE_COMMIT = BASE_COMMIT
ENGINE.PARENT.PREVIOUS.FIXED_GENERATED_AT = FIXED_GENERATED_AT

LEGACY = ENGINE.PARENT.PREVIOUS
EXPECTED_CARTRIDGES = frozenset(LEGACY.EXPECTED_CARTRIDGES)
COMPANY_PARQUET = ENGINE.COMPANY_PARQUET
RELATIONSHIP_PARQUET = ENGINE.RELATIONSHIP_PARQUET
AUDIT_PATH = ENGINE.AUDIT_PATH
DUCKDB_VERSION = ENGINE.DUCKDB_VERSION
COMPANY_COLUMNS = ENGINE.COMPANY_COLUMNS
RELATIONSHIP_COLUMNS = ENGINE.RELATIONSHIP_COLUMNS

MAXIMUM_FILE_BYTES = 90_000_000
SHARD_TARGET_BYTES = 64_000_000
MAXIMUM_TOTAL_BYTES = 200_000_000
SHARD_SCHEMA = "companies-house-cartridge-shard-v2"
MANIFEST_SCHEMA = "companies-house-bounded-candidate-v2"
PARTITION_SCHEME = "company-number-ordered-greedy-byte-bound-v1"
DECLARED_KEY = ["company_number"]

SHARD_POLICY = {
    "scheme": PARTITION_SCHEME,
    "declared_key": DECLARED_KEY,
    "ordering": "strictly-increasing-company-number",
    "target_bytes_including_envelope_and_lf": SHARD_TARGET_BYTES,
    "maximum_file_bytes": MAXIMUM_FILE_BYTES,
    "empty_shards_allowed": False,
}
COVERAGE = {
    "kind": "bounded-three-month-candidate",
    "accounts_months": 3,
    "partial_coverage": True,
    "annual_bootstrap": False,
}
PRIVACY = {
    "directors": False,
    "individual_psc": False,
    "dates_of_birth": False,
    "residential_addresses": False,
    "credit_scores": False,
    "bankability_scores": False,
}
PUBLICATION = {
    "candidate_path": f"data/candidates/{GENERATION}/",
    "candidate_branch": f"candidate/{GENERATION}",
    "stable_path": "data/current/",
    "stable_path_must_change": False,
    "pages_must_change": False,
    "promotion_eligible": False,
}
LOGICAL_ENTRY_KEYS = {
    "declared_key",
    "records",
    "distinct_keys",
    "record_universe_sha256",
    "shard_policy",
    "shards",
}
SHARD_RECEIPT_KEYS = {
    "ordinal",
    "path",
    "rows",
    "first_company_number",
    "last_company_number",
    "bytes",
    "sha256",
    "record_universe_sha256",
}
MANIFEST_KEYS = {
    "schema",
    "generation",
    "generated_at",
    "deployment_state",
    "promotion_eligible",
    "coverage",
    "threshold_gbp",
    "financial_currency",
    "inputs",
    "cartridges",
    "evidence",
    "companies",
    "privacy",
    "licence",
    "usage_context",
    "source_licence",
    "source_licences",
    "source_rights_are_distinct_from_usage_context",
    "field_lineage",
    "data_discipline",
    "publication",
    "analytical_dataset",
    "relationship_dataset",
    "audits",
    "candidate_outputs",
}
INPUT_KEYS = {
    "companies_base_commit",
    "generation_source_commit",
    "pipelinenews_commit",
    "repd",
    "repd_runtime_read",
    "download_plan_sha256",
    "basic_archive_sha256",
    "accounts_latest_sha256",
    "accounts_latest_records",
    "optional_rest",
    "basic_validation_sha256",
    "news",
}
EXPECTED_REPD_PATHS = [
    *(f"202608261927-project-partition-v9-1-{index:02d}.json" for index in range(1, 17)),
]
EXPECTED_REPD_CLOSURE_SHA256 = "d00dffe4659dbbb796cb1f32a6e446d3c429e800fc2c446b79b90189ee1db99c"
EXPECTED_REPD_TOTAL_BYTES = 9_605_267
EXPECTED_REPD_PROJECTS = 7_680
ALLOWED_MATCH_TYPES = {
    "EXACT_OPERATOR_NAME",
    "EXACT_PROJECT_NAME",
    "PROJECT_NAME_SPV_CANDIDATE",
}
DATA_DISCIPLINE = {
    **copy.deepcopy(ENGINE.DATA_DISCIPLINE),
    "logical_json_partitioning": PARTITION_SCHEME,
    "published_file_maximum_bytes": MAXIMUM_FILE_BYTES,
    "candidate_total_maximum_bytes": MAXIMUM_TOTAL_BYTES,
    "aggregate_file_count_and_bytes": "MONITORS_WITH_HARD_PUBLICATION_RESOURCE_GATES",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def encode_ordered_records(records: list[dict]) -> tuple[list[bytes], str]:
    value = hashlib.sha256()
    previous = None
    encoded = []
    for record in records:
        number = record.get("company_number")
        if not isinstance(number, str) or not ENGINE.COMPANY_NUMBER.fullmatch(number):
            raise RuntimeError("Cartridge record has an invalid company key")
        if previous is not None and number <= previous:
            raise RuntimeError("Cartridge records are not strictly increasing by company_number")
        previous = number
        record_bytes = canonical_json(record).encode("utf-8")
        encoded.append(record_bytes)
        value.update(number.encode("utf-8"))
        value.update(b"\0")
        value.update(record_bytes)
        value.update(b"\n")
    return encoded, value.hexdigest()


def record_digest(records: list[dict]) -> str:
    return encode_ordered_records(records)[1]


def encoded_record_digest(records: list[dict], encoded: list[bytes]) -> str:
    if len(records) != len(encoded):
        raise RuntimeError("Cached canonical record closure drifted")
    value = hashlib.sha256()
    previous = None
    for record, record_bytes in zip(records, encoded):
        number = record["company_number"]
        if previous is not None and number <= previous:
            raise RuntimeError("Cached cartridge order drifted")
        previous = number
        value.update(number.encode("utf-8"))
        value.update(b"\0")
        value.update(record_bytes)
        value.update(b"\n")
    return value.hexdigest()


def shard_common(logical_name: str, ordinal: int) -> dict:
    return {
        "schema": SHARD_SCHEMA,
        "generation": GENERATION,
        "snapshot_id": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "coverage": "BOUNDED_THREE_MONTH_CANDIDATE",
        "logical_cartridge": logical_name,
        "ordinal": ordinal,
        "declared_key": DECLARED_KEY,
        "shard_policy": SHARD_POLICY,
        "usage_context": "NON_COMMERCIAL_OPEN_SOURCE",
        "source_rights_are_distinct_from_usage_context": True,
        "licence": LEGACY.OGL,
        "licence_scope": "Companies House fields only; REPD-derived fields use materialised_sources.repd",
        "materialised_sources": ENGINE.MATERIALISED_SOURCES,
        "field_lineage": ENGINE.FIELD_LINEAGE,
    }


def render_shard(logical_name: str, ordinal: int, records: list[dict]) -> bytes:
    return (canonical_json({**shard_common(logical_name, ordinal), "records": records}) + "\n").encode("utf-8")


def render_shard_from_encoded(logical_name: str, ordinal: int, encoded: list[bytes]) -> bytes:
    empty = render_shard(logical_name, ordinal, [])
    marker = b'"records":[]'
    if empty.count(marker) != 1:
        raise RuntimeError("Canonical shard envelope does not contain one records marker")
    replacement = b'"records":[' + b",".join(encoded) + b"]"
    return empty.replace(marker, replacement)


def partition_records(
    logical_name: str, records: list[dict]
) -> tuple[list[tuple[list[dict], list[bytes], int]], str]:
    """Greedy deterministic partitioning measured against exact final bytes."""
    if not records:
        raise RuntimeError(f"Logical cartridge is empty: {logical_name}")
    all_encoded, union_digest = encode_ordered_records(records)
    groups: list[tuple[list[dict], list[bytes], int]] = []
    current: list[dict] = []
    current_encoded: list[bytes] = []
    ordinal = 0
    # The canonical empty payload already contains the list brackets and LF.
    # Replacing [] with canonical records adds exactly their bytes and the
    # inter-record commas, so this remains linear even for hundreds of thousands
    # of rows while still measuring the exact final file size.
    current_bytes = len(render_shard(logical_name, ordinal, []))
    for record, record_bytes in zip(records, all_encoded):
        encoded_bytes = len(record_bytes)
        increment = encoded_bytes + (1 if current else 0)
        if current_bytes + increment <= SHARD_TARGET_BYTES:
            current.append(record)
            current_encoded.append(record_bytes)
            current_bytes += increment
            continue
        if not current:
            raise RuntimeError(f"One record exceeds the exact shard target: {logical_name}/{record['company_number']}")
        groups.append((current, current_encoded, current_bytes))
        ordinal += 1
        current = [record]
        current_encoded = [record_bytes]
        current_bytes = len(render_shard(logical_name, ordinal, [])) + encoded_bytes
        if current_bytes > SHARD_TARGET_BYTES:
            raise RuntimeError(f"One record exceeds the exact shard target: {logical_name}/{record['company_number']}")
    groups.append((current, current_encoded, current_bytes))
    return groups, union_digest


def write_logical_cartridge(root: Path, logical_name: str, records: list[dict]) -> dict:
    groups, union_digest = partition_records(logical_name, records)
    shards = []
    for ordinal, (group, encoded, predicted_size) in enumerate(groups):
        relative = f"cartridges/{logical_name}/part-{ordinal:05d}.json"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise RuntimeError(f"Shard target already exists: {relative}")
        rendered = render_shard_from_encoded(logical_name, ordinal, encoded)
        if len(rendered) != predicted_size:
            raise RuntimeError(f"Exact shard byte prediction drifted: {relative}")
        if predicted_size > SHARD_TARGET_BYTES or predicted_size > MAXIMUM_FILE_BYTES:
            raise RuntimeError(f"Shard byte ceiling failed before write: {relative}")
        path.write_bytes(rendered)
        shards.append(
            {
                "ordinal": ordinal,
                "path": relative,
                "rows": len(group),
                "first_company_number": group[0]["company_number"],
                "last_company_number": group[-1]["company_number"],
                "bytes": path.stat().st_size,
                "sha256": digest(path),
                "record_universe_sha256": encoded_record_digest(group, encoded),
            }
        )
    return {
        "declared_key": DECLARED_KEY,
        "records": len(records),
        "distinct_keys": len(records),
        "record_universe_sha256": union_digest,
        "shard_policy": SHARD_POLICY,
        "shards": shards,
    }


def safe_shard_path(root: Path, logical_name: str, ordinal: int, raw_path: object) -> Path:
    expected = f"cartridges/{logical_name}/part-{ordinal:05d}.json"
    if raw_path != expected:
        raise RuntimeError(f"Shard path/ordinal closure failed: {logical_name}/{ordinal}")
    path = root / expected
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"Shard path is missing, unsafe or symlinked: {expected}")
    return path


def validate_company_record(record: dict, label: str) -> None:
    LEGACY.require_private_safe(record, label)
    if (
        record.get("classification") not in LEGACY.CLASSIFICATIONS
        or record.get("financial_currency") != "GBP"
        or record.get("news_identity_policy") != "NEWS_MAY_ANNOTATE_BUT_NEVER_ESTABLISH_IDENTITY"
    ):
        raise RuntimeError(f"Company classification/currency/identity policy failed: {label}")
    relationships = record.get("repd_name_candidates")
    if not isinstance(relationships, list):
        raise RuntimeError(f"Company relationship list failed: {label}")
    expected_classification = (
        "REPD_NAME_CANDIDATE"
        if relationships
        else "PROBABLE_PROJECT_SPV"
        if record.get("probable_project_spv") is True
        else "ENERGY_RELEVANT_LARGE_COMPANY"
        if record.get("energy_relevant_large_company") is True
        else "UNRESOLVED_CANDIDATE"
    )
    if record.get("classification") != expected_classification:
        raise RuntimeError(f"Company derived classification failed: {label}")
    for relationship in relationships:
        if not isinstance(relationship, dict):
            raise RuntimeError(f"Company relationship object failed: {label}")
        ref = str(relationship.get("repd_ref", ""))
        project_id = str(relationship.get("gg_project_id", ""))
        if (
            not ref
            or relationship.get("match_type") not in ALLOWED_MATCH_TYPES
            or project_id != f"GG2050-REPD-{ref}"
        ):
            raise RuntimeError(f"Company relationship identity failed: {label}/{ref}")
        for field, minimum, maximum in (("latitude", -90.0, 90.0), ("longitude", -180.0, 180.0)):
            raw_value = relationship.get(field)
            if raw_value is None:
                continue
            if isinstance(raw_value, bool):
                raise RuntimeError(f"Company relationship coordinate failed: {label}/{ref}/{field}")
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Company relationship coordinate failed: {label}/{ref}/{field}") from exc
            if not math.isfinite(value) or value < minimum or value > maximum:
                raise RuntimeError(f"Company relationship coordinate failed: {label}/{ref}/{field}")
        atlas = relationship.get("atlas_url")
        if atlas:
            parsed = urllib.parse.urlsplit(str(atlas))
            query = urllib.parse.parse_qs(parsed.query)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "globalgrid2050.com"
                or parsed.path != "/repd_grid_atlasv8/"
                or query.get("repd_ref") != [ref]
            ):
                raise RuntimeError(f"Company Atlas identity link failed: {label}/{ref}")


def read_logical_cartridge(root: Path, logical_name: str, entry: dict) -> tuple[list[dict], dict]:
    if (
        not isinstance(entry, dict)
        or set(entry) != LOGICAL_ENTRY_KEYS
        or entry.get("declared_key") != DECLARED_KEY
        or entry.get("shard_policy") != SHARD_POLICY
        or entry.get("records") != entry.get("distinct_keys")
        or type(entry.get("records")) is not int
        or type(entry.get("distinct_keys")) is not int
        or entry.get("records", 0) < 1
        or not isinstance(entry.get("record_universe_sha256"), str)
    ):
        raise RuntimeError(f"Logical cartridge declaration failed: {logical_name}")
    shards = entry.get("shards")
    if not isinstance(shards, list) or not shards:
        raise RuntimeError(f"Logical cartridge has no shards: {logical_name}")
    records: list[dict] = []
    total_bytes = 0
    previous_last = None
    for ordinal, receipt in enumerate(shards):
        if (
            not isinstance(receipt, dict)
            or set(receipt) != SHARD_RECEIPT_KEYS
            or receipt.get("ordinal") != ordinal
            or type(receipt.get("ordinal")) is not int
            or type(receipt.get("rows")) is not int
            or receipt.get("rows", 0) < 1
        ):
            raise RuntimeError(f"Shard ordinals must be contiguous and nonempty: {logical_name}/{ordinal}")
        path = safe_shard_path(root, logical_name, ordinal, receipt.get("path"))
        size = path.stat().st_size
        total_bytes += size
        if (
            size > SHARD_TARGET_BYTES
            or size > MAXIMUM_FILE_BYTES
            or receipt.get("bytes") != size
            or receipt.get("sha256") != digest(path)
        ):
            raise RuntimeError(f"Shard physical receipt failed: {logical_name}/{ordinal}")
        payload = json.loads(path.read_text())
        shard_records = payload.get("records")
        if (
            {key: value for key, value in payload.items() if key != "records"} != shard_common(logical_name, ordinal)
            or not isinstance(shard_records, list)
            or len(shard_records) != receipt.get("rows")
        ):
            raise RuntimeError(f"Shard payload/rights contract failed: {logical_name}/{ordinal}")
        if path.read_bytes() != render_shard(logical_name, ordinal, shard_records):
            raise RuntimeError(f"Shard canonical byte/LF contract failed: {logical_name}/{ordinal}")
        shard_hash = record_digest(shard_records)
        first = shard_records[0]["company_number"]
        last = shard_records[-1]["company_number"]
        if (
            receipt.get("first_company_number") != first
            or receipt.get("last_company_number") != last
            or receipt.get("record_universe_sha256") != shard_hash
            or (previous_last is not None and first <= previous_last)
        ):
            raise RuntimeError(f"Shard semantic/range receipt failed: {logical_name}/{ordinal}")
        previous_last = last
        for record in shard_records:
            validate_company_record(record, f"{logical_name}/{record['company_number']}")
        records.extend(shard_records)
    union_hash = record_digest(records)
    if (
        len(records) != entry.get("records")
        or len(records) != sum(int(row["rows"]) for row in shards)
        or union_hash != entry.get("record_universe_sha256")
    ):
        raise RuntimeError(f"Logical ordered union failed: {logical_name}")
    expected_groups, expected_union_hash = partition_records(logical_name, records)
    if len(expected_groups) != len(shards) or expected_union_hash != union_hash:
        raise RuntimeError(f"Logical greedy shard closure failed: {logical_name}")
    for receipt, (group, encoded, predicted_size) in zip(shards, expected_groups):
        if (
            receipt["rows"] != len(group)
            or receipt["first_company_number"] != group[0]["company_number"]
            or receipt["last_company_number"] != group[-1]["company_number"]
            or receipt["bytes"] != predicted_size
            or receipt["record_universe_sha256"] != encoded_record_digest(group, encoded)
        ):
            raise RuntimeError(f"Logical greedy shard closure failed: {logical_name}")
    return records, {
        "shards": len(shards),
        "shard_receipts": copy.deepcopy(shards),
        "records": len(records),
        "distinct_keys": len(records),
        "bytes": total_bytes,
        "record_universe_sha256": union_hash,
    }


def canonical_company_records(root: Path, manifest: dict) -> tuple[list[dict], dict]:
    cartridges = manifest.get("cartridges")
    if not isinstance(cartridges, dict) or set(cartridges) != EXPECTED_CARTRIDGES:
        raise RuntimeError("Logical cartridge closure is unexpected")
    canonical: dict[str, str] = {}
    records_by_number: dict[str, dict] = {}
    metrics = {}
    for logical_name in sorted(EXPECTED_CARTRIDGES):
        records, metrics[logical_name] = read_logical_cartridge(root, logical_name, cartridges[logical_name])
        for record in records:
            number = record["company_number"]
            serialised = canonical_json(record)
            if number in canonical and canonical[number] != serialised:
                raise RuntimeError(f"Cross-cartridge record drift: {number}")
            canonical[number] = serialised
            records_by_number[number] = record
    if (
        not records_by_number
        or type(manifest.get("companies")) is not int
        or len(records_by_number) != manifest.get("companies")
    ):
        raise RuntimeError("Distinct sharded union does not equal manifest companies")
    return [records_by_number[number] for number in sorted(records_by_number)], metrics


def copy_evidence(
    output: Path,
    plan_path: Path,
    receipts_root: Path,
    reports_root: Path,
    receipts: list[dict],
    extractions: list[dict],
    rest_evidence_path: Path,
    basic_report_path: Path,
) -> list[dict]:
    evidence_root = output / "evidence"
    evidence_root.mkdir()
    sources = [
        ("download-plan.json", plan_path),
        ("rest-api.json", rest_evidence_path),
        ("basic-validation.json", basic_report_path),
    ]
    for receipt in receipts:
        source = next(
            path
            for path in receipts_root.rglob("receipt-*.json")
            if json.loads(path.read_text()).get("index") == receipt["index"]
        )
        sources.append((f"receipt-{receipt['index']}.json", source))
    for index, report in enumerate(extractions):
        source = next(
            path
            for path in reports_root.rglob("extraction-*.json")
            if json.loads(path.read_text()).get("archive_filename") == report["archive_filename"]
        )
        sources.append((f"extraction-{index}.json", source))
    result = []
    for filename, source in sources:
        target = evidence_root / filename
        shutil.copyfile(source, target)
        result.append({"path": f"evidence/{filename}", "bytes": target.stat().st_size, "sha256": digest(target)})
    return result


def build_analytical_datasets(root: Path, records: list[dict]) -> dict:
    company_rows = ENGINE.company_rows(records)
    relationship_rows = ENGINE.relationship_rows(records)
    ENGINE.write_parquet(root / COMPANY_PARQUET, COMPANY_COLUMNS, company_rows, ("company_number",))
    ENGINE.write_parquet(
        root / RELATIONSHIP_PARQUET,
        RELATIONSHIP_COLUMNS,
        relationship_rows,
        ("company_number", "repd_ref", "match_type"),
    )
    companies = ENGINE.audit_parquet(
        root / COMPANY_PARQUET,
        COMPANY_COLUMNS,
        ("company_number",),
        "record_json",
        company_rows,
    )
    relationships = ENGINE.audit_parquet(
        root / RELATIONSHIP_PARQUET,
        RELATIONSHIP_COLUMNS,
        ("company_number", "repd_ref", "match_type"),
        "relationship_json",
        relationship_rows,
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
                **companies,
                "grain": "one row per distinct company in the candidate cartridge union",
            },
            "company_repd_candidates": {
                **relationships,
                "grain": "one evidence-qualified REPD candidate relationship",
                "identity_posture": "CANDIDATE_RELATIONSHIP_ONLY_NOT_PRIMARY_PROJECT_BINDING",
            },
        },
    }


def verify_evidence(root: Path, manifest: dict, errors: list[str]) -> None:
    inputs = manifest.get("inputs", {})
    evidence = manifest.get("evidence", [])
    expected_paths = [
        "evidence/download-plan.json",
        "evidence/rest-api.json",
        "evidence/basic-validation.json",
        *(f"evidence/receipt-{index}.json" for index in range(4)),
        *(f"evidence/extraction-{index}.json" for index in range(3)),
    ]
    if (
        not isinstance(evidence, list)
        or len(evidence) != 10
        or [row.get("path") for row in evidence] != expected_paths
    ):
        errors.append("evidence closure")
        return
    for receipt in evidence:
        path = root / str(receipt.get("path", "__missing__"))
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"path", "bytes", "sha256"}
            or not path.is_file()
            or path.is_symlink()
            or receipt.get("bytes") != path.stat().st_size
            or receipt.get("sha256") != digest(path)
        ):
            errors.append(f"evidence receipt: {receipt.get('path')}")
    copied_plan = root / "evidence/download-plan.json"
    plan = LEGACY.load_plan(copied_plan)
    if (
        digest(copied_plan) != EXPECTED_PLAN_SHA256
        or inputs.get("download_plan_sha256") != EXPECTED_PLAN_SHA256
        or plan.get("planned_at") != FIXED_GENERATED_AT
    ):
        errors.append("source-pinned archive plan")
    rest_path = root / "evidence/rest-api.json"
    rest = LEGACY.load_rest_evidence(rest_path)
    if digest(rest_path) != EXPECTED_REST_EVIDENCE_SHA256:
        errors.append("deterministic REST non-use evidence")
    if inputs.get("optional_rest") != {
        "enabled": rest["enabled"],
        "status": rest["status"],
        "evidence_sha256": EXPECTED_REST_EVIDENCE_SHA256,
    }:
        errors.append("optional REST input receipt")
    plan["_path"] = str(copied_plan)
    copied_receipts = LEGACY.collect_receipts(root / "evidence", plan)
    if any(row.get("retrieved_at") != FIXED_GENERATED_AT for row in copied_receipts):
        errors.append("acquisition receipt timestamp closure")
    basic_receipt = next(row for row in copied_receipts if row.get("kind") == "basic")
    basic_report_path = root / "evidence/basic-validation.json"
    basic_report = LEGACY.load_basic_report(basic_report_path, basic_receipt)
    if (
        inputs.get("basic_archive_sha256") != basic_receipt.get("sha256")
        or inputs.get("basic_validation_sha256") != digest(basic_report_path)
        or basic_report.get("completed_at") != FIXED_GENERATED_AT
    ):
        errors.append("basic archive input receipt")
    account_receipts = {row.get("filename"): row for row in copied_receipts if row.get("kind") == "accounts"}
    extraction_archives = set()
    for index in range(3):
        report = json.loads((root / f"evidence/extraction-{index}.json").read_text())
        receipt = account_receipts.get(report.get("archive_filename"))
        if (
            not receipt
            or report.get("schema") != "companies-house-bounded-extraction-report-v1"
            or report.get("generation") != GENERATION
            or report.get("status") != "PASS"
            or report.get("archive_sha256") != receipt.get("sha256")
            or report.get("archive_bytes") != receipt.get("bytes")
            or not isinstance(report.get("records"), int)
            or report.get("records", 0) < 1
            or not isinstance(report.get("parse_error_rate"), (int, float))
            or report.get("parse_error_rate", 1) > 0.02
            or report.get("completed_at") != FIXED_GENERATED_AT
            or not re.fullmatch(r"[0-9a-f]{64}", str(report.get("output_sha256", "")))
        ):
            errors.append(f"extraction {index} receipt")
        extraction_archives.add(report.get("archive_filename"))
    if extraction_archives != set(account_receipts):
        errors.append("extraction archive closure")
    if plan.get("total_bytes", 12_000_000_001) > 12_000_000_000:
        errors.append("download plan ceiling")


def verify_repd_input(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"files", "sha256", "projects"}:
        return False
    files = value.get("files")
    if not isinstance(files, list) or [row.get("path") for row in files if isinstance(row, dict)] != EXPECTED_REPD_PATHS:
        return False
    for receipt in files:
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"path", "bytes", "sha256"}
            or type(receipt.get("bytes")) is not int
            or receipt.get("bytes", 0) < 1
            or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256", "")))
        ):
            return False
    closure = hashlib.sha256(
        "".join(f"{row['path']}\0{row['sha256']}\n" for row in files).encode("utf-8")
    ).hexdigest()
    return (
        closure == EXPECTED_REPD_CLOSURE_SHA256
        and value.get("sha256") == EXPECTED_REPD_CLOSURE_SHA256
        and sum(row["bytes"] for row in files) == EXPECTED_REPD_TOTAL_BYTES
        and value.get("projects") == EXPECTED_REPD_PROJECTS
    )


def resource_totals(root: Path) -> dict:
    files = []
    categories = {
        "manifest": 0,
        "json_shards": 0,
        "evidence": 0,
        "company_parquet": 0,
        "relationship_parquet": 0,
        "duckdb_audit": 0,
        "other": 0,
    }
    logical_cartridges = {name: 0 for name in sorted(EXPECTED_CARTRIDGES)}
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
            category = "other"
            if relative == "manifest-v2.json":
                category = "manifest"
            elif relative == COMPANY_PARQUET:
                category = "company_parquet"
            elif relative == RELATIONSHIP_PARQUET:
                category = "relationship_parquet"
            elif relative == AUDIT_PATH:
                category = "duckdb_audit"
            elif relative.startswith("evidence/"):
                category = "evidence"
            elif relative.startswith("cartridges/"):
                category = "json_shards"
                parts = relative.split("/")
                if len(parts) == 3 and parts[1] in logical_cartridges:
                    logical_cartridges[parts[1]] += size
            categories[category] += size
            files.append({"path": relative, "bytes": size, "category": category})
    total = sum(row["bytes"] for row in files)
    return {
        "maximum_file_bytes": MAXIMUM_FILE_BYTES,
        "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
        "total_bytes": total,
        "file_count": len(files),
        "within_file_ceiling": all(row["bytes"] <= MAXIMUM_FILE_BYTES for row in files),
        "within_total_ceiling": total <= MAXIMUM_TOTAL_BYTES,
        "category_bytes": categories,
        "logical_cartridge_bytes": logical_cartridges,
        "files": files,
    }


def verify(root: Path) -> dict:
    errors: list[str] = []
    companies = 0
    total_bytes = 0
    cartridge_metrics = {}
    try:
        manifest_path = root / "manifest-v2.json"
        manifest = json.loads(manifest_path.read_text())
        if set(manifest) != MANIFEST_KEYS or manifest_path.read_bytes() != (
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8"):
            errors.append("manifest key/canonical byte closure")
        if (
            manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("generation") != GENERATION
            or manifest.get("generated_at") != FIXED_GENERATED_AT
            or manifest.get("deployment_state") != "not-authorised"
            or manifest.get("promotion_eligible") is not False
        ):
            errors.append("candidate identity/quarantine")
        if (
            manifest.get("coverage") != COVERAGE
            or manifest.get("threshold_gbp") != 10_000_000
            or manifest.get("financial_currency") != "GBP"
            or manifest.get("privacy") != PRIVACY
            or manifest.get("licence") != LEGACY.OGL
        ):
            errors.append("coverage/privacy/licence")
        if (
            manifest.get("usage_context") != "NON_COMMERCIAL_OPEN_SOURCE"
            or manifest.get("source_licence") != LEGACY.OGL
            or manifest.get("source_licences") != ENGINE.MATERIALISED_SOURCES
            or manifest.get("source_rights_are_distinct_from_usage_context") is not True
            or manifest.get("field_lineage") != ENGINE.FIELD_LINEAGE
        ):
            errors.append("usage context/source rights/field lineage")
        if manifest.get("data_discipline") != DATA_DISCIPLINE:
            errors.append("data discipline")
        if manifest.get("publication") != PUBLICATION:
            errors.append("publication boundary")
        inputs = manifest.get("inputs", {})
        if (
            not isinstance(inputs, dict)
            or set(inputs) != INPUT_KEYS
            or inputs.get("companies_base_commit") != BASE_COMMIT
            or inputs.get("pipelinenews_commit") != ENGINE.PIPELINENEWS_COMMIT
            or not LEGACY.COMMIT_SHA.fullmatch(str(inputs.get("generation_source_commit", "")))
            or not verify_repd_input(inputs.get("repd"))
            or not re.fullmatch(r"[0-9a-f]{64}", str(inputs.get("accounts_latest_sha256", "")))
            or type(inputs.get("accounts_latest_records")) is not int
            or inputs.get("accounts_latest_records", 0) < 1
        ):
            errors.append("input commit boundary")
        if inputs.get("repd_runtime_read") != {
            "repository": "Ventusltd/pipelinenews",
            "commit": ENGINE.PIPELINENEWS_COMMIT,
            "path": "data/projects",
            "mode": "read-only sparse checkout",
            "foreign_repository_files_committed": False,
            "foreign_data_materialised": True,
        }:
            errors.append("REPD runtime provenance")
        if inputs.get("news") != {"included": False, "identity_policy": "annotation-only"}:
            errors.append("news identity boundary")
        verify_evidence(root, manifest, errors)
        records, cartridge_metrics = canonical_company_records(root, manifest)
        companies = len(records)
        company_rows = ENGINE.company_rows(records)
        relationship_rows = ENGINE.relationship_rows(records)
        company_audit = ENGINE.audit_parquet(
            root / COMPANY_PARQUET,
            COMPANY_COLUMNS,
            ("company_number",),
            "record_json",
            company_rows,
        )
        relationship_audit = ENGINE.audit_parquet(
            root / RELATIONSHIP_PARQUET,
            RELATIONSHIP_COLUMNS,
            ("company_number", "repd_ref", "match_type"),
            "relationship_json",
            relationship_rows,
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
        if (
            json.loads(audit_path.read_text()) != expected_audit
            or audit_path.read_bytes()
            != (json.dumps(expected_audit, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        ):
            errors.append("stored DuckDB audit semantics")
        audit_receipt = {"path": AUDIT_PATH, "bytes": audit_path.stat().st_size, "sha256": digest(audit_path)}
        if manifest.get("audits") != [audit_receipt]:
            errors.append("DuckDB audit receipt")
        shard_paths = {
            shard["path"]
            for entry in manifest.get("cartridges", {}).values()
            for shard in entry.get("shards", [])
        }
        expected_paths = {"manifest-v2.json", COMPANY_PARQUET, RELATIONSHIP_PARQUET, AUDIT_PATH, *shard_paths}
        expected_paths.update(str(receipt["path"]) for receipt in manifest.get("evidence", []))
        all_nodes = list(root.rglob("*"))
        if any(path.is_symlink() for path in all_nodes):
            errors.append("candidate symlink closure")
        actual_paths = {path.relative_to(root).as_posix() for path in all_nodes if path.is_file()}
        if actual_paths != expected_paths:
            errors.append("candidate physical file closure")
        if any(path.suffix.lower() in {".zip", ".ndjson"} for path in all_nodes if path.is_file()):
            errors.append("raw/transport file leaked into candidate")
        oversized = []
        for path in all_nodes:
            if not path.is_file():
                continue
            size = path.stat().st_size
            total_bytes += size
            if size > MAXIMUM_FILE_BYTES:
                oversized.append(f"{path.relative_to(root).as_posix()}={size}")
        if oversized:
            errors.append(f"published file byte ceiling: {oversized}")
        if total_bytes > MAXIMUM_TOTAL_BYTES:
            totals = {name: row.get("bytes", 0) for name, row in cartridge_metrics.items()}
            parquet_totals = {
                COMPANY_PARQUET: (root / COMPANY_PARQUET).stat().st_size,
                RELATIONSHIP_PARQUET: (root / RELATIONSHIP_PARQUET).stat().st_size,
            }
            errors.append(
                f"candidate total byte ceiling: total={total_bytes}, cartridge_bytes={totals}, parquet_bytes={parquet_totals}"
            )
        outputs = manifest.get("candidate_outputs", {})
        if outputs != {
            "logical_json_cartridges": len(EXPECTED_CARTRIDGES),
            "json_shard_files": len(shard_paths),
            "partition_scheme": PARTITION_SCHEME,
            "shard_target_bytes": SHARD_TARGET_BYTES,
            "maximum_published_file_bytes": MAXIMUM_FILE_BYTES,
            "maximum_candidate_total_bytes": MAXIMUM_TOTAL_BYTES,
            "company_parquet": COMPANY_PARQUET,
            "relationship_parquet": RELATIONSHIP_PARQUET,
            "duckdb_audit": AUDIT_PATH,
            "exact_candidate_file_closure_enforced": True,
        }:
            errors.append("candidate output declaration")
    except Exception as exc:
        errors.append(str(exc))
    resources = resource_totals(root)
    total_bytes = resources["total_bytes"]
    if not resources["within_file_ceiling"] and not any("published file byte ceiling" in row for row in errors):
        errors.append("published file byte ceiling")
    if not resources["within_total_ceiling"] and not any("candidate total byte ceiling" in row for row in errors):
        errors.append(
            "candidate total byte ceiling: "
            f"total={total_bytes}, logical={resources['logical_cartridge_bytes']}, "
            f"categories={resources['category_bytes']}"
        )
    return {
        "schema": "companies-house-bounded-verification-v5",
        "generation": GENERATION,
        "status": "FAIL" if errors else "PASS",
        "companies": companies,
        "bytes_monitor": total_bytes,
        "cartridges": cartridge_metrics,
        "resource_totals": resources,
        "errors": errors[:100],
    }


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
    if output.exists():
        raise RuntimeError("Candidate target must be absent before direct sealing")
    if not LEGACY.COMMIT_SHA.fullmatch(source_commit):
        raise RuntimeError("Generation source commit is not an exact SHA")
    if digest(plan_path) != EXPECTED_PLAN_SHA256:
        raise RuntimeError("The source-pinned archive plan drifted")
    if digest(rest_evidence_path) != EXPECTED_REST_EVIDENCE_SHA256:
        raise RuntimeError("The deterministic REST non-use evidence drifted")
    plan = LEGACY.load_plan(plan_path)
    plan["_path"] = str(plan_path)
    receipts = LEGACY.collect_receipts(receipts_root, plan)
    extractions = LEGACY.collect_extractions(reports_root, receipts)
    basic_receipt = next(row for row in receipts if row["kind"] == "basic")
    rest_evidence = LEGACY.load_rest_evidence(rest_evidence_path)
    LEGACY.load_basic_report(basic_report_path, basic_receipt)
    basic_archives = sorted(basic_root.glob("*.zip"))
    if len(basic_archives) != 1:
        raise RuntimeError("Compiler input must contain exactly one basic-company ZIP")
    basic_archive = basic_archives[0]
    if (
        basic_archive.name != basic_receipt["filename"]
        or basic_archive.stat().st_size != basic_receipt["bytes"]
        or digest(basic_archive) != basic_receipt["sha256"]
    ):
        raise RuntimeError("Basic-company compiler input drifted from its acquisition receipt")
    account_records = 0
    account_numbers = set()
    with accounts_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            number = str(row.get("company_number", ""))
            if not ENGINE.COMPANY_NUMBER.fullmatch(number) or number in account_numbers:
                raise RuntimeError("Merged accounts input contains an invalid or duplicate company number")
            account_numbers.add(number)
            account_records += 1
    if not account_records:
        raise RuntimeError("Merged accounts input is empty")
    projects, repd_manifest = LEGACY.repd_closure(repd_root)
    raw_manifest_path = raw_root / "manifest-v1.json"
    raw_manifest = json.loads(raw_manifest_path.read_text())
    if (
        set(raw_manifest) != {"schema", "snapshot_id", "refresh_policy", "threshold_gbp", "files", "privacy"}
        or raw_manifest.get("schema") != "companies-house-manifest-v1"
        or raw_manifest.get("snapshot_id") != GENERATION
        or raw_manifest.get("refresh_policy") != "annual-overwrite"
        or raw_manifest.get("threshold_gbp") != 10_000_000
        or raw_manifest.get("privacy")
        != {"directors": False, "individual_psc": False, "residential_addresses": False}
    ):
        raise RuntimeError("Raw compiler manifest contract failed")
    raw_files = raw_manifest.get("files", {})
    if set(raw_files) != EXPECTED_CARTRIDGES:
        raise RuntimeError("Compiler cartridge closure is unexpected")
    raw_expected_paths = {"manifest-v1.json", *(f"{name}-v1.json" for name in EXPECTED_CARTRIDGES)}
    raw_nodes = list(raw_root.rglob("*"))
    if (
        any(path.is_symlink() for path in raw_nodes)
        or {path.relative_to(raw_root).as_posix() for path in raw_nodes if path.is_file()} != raw_expected_paths
    ):
        raise RuntimeError("Raw compiler physical closure failed")

    output.mkdir(parents=True, exist_ok=False)
    cartridges = {}
    canonical: dict[str, str] = {}
    records_by_number: dict[str, dict] = {}
    for logical_name in sorted(EXPECTED_CARTRIDGES):
        raw_receipt = raw_files[logical_name]
        expected_source_name = f"{logical_name}-v1.json"
        if (
            not isinstance(raw_receipt, dict)
            or set(raw_receipt) != {"path", "records", "sha256"}
            or raw_receipt.get("path") != expected_source_name
            or type(raw_receipt.get("records")) is not int
            or raw_receipt.get("records", 0) < 1
            or not re.fullmatch(r"[0-9a-f]{64}", str(raw_receipt.get("sha256", "")))
        ):
            raise RuntimeError(f"Raw compiler logical receipt failed: {logical_name}")
        source = raw_root / expected_source_name
        payload = json.loads(source.read_text())
        raw_records = payload.get("records")
        if (
            set(payload) != {"schema", "snapshot_id", "generated_at", "records"}
            or payload.get("schema") != "companies-house-cartridge-v1"
            or payload.get("snapshot_id") != GENERATION
            or not isinstance(payload.get("generated_at"), str)
            or not isinstance(raw_records, list)
            or digest(source) != raw_receipt.get("sha256")
            or len(raw_records) != raw_receipt.get("records")
        ):
            raise RuntimeError(f"Raw compiler receipt failed: {logical_name}")
        sealed_records = []
        seen = set()
        for raw_record in raw_records:
            number = str(raw_record.get("company_number", ""))
            if not ENGINE.COMPANY_NUMBER.fullmatch(number) or number in seen:
                raise RuntimeError(f"Invalid or duplicate company number: {logical_name}/{number}")
            seen.add(number)
            record = LEGACY.enrich(raw_record, projects)
            serialised = canonical_json(record)
            if number in canonical and canonical[number] != serialised:
                raise RuntimeError(f"Cross-cartridge record drift: {number}")
            canonical[number] = serialised
            records_by_number[number] = record
            sealed_records.append(record)
        sealed_records.sort(key=lambda row: row["company_number"])
        cartridges[logical_name] = write_logical_cartridge(output, logical_name, sealed_records)
    records = [records_by_number[number] for number in sorted(records_by_number)]
    evidence = copy_evidence(
        output,
        plan_path,
        receipts_root,
        reports_root,
        receipts,
        extractions,
        rest_evidence_path,
        basic_report_path,
    )
    audit = build_analytical_datasets(output, records)
    audit_path = output / AUDIT_PATH
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "promotion_eligible": False,
        "coverage": COVERAGE,
        "threshold_gbp": 10_000_000,
        "financial_currency": "GBP",
        "inputs": {
            "companies_base_commit": BASE_COMMIT,
            "generation_source_commit": source_commit,
            "pipelinenews_commit": ENGINE.PIPELINENEWS_COMMIT,
            "repd": repd_manifest,
            "repd_runtime_read": {
                "repository": "Ventusltd/pipelinenews",
                "commit": ENGINE.PIPELINENEWS_COMMIT,
                "path": "data/projects",
                "mode": "read-only sparse checkout",
                "foreign_repository_files_committed": False,
                "foreign_data_materialised": True,
            },
            "download_plan_sha256": EXPECTED_PLAN_SHA256,
            "basic_archive_sha256": digest(basic_archive),
            "accounts_latest_sha256": digest(accounts_path),
            "accounts_latest_records": account_records,
            "optional_rest": {
                "enabled": rest_evidence["enabled"],
                "status": rest_evidence["status"],
                "evidence_sha256": EXPECTED_REST_EVIDENCE_SHA256,
            },
            "basic_validation_sha256": digest(basic_report_path),
            "news": {"included": False, "identity_policy": "annotation-only"},
        },
        "cartridges": cartridges,
        "evidence": evidence,
        "companies": len(records),
        "privacy": PRIVACY,
        "licence": LEGACY.OGL,
        "usage_context": "NON_COMMERCIAL_OPEN_SOURCE",
        "source_licence": LEGACY.OGL,
        "source_licences": ENGINE.MATERIALISED_SOURCES,
        "source_rights_are_distinct_from_usage_context": True,
        "field_lineage": ENGINE.FIELD_LINEAGE,
        "data_discipline": DATA_DISCIPLINE,
        "publication": PUBLICATION,
        "analytical_dataset": audit["datasets"]["companies"],
        "relationship_dataset": audit["datasets"]["company_repd_candidates"],
        "audits": [{"path": AUDIT_PATH, "bytes": audit_path.stat().st_size, "sha256": digest(audit_path)}],
        "candidate_outputs": {
            "logical_json_cartridges": len(EXPECTED_CARTRIDGES),
            "json_shard_files": sum(len(row["shards"]) for row in cartridges.values()),
            "partition_scheme": PARTITION_SCHEME,
            "shard_target_bytes": SHARD_TARGET_BYTES,
            "maximum_published_file_bytes": MAXIMUM_FILE_BYTES,
            "maximum_candidate_total_bytes": MAXIMUM_TOTAL_BYTES,
            "company_parquet": COMPANY_PARQUET,
            "relationship_parquet": RELATIONSHIP_PARQUET,
            "duckdb_audit": AUDIT_PATH,
            "exact_candidate_file_closure_enforced": True,
        },
    }
    manifest_path = output / "manifest-v2.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result = verify(output)
    if result["status"] != "PASS":
        raise RuntimeError(f"Direct sharded candidate verification failed: {result['errors']!r}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seal", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--repd", type=Path)
    parser.add_argument("--basic", type=Path)
    parser.add_argument("--accounts", type=Path)
    parser.add_argument("--rest-evidence", type=Path)
    parser.add_argument("--basic-report", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    summary: dict
    try:
        if args.seal:
            required = [
                args.output,
                args.plan,
                args.receipts,
                args.reports,
                args.repd,
                args.basic,
                args.accounts,
                args.rest_evidence,
                args.basic_report,
                args.source_commit,
            ]
            if any(value is None for value in required):
                raise RuntimeError("Seal mode requires every frozen bulk, evidence, REPD and source input")
            seal(
                args.input,
                args.output,
                args.plan,
                args.receipts,
                args.reports,
                args.repd,
                args.basic,
                args.accounts,
                args.rest_evidence,
                args.basic_report,
                args.source_commit,
            )
            summary = verify(args.output)
        else:
            summary = verify(args.input)
    except Exception as exc:
        if args.seal and args.output is not None and args.output.exists():
            summary = verify(args.output)
            summary["status"] = "FAIL"
            summary["errors"] = [*summary.get("errors", []), f"seal: {exc}"][:100]
        else:
            summary = {
                "schema": "companies-house-bounded-verification-v5",
                "generation": GENERATION,
                "status": "FAIL",
                "companies": 0,
                "bytes_monitor": 0,
                "cartridges": {},
                "resource_totals": resource_totals(args.output if args.seal and args.output else args.input),
                "errors": [str(exc)],
            }
    rendered = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered)
    stream = sys.stdout if summary.get("status") == "PASS" else sys.stderr
    print(rendered, end="", file=stream)
    return 0 if summary.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
