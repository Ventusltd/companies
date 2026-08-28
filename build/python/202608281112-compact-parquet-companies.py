#!/usr/bin/env python3
"""Build and verify the relationship/report-only Companies candidate."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

GENERATION = "202608272155"
RESUME_GENERATION = "202608281112"
FIXED_GENERATED_AT = "2026-08-27T21:55:00Z"
DUCKDB_VERSION = "1.3.2"
EXPECTED_SELECTED_COMPANIES = 294_904
MAXIMUM_FILE_BYTES = 20_000_000
MAXIMUM_TOTAL_BYTES = 30_000_000
SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_ACQUISITION_RUN_ID = 33123064395
EXPECTED_ACQUISITION_SOURCE_COMMIT = "72c4e033f536d793e1a357b108b05fbac43e8d09"
EXPECTED_MAIN_PARENT_COMMIT = "49fa8deaac277794251eb808a4747b09a35cda3c"
SUPERSEDED_FAILED_RUN_ID = 33149009261
EXPECTED_PIPELINENEWS_COMMIT = "35f35ada161223fb3ee19e525664ee7f17df1ddd"
FILING_TRUTH_CAVEAT = (
    "Accounts facts are public filing facts and are not a credit or bankability score."
)
RELATIONSHIP_TRUTH_CAVEAT = (
    "All company–REPD rows are name-evidence candidates, never confirmed ownership or project identity."
)
RETAINED_ARTIFACTS = [
    {
        "name": "companies-plan-202608272155-33123064395",
        "digest": "sha256:5458cb47d45107be3468472da15d02f18e0b5c0992f10c594af6897f2aea8aaa",
    },
    {
        "name": "accounts-202608272155-33123064395-0",
        "digest": "sha256:73cfb68813a6524b23eee4ae45504d3a2bed2f0035116cc0efa049c2b62d2b1c",
    },
    {
        "name": "accounts-202608272155-33123064395-1",
        "digest": "sha256:3da269b26136b8ca6b32e8200ae19527d8fb83f7836a661685fab78662047682",
    },
    {
        "name": "accounts-202608272155-33123064395-2",
        "digest": "sha256:4f37aa9ef85a32270d297cfbcd37606c5cad04b25af3db0c881a8324a0ccaf03",
    },
]
PUBLICATION = {
    "candidate_branch": "candidate/202608272155-compact",
    "candidate_path": "data/candidates/202608272155-compact/",
    "stable_path": "data/current/",
    "stable_path_must_change": False,
    "pages_must_change": False,
    "promotion_eligible": False,
}
MANIFEST_KEYS = frozenset(
    {
        "schema",
        "generation",
        "resume_generation",
        "generated_at",
        "source_commit",
        "supersedes_failed_run_id",
        "deployment_state",
        "promotion_eligible",
        "coverage",
        "threshold_gbp",
        "financial_currency",
        "basic_company_rows_scanned",
        "companies_selected",
        "companies_with_repd_candidates",
        "company_repd_candidates",
        "solar_company_repd_relationships",
        "privacy",
        "usage_context",
        "source_licences",
        "source_rights_are_distinct_from_usage_context",
        "filing_truth_caveat",
        "relationship_truth_caveat",
        "publication",
        "inputs",
        "datasets",
        "report",
        "evidence",
        "audit",
        "output_policy",
    }
)
INPUT_KEYS = frozenset(
    {
        "acquisition_run_id",
        "acquisition_source_commit",
        "retained_artifacts",
        "source_parent_commit",
        "companies_base_commit",
        "pipelinenews_commit",
        "download_plan_sha256",
        "basic_archive_sha256",
        "basic_validation_sha256",
        "accounts_latest_sha256",
        "accounts_latest_records",
        "repd",
        "repd_runtime_read",
        "optional_rest",
        "news",
    }
)

ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = Path("build/python/202608272155-verify-companies-house-candidate.py")
COMPILER_PATH = Path("build/python/202608262245-compile-companies-house.py")
CONTRACT_PATH = Path("contracts/202608281112-compact-parquet-companies.json")
RELATIONSHIP_PARQUET = Path("company-repd-relationships-v1.parquet")
SOLAR_PARQUET = Path("solar-company-repd-relationships-v1.parquet")
REPORT_PATH = Path("relationship-report-v1.json")
AUDIT_PATH = Path("relationship-parquet-audit-v1.json")
MANIFEST_PATH = Path("manifest-compact-v1.json")

SOURCE_BOUNDARY = (
    ".github/workflows/202608281112-compact-parquet-companies-candidate.yml",
    "README.md",
    "build/python/202608281112-compact-parquet-companies.py",
    "contracts/202608281112-compact-parquet-companies.json",
    "tests/test_202608281112_compact_parquet_companies.py",
)

DEPENDENCY_SHA256 = {
    "build/python/202608262245-compile-companies-house.py": "f7e5ebfb6ddc885b3b2a05deeedff5bf4b4f808b78ef62974baa7025487dcc90",
    "build/python/202608262245-merge-accounts.py": "d6ff055510c9b42a1710d6f4cdd22288d7334d20e3ee4190be13ff5c219c2e2e",
    "build/python/202608272155-download-planned-archive.py": "d4f8d4b3d98e3c8df69cf668743320b18c177742113c7b331ab12f4dd9e78387",
    "build/python/202608272155-extract-bounded-accounts.py": "717165dbfa9edaf16cf0a06b83f31153faabe1daf48960a3afbcd3b67a958823",
    "build/python/202608272155-verify-companies-house-candidate.py": "b81e200a44a2f293e71535a07ee6fcca54fca25915524af8ac1f28ea44b397fd",
    "build/python/202608272120-verify-companies-house-candidate.py": "d1e1cb3871fca3f6cfab62d60b763d62573935ad3c4d592842ffce106f9fd3b5",
    "build/python/202608272035-verify-companies-house-candidate.py": "5c3a3af787520bdb7936005d7247fb6060f36fae981f78c587ff35d6a55343db",
    "build/python/202608272016-verify-companies-house-candidate.py": "b37c634d3369c8110712aaf36cffb5df303d4f93eb64b79bae224bdc69441033",
    "build/python/202608271507-verify-companies-house-candidate.py": "22e8393dc55606e3f24381ed0fad0bf0ae545c51127a7a68c90f65e3a8558f02",
}

RELATIONSHIP_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("generation", "VARCHAR", False),
    ("relationship_repository", "VARCHAR", False),
    ("relationship_repository_commit", "VARCHAR", False),
    ("company_number", "VARCHAR", False),
    ("company_name", "VARCHAR", False),
    ("company_register_url", "VARCHAR", False),
    ("repd_repository", "VARCHAR", False),
    ("repd_commit", "VARCHAR", False),
    ("repd_path", "VARCHAR", False),
    ("repd_ref", "VARCHAR", False),
    ("evidence_class", "VARCHAR", False),
    ("evidence_type", "VARCHAR", False),
    ("gg_project_id", "VARCHAR", False),
    ("project", "VARCHAR", True),
    ("operator", "VARCHAR", True),
    ("technology", "VARCHAR", False),
    ("capacity_mw", "DECIMAL(38,6)", True),
    ("status", "VARCHAR", True),
    ("latitude", "DOUBLE", True),
    ("longitude", "DOUBLE", True),
    ("atlas_url", "VARCHAR", True),
    ("relationship_sha256", "VARCHAR", False),
)
RELATIONSHIP_KEY = ("company_number", "repd_ref", "evidence_type")
REPD_TECHNOLOGIES = frozenset({"bess", "solar", "wind_offshore", "wind_onshore"})
EDGE_PAYLOAD_KEYS = frozenset(name for name, _type, _nullable in RELATIONSHIP_COLUMNS) - {
    "relationship_sha256"
}


def _early_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _assert_pinned_dependencies(root: Path) -> None:
    for relative, expected in DEPENDENCY_SHA256.items():
        path = root / relative
        if not path.is_file() or _early_digest(path) != expected:
            raise RuntimeError(f"Pinned dependency drifted before import: {relative}")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load pinned module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_assert_pinned_dependencies(ROOT)
BASE = load_module(ROOT / BASE_PATH, "companies_compact_base_202608281112")
COMPILER = load_module(ROOT / COMPILER_PATH, "companies_compact_selector_202608281112")
ENGINE = BASE.ENGINE
LEGACY = BASE.LEGACY


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def receipt(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
    }


def doctor(root: Path) -> dict[str, Any]:
    missing = [path for path in SOURCE_BOUNDARY if not (root / path).is_file()]
    if missing:
        raise RuntimeError(f"Source boundary is incomplete: {missing!r}")
    for relative, expected in DEPENDENCY_SHA256.items():
        path = root / relative
        if not path.is_file() or digest(path) != expected:
            raise RuntimeError(f"Pinned dependency drifted: {relative}")
    contract = load_json(root / CONTRACT_PATH)
    expected_contract_keys = {
        "schema",
        "generation",
        "resume_generation",
        "supersedes_failed_run_id",
        "owner",
        "purpose",
        "expected_companies_selected",
        "duckdb_version",
        "parquet_compression",
        "maximum_file_bytes",
        "maximum_total_bytes",
        "source_boundary",
        "dependency_sha256",
        "inputs",
        "grains",
        "relationship_schema",
        "solar_relationship_schema",
        "hard_gates",
        "outputs",
    }
    if (
        set(contract) != expected_contract_keys
        or contract.get("schema") != "companies-house-relationship-report-contract-v1"
        or contract.get("generation") != GENERATION
        or contract.get("resume_generation") != RESUME_GENERATION
        or contract.get("supersedes_failed_run_id") != SUPERSEDED_FAILED_RUN_ID
        or contract.get("owner") != "Ventusltd/companies"
        or contract.get("purpose")
        != (
            "Use ephemeral GitHub Actions compute to scan pinned Companies House inputs and "
            "retain only compact cross-repository relationship tables and an aggregate report."
        )
        or contract.get("duckdb_version") != DUCKDB_VERSION
        or contract.get("parquet_compression") != "ZSTD"
        or contract.get("source_boundary") != list(SOURCE_BOUNDARY)
        or contract.get("dependency_sha256") != DEPENDENCY_SHA256
        or contract.get("maximum_file_bytes") != MAXIMUM_FILE_BYTES
        or contract.get("maximum_total_bytes") != MAXIMUM_TOTAL_BYTES
        or contract.get("expected_companies_selected") != EXPECTED_SELECTED_COMPANIES
        or set(contract.get("inputs", {}))
        != {
            "acquisition_run_id",
            "acquisition_source_commit",
            "download_plan_sha256",
            "pipelinenews_commit",
            "retained_artifacts",
            "source_parent_commit",
        }
        or contract.get("inputs", {}).get("acquisition_run_id") != EXPECTED_ACQUISITION_RUN_ID
        or contract.get("inputs", {}).get("acquisition_source_commit")
        != EXPECTED_ACQUISITION_SOURCE_COMMIT
        or contract.get("inputs", {}).get("pipelinenews_commit")
        != EXPECTED_PIPELINENEWS_COMMIT
        or contract.get("inputs", {}).get("download_plan_sha256")
        != BASE.EXPECTED_PLAN_SHA256
        or contract.get("inputs", {}).get("retained_artifacts") != RETAINED_ARTIFACTS
        or contract.get("inputs", {}).get("source_parent_commit")
        != EXPECTED_MAIN_PARENT_COMMIT
        or contract.get("grains")
        != {
            RELATIONSHIP_PARQUET.as_posix(): {
                "declared_key": list(RELATIONSHIP_KEY),
                "evidence_class": "CANDIDATE",
                "grain": "one cross-repository candidate Company-REPD relationship",
                "identity_posture": "CANDIDATE_ONLY_NOT_CONFIRMED_OWNERSHIP",
            },
            SOLAR_PARQUET.as_posix(): {
                "declared_key": list(RELATIONSHIP_KEY),
                "evidence_class": "CANDIDATE",
                "grain": "one solar-filtered candidate Company-REPD relationship",
                "identity_posture": "CANDIDATE_ONLY_NOT_CONFIRMED_OWNERSHIP",
            },
        }
        or contract.get("outputs")
        != {
            "company_repd_candidates": RELATIONSHIP_PARQUET.as_posix(),
            "solar_company_repd_relationships": SOLAR_PARQUET.as_posix(),
            "report": REPORT_PATH.as_posix(),
            "audit": AUDIT_PATH.as_posix(),
            "manifest": MANIFEST_PATH.as_posix(),
        }
    ):
        raise RuntimeError("Compact Parquet contract drifted")
    expected_schema = [
        {"name": name, "duckdb_type": type_name, "nullable": nullable}
        for name, type_name, nullable in RELATIONSHIP_COLUMNS
    ]
    if (
        contract.get("relationship_schema") != expected_schema
        or contract.get("solar_relationship_schema") != expected_schema
        or contract.get("hard_gates")
        != {
            "companies_selected": EXPECTED_SELECTED_COMPANIES,
            "rows_equal_distinct_declared_keys": True,
            "null_declared_keys": 0,
            "typed_column_mismatches": 0,
            "compression": "ZSTD",
            "landed_duckdb_readback": True,
            "company_master_files": 0,
            "company_master_rows": 0,
            "raw_company_json_files": 0,
            "logical_json_cartridges": 0,
            "raw_archives": 0,
            "duplicate_corpus_builds": 0,
            "embedded_relationship_json_fields": 0,
            "promotion_eligible": False,
        }
    ):
        raise RuntimeError("Relationship schema or hard gates drifted")
    return {
        "status": "PASS",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "source_files": len(SOURCE_BOUNDARY),
    }


def validate_inputs(
    plan_path: Path,
    receipts_root: Path,
    reports_root: Path,
    repd_root: Path,
    basic_root: Path,
    accounts_path: Path,
    rest_evidence_path: Path,
    basic_report_path: Path,
) -> dict[str, Any]:
    if digest(plan_path) != BASE.EXPECTED_PLAN_SHA256:
        raise RuntimeError("The source-pinned archive plan drifted")
    if digest(rest_evidence_path) != BASE.EXPECTED_REST_EVIDENCE_SHA256:
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
    account_facts: dict[str, dict[str, Any]] = {}
    with accounts_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError("Merged accounts input contains a non-object record")
            number = str(row.get("company_number", ""))
            if not ENGINE.COMPANY_NUMBER.fullmatch(number):
                raise RuntimeError("Merged accounts input contains an invalid company record")
            if number in account_facts:
                raise RuntimeError("Merged accounts input contains an invalid or duplicate company number")
            LEGACY.require_private_safe(row, f"accounts/{number}")
            account_facts[number] = row
    if not account_facts:
        raise RuntimeError("Merged accounts input is empty")
    projects, repd_manifest = LEGACY.repd_closure(repd_root)
    if not BASE.verify_repd_input(repd_manifest):
        raise RuntimeError("Pinned REPD source closure drifted")
    return {
        "plan": plan,
        "receipts": receipts,
        "extractions": extractions,
        "basic_archive": basic_archive,
        "accounts_count": len(account_facts),
        "account_facts": account_facts,
        "projects": projects,
        "repd_manifest": repd_manifest,
        "rest_evidence": rest_evidence,
    }


def select_relationship_records(
    basic_archive: Path,
    account_facts: dict[str, dict[str, Any]],
    repd_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repd_index = COMPILER.repd_index(repd_root)
    selected_numbers: set[str] = set()
    relationship_records: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "basic_company_rows_scanned": 0,
        "selected_companies": 0,
        "assets_gte_10m_companies": 0,
        "energy_relevant_large_companies": 0,
        "probable_project_spvs": 0,
        "companies_with_repd_candidates": 0,
        "candidate_relationship_rows": 0,
        "btm_tag_counts": {},
    }
    with zipfile.ZipFile(basic_archive) as archive:
        csv_members = sorted(name for name in archive.namelist() if name.lower().endswith(".csv"))
        if not csv_members:
            raise RuntimeError("Basic-company archive contains no CSV member")
        for member in csv_members:
            with archive.open(member) as stream:
                rows = csv.DictReader(
                    line.decode("utf-8-sig", errors="replace") for line in stream
                )
                for row in rows:
                    summary["basic_company_rows_scanned"] += 1
                    number = COMPILER.field(row, "CompanyNumber").upper()
                    name = COMPILER.field(row, "CompanyName")
                    status = COMPILER.field(row, "CompanyStatus")
                    if not number or not name:
                        continue
                    if not ENGINE.COMPANY_NUMBER.fullmatch(number):
                        raise RuntimeError(f"Basic-company source has invalid company number: {number!r}")
                    sic_codes = [
                        COMPILER.field(row, f"SICCode.SicText_{index}") for index in range(1, 5)
                    ]
                    tags = COMPILER.sic_tags(sic_codes)
                    facts = account_facts.get(number, {})
                    large = max(
                        facts.get("total_assets", 0) or 0,
                        facts.get("net_assets", 0) or 0,
                    ) >= COMPILER.LIMIT
                    matches = COMPILER.repd_candidates(name, repd_index)
                    legal_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
                    probable_spv = bool(legal_tokens & {"limited", "ltd", "plc", "llp"}) and bool(
                        legal_tokens
                        & {"project", "farm", "solar", "wind", "battery", "storage", "bess", "generation"}
                    )
                    energy_relevant_large = large and bool(tags)
                    if not (energy_relevant_large or matches or probable_spv):
                        continue
                    if number in selected_numbers:
                        raise RuntimeError(f"Basic-company source duplicated selected company: {number}")
                    selected_numbers.add(number)
                    summary["selected_companies"] += 1
                    summary["assets_gte_10m_companies"] += int(large)
                    summary["energy_relevant_large_companies"] += int(energy_relevant_large)
                    summary["probable_project_spvs"] += int(probable_spv)
                    for tag in tags:
                        summary["btm_tag_counts"][tag] = summary["btm_tag_counts"].get(tag, 0) + 1
                    if not matches:
                        continue
                    candidate = {
                        "company_name": name,
                        "company_number": number,
                        "company_status": status,
                        "sic_codes": [value for value in sic_codes if value],
                        "accounts_date": facts.get("accounts_date"),
                        "total_assets": facts.get("total_assets"),
                        "net_assets": facts.get("net_assets"),
                        "turnover": facts.get("turnover"),
                        "cash": facts.get("cash"),
                        "assets_gte_10m": large,
                        "energy_relevant_large_company": energy_relevant_large,
                        "btm_tags": tags,
                        "repd_name_candidates": matches,
                        "probable_project_spv": probable_spv,
                    }
                    relationship_records.append(candidate)
                    summary["companies_with_repd_candidates"] += 1
                    summary["candidate_relationship_rows"] += len(matches)
    if not selected_numbers or not relationship_records:
        raise RuntimeError("Compact Companies selection is empty")
    summary["btm_tag_counts"] = dict(sorted(summary["btm_tag_counts"].items()))
    relationship_records.sort(key=lambda row: row["company_number"])
    return relationship_records, summary


def enrich_relationship_records(
    raw_records: list[dict[str, Any]], projects: dict[str, Any]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_record in raw_records:
        record = LEGACY.enrich(raw_record, projects)
        BASE.validate_company_record(record, f"compact/{record.get('company_number', '__missing__')}")
        if not record.get("repd_name_candidates"):
            raise RuntimeError("Relationship-only closure received a company without a REPD edge")
        result.append(record)
    result.sort(key=lambda row: row["company_number"])
    if len(result) != len({row["company_number"] for row in result}):
        raise RuntimeError("Relationship company universe contains duplicate company numbers")
    return result


def edge_tuple(payload: dict[str, Any], expected_source_commit: str) -> tuple[Any, ...]:
    if set(payload) != EDGE_PAYLOAD_KEYS:
        raise RuntimeError("Relationship payload key closure drifted")
    number = payload.get("company_number")
    name = payload.get("company_name")
    ref = payload.get("repd_ref")
    evidence_type = payload.get("evidence_type")
    technology = payload.get("technology")
    if (
        payload.get("generation") != GENERATION
        or payload.get("relationship_repository") != "Ventusltd/companies"
        or payload.get("relationship_repository_commit") != expected_source_commit
        or not isinstance(number, str)
        or not ENGINE.COMPANY_NUMBER.fullmatch(number)
        or not isinstance(name, str)
        or not name.strip()
        or payload.get("company_register_url")
        != f"https://find-and-update.company-information.service.gov.uk/company/{number}"
        or payload.get("repd_repository") != "Ventusltd/pipelinenews"
        or payload.get("repd_commit") != EXPECTED_PIPELINENEWS_COMMIT
        or payload.get("repd_path") != "data/projects"
        or not isinstance(ref, str)
        or not ref
        or ref != ref.strip()
        or payload.get("evidence_class") != "CANDIDATE"
        or evidence_type not in BASE.ALLOWED_MATCH_TYPES
        or payload.get("gg_project_id") != f"GG2050-REPD-{ref}"
        or technology not in REPD_TECHNOLOGIES
    ):
        raise RuntimeError("Relationship payload identity or provenance drifted")
    atlas = payload.get("atlas_url")
    for field in ("project", "operator", "status", "atlas_url"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise RuntimeError(f"Relationship nullable string drifted: {field}")
    if atlas is not None:
        parsed = urllib.parse.urlsplit(atlas)
        query = urllib.parse.parse_qs(parsed.query)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "globalgrid2050.com"
            or parsed.path != "/repd_grid_atlasv8/"
            or query.get("repd_ref") != [ref]
        ):
            raise RuntimeError("Relationship Atlas reference drifted")
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    for field, value, minimum, maximum in (
        ("latitude", latitude, -90.0, 90.0),
        ("longitude", longitude, -180.0, 180.0),
    ):
        if value is None:
            continue
        if isinstance(value, bool):
            raise RuntimeError(f"Relationship {field} drifted")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Relationship {field} drifted") from exc
        if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
            raise RuntimeError(f"Relationship {field} drifted")
    LEGACY.require_private_safe(payload, f"relationship/{number}/{ref}/{evidence_type}")
    relationship_sha256 = hashlib.sha256(BASE.canonical_json(payload).encode("utf-8")).hexdigest()
    return (
        GENERATION,
        "Ventusltd/companies",
        expected_source_commit,
        number,
        name,
        payload["company_register_url"],
        "Ventusltd/pipelinenews",
        EXPECTED_PIPELINENEWS_COMMIT,
        "data/projects",
        ref,
        "CANDIDATE",
        evidence_type,
        payload.get("gg_project_id") or None,
        payload.get("project") or None,
        payload.get("operator") or None,
        technology,
        ENGINE.bounded_decimal(payload.get("capacity_mw"), f"{number}/{ref}.capacity_mw"),
        payload.get("status") or None,
        float(latitude) if latitude is not None else None,
        float(longitude) if longitude is not None else None,
        atlas or None,
        relationship_sha256,
    )


def relationship_rows(
    records: list[dict[str, Any]], source_commit: str
) -> list[tuple[Any, ...]]:
    companies = {record["company_number"]: record for record in records}
    result: list[tuple[Any, ...]] = []
    seen: set[tuple[str, str, str]] = set()
    for base in ENGINE.relationship_rows(records):
        number = str(base[1])
        record = companies[number]
        payload = {
            "generation": GENERATION,
            "relationship_repository": "Ventusltd/companies",
            "relationship_repository_commit": source_commit,
            "company_number": number,
            "company_name": record["company_name"],
            "company_register_url": (
                "https://find-and-update.company-information.service.gov.uk/company/" + number
            ),
            "repd_repository": "Ventusltd/pipelinenews",
            "repd_commit": EXPECTED_PIPELINENEWS_COMMIT,
            "repd_path": "data/projects",
            "repd_ref": str(base[2]),
            "evidence_class": "CANDIDATE",
            "evidence_type": str(base[3]),
            "gg_project_id": base[4],
            "project": base[5],
            "operator": base[6],
            "technology": base[7],
            "capacity_mw": str(base[8]) if base[8] is not None else None,
            "status": base[9],
            "latitude": base[10],
            "longitude": base[11],
            "atlas_url": base[12],
        }
        row = edge_tuple(payload, source_commit)
        key = (str(row[3]), str(row[9]), str(row[11]))
        if key in seen:
            raise RuntimeError(f"Duplicate relationship key: {'/'.join(key)}")
        seen.add(key)
        result.append(row)
    if not result:
        raise RuntimeError("Company–REPD relationship dataset is empty")
    return sorted(result, key=lambda row: (row[3], row[9], row[11]))


def solar_rows(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    result = [row for row in rows if row[15] == "solar"]
    if not result:
        raise RuntimeError("Solar company–REPD relationship dataset is empty")
    return sorted(result, key=lambda row: (row[3], row[9], row[11]))


def build_datasets(
    output: Path, records: list[dict[str, Any]], source_commit: str
) -> dict[str, Any]:
    rows = relationship_rows(records, source_commit)
    selected_solar_rows = solar_rows(rows)
    ENGINE.write_parquet(
        output / RELATIONSHIP_PARQUET,
        RELATIONSHIP_COLUMNS,
        rows,
        RELATIONSHIP_KEY,
    )
    ENGINE.write_parquet(
        output / SOLAR_PARQUET,
        RELATIONSHIP_COLUMNS,
        selected_solar_rows,
        RELATIONSHIP_KEY,
    )
    relationships = ENGINE.audit_parquet(
        output / RELATIONSHIP_PARQUET,
        RELATIONSHIP_COLUMNS,
        RELATIONSHIP_KEY,
        "relationship_sha256",
        rows,
    )
    solar = ENGINE.audit_parquet(
        output / SOLAR_PARQUET,
        RELATIONSHIP_COLUMNS,
        RELATIONSHIP_KEY,
        "relationship_sha256",
        selected_solar_rows,
    )
    return {
        "schema": "companies-house-relationship-parquet-audit-v1",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "engine": {"name": "duckdb", "version": DUCKDB_VERSION, "threads": 1},
        "datasets": {
            "company_repd_candidates": {
                **relationships,
                "grain": "one cross-repository candidate Company–REPD relationship",
                "evidence_class": "CANDIDATE",
                "identity_posture": "CANDIDATE_ONLY_NOT_CONFIRMED_OWNERSHIP",
            },
            "solar_company_repd_relationships": {
                **solar,
                "grain": "one solar-filtered candidate company–REPD relationship",
                "evidence_class": "CANDIDATE",
                "identity_posture": "CANDIDATE_ONLY_NOT_CONFIRMED_OWNERSHIP",
            },
        },
    }


def read_relationship_rows(path: Path, expected_source_commit: str) -> list[tuple[Any, ...]]:
    duckdb = ENGINE.load_duckdb()
    connection = duckdb.connect(":memory:")
    result: list[tuple[Any, ...]] = []
    try:
        connection.execute("SET threads = 1")
        escaped = ENGINE.sql_path(path)
        cursor = connection.execute(
            f"SELECT * FROM read_parquet('{escaped}') "
            "ORDER BY company_number, repd_ref, evidence_type"
        )
        while True:
            batch = cursor.fetchmany(10_000)
            if not batch:
                break
            for row in batch:
                if len(row) != len(RELATIONSHIP_COLUMNS):
                    raise RuntimeError("Relationship landed column closure drifted")
                payload = {
                    name: (str(row[index]) if name == "capacity_mw" and row[index] is not None else row[index])
                    for index, (name, _type, _nullable) in enumerate(RELATIONSHIP_COLUMNS[:-1])
                }
                expected = edge_tuple(payload, expected_source_commit)
                if tuple(row) != expected:
                    raise RuntimeError("Relationship landed row hash or typed value drifted")
                result.append(expected)
    finally:
        connection.close()
    if not result:
        raise RuntimeError("Relationship readback is empty")
    return result


def exact_file_closure(root: Path, manifest: dict[str, Any]) -> tuple[list[Path], int]:
    expected = {
        MANIFEST_PATH.as_posix(),
        RELATIONSHIP_PARQUET.as_posix(),
        SOLAR_PARQUET.as_posix(),
        REPORT_PATH.as_posix(),
        AUDIT_PATH.as_posix(),
    }
    expected.update(str(row["path"]) for row in manifest.get("evidence", []))
    nodes = list(root.rglob("*"))
    if any(path.is_symlink() for path in nodes):
        raise RuntimeError("Candidate contains a symlink")
    files = sorted(path for path in nodes if path.is_file())
    actual = {path.relative_to(root).as_posix() for path in files}
    if actual != expected:
        raise RuntimeError(f"Compact candidate file closure drifted: {sorted(actual ^ expected)!r}")
    if any(path.suffix.lower() in {".zip", ".ndjson", ".csv", ".gz"} for path in files):
        raise RuntimeError("Raw or transport data leaked into the compact candidate")
    if any(path.name == "companies-v1.parquet" for path in files):
        raise RuntimeError("A company-master Parquet leaked into the relationship-only candidate")
    oversized = [path for path in files if path.stat().st_size > MAXIMUM_FILE_BYTES]
    total = sum(path.stat().st_size for path in files)
    if oversized or total > MAXIMUM_TOTAL_BYTES:
        raise RuntimeError(
            f"Compact candidate byte gate failed: total={total}, oversized={[p.name for p in oversized]!r}"
        )
    return files, total


def verify(root: Path, expected_source_commit: str) -> dict[str, Any]:
    if not SOURCE_COMMIT.fullmatch(expected_source_commit):
        raise RuntimeError("Expected source commit is invalid")
    manifest_path = root / MANIFEST_PATH
    manifest = load_json(manifest_path)
    if set(manifest) != MANIFEST_KEYS or manifest_path.read_bytes() != pretty_json(manifest).encode(
        "utf-8"
    ):
        raise RuntimeError("Compact manifest key or canonical byte closure drifted")
    if (
        manifest.get("schema") != "companies-house-relationship-report-candidate-v1"
        or manifest.get("generation") != GENERATION
        or manifest.get("resume_generation") != RESUME_GENERATION
        or manifest.get("generated_at") != FIXED_GENERATED_AT
        or manifest.get("source_commit") != expected_source_commit
        or manifest.get("supersedes_failed_run_id") != SUPERSEDED_FAILED_RUN_ID
        or manifest.get("deployment_state") != "not-authorised"
        or manifest.get("promotion_eligible") is not False
        or manifest.get("coverage") != BASE.COVERAGE
        or manifest.get("threshold_gbp") != 10_000_000
        or manifest.get("financial_currency") != "GBP"
        or type(manifest.get("basic_company_rows_scanned")) is not int
        or manifest.get("basic_company_rows_scanned", 0) <= EXPECTED_SELECTED_COMPANIES
        or manifest.get("companies_selected") != EXPECTED_SELECTED_COMPANIES
        or manifest.get("privacy") != BASE.PRIVACY
        or manifest.get("usage_context") != "NON_COMMERCIAL_OPEN_SOURCE"
        or manifest.get("source_licences") != ENGINE.MATERIALISED_SOURCES
        or manifest.get("source_rights_are_distinct_from_usage_context") is not True
        or manifest.get("filing_truth_caveat") != FILING_TRUTH_CAVEAT
        or manifest.get("relationship_truth_caveat") != RELATIONSHIP_TRUTH_CAVEAT
        or manifest.get("publication") != PUBLICATION
    ):
        raise RuntimeError("Compact candidate governance drifted")
    inputs = manifest.get("inputs")
    if (
        not isinstance(inputs, dict)
        or set(inputs) != INPUT_KEYS
        or inputs.get("acquisition_run_id") != EXPECTED_ACQUISITION_RUN_ID
        or inputs.get("acquisition_source_commit") != EXPECTED_ACQUISITION_SOURCE_COMMIT
        or inputs.get("retained_artifacts") != RETAINED_ARTIFACTS
        or inputs.get("source_parent_commit") != EXPECTED_MAIN_PARENT_COMMIT
        or inputs.get("companies_base_commit") != BASE.BASE_COMMIT
        or inputs.get("pipelinenews_commit") != EXPECTED_PIPELINENEWS_COMMIT
        or inputs.get("download_plan_sha256") != BASE.EXPECTED_PLAN_SHA256
        or not re.fullmatch(r"[0-9a-f]{64}", str(inputs.get("basic_archive_sha256", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(inputs.get("basic_validation_sha256", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(inputs.get("accounts_latest_sha256", "")))
        or type(inputs.get("accounts_latest_records")) is not int
        or inputs.get("accounts_latest_records", 0) < 1
        or not BASE.verify_repd_input(inputs.get("repd"))
        or inputs.get("repd_runtime_read")
        != {
            "repository": "Ventusltd/pipelinenews",
            "commit": EXPECTED_PIPELINENEWS_COMMIT,
            "path": "data/projects",
            "mode": "read-only sparse checkout",
            "foreign_repository_files_committed": False,
            "foreign_data_materialised": True,
        }
        or inputs.get("news") != {"included": False, "identity_policy": "annotation-only"}
    ):
        raise RuntimeError("Compact candidate input provenance drifted")
    evidence_errors: list[str] = []
    BASE.verify_evidence(root, manifest, evidence_errors)
    if evidence_errors:
        raise RuntimeError(f"Compact evidence semantics drifted: {evidence_errors!r}")
    output_policy = manifest.get("output_policy", {})
    if output_policy != {
        "canonical_relationship_format": "PARQUET",
        "aggregate_report_format": "JSON",
        "duckdb_version": DUCKDB_VERSION,
        "relationship_tables": 2,
        "company_master_files": 0,
        "company_master_rows": 0,
        "embedded_relationship_json_fields": 0,
        "logical_json_cartridges": 0,
        "raw_company_json_files": 0,
        "raw_archives": 0,
        "duplicate_corpus_builds": 0,
        "maximum_file_bytes": MAXIMUM_FILE_BYTES,
        "maximum_candidate_total_bytes": MAXIMUM_TOTAL_BYTES,
        "exact_file_closure_enforced": True,
    }:
        raise RuntimeError("Compact output policy drifted")
    rows = read_relationship_rows(root / RELATIONSHIP_PARQUET, expected_source_commit)
    selected_solar_rows = solar_rows(rows)
    relationships = ENGINE.audit_parquet(
        root / RELATIONSHIP_PARQUET,
        RELATIONSHIP_COLUMNS,
        RELATIONSHIP_KEY,
        "relationship_sha256",
        rows,
    )
    solar = ENGINE.audit_parquet(
        root / SOLAR_PARQUET,
        RELATIONSHIP_COLUMNS,
        RELATIONSHIP_KEY,
        "relationship_sha256",
        selected_solar_rows,
    )
    expected_datasets = {
        "company_repd_candidates": {
            **relationships,
            "grain": "one cross-repository candidate Company–REPD relationship",
            "evidence_class": "CANDIDATE",
            "identity_posture": "CANDIDATE_ONLY_NOT_CONFIRMED_OWNERSHIP",
        },
        "solar_company_repd_relationships": {
            **solar,
            "grain": "one solar-filtered candidate company–REPD relationship",
            "evidence_class": "CANDIDATE",
            "identity_posture": "CANDIDATE_ONLY_NOT_CONFIRMED_OWNERSHIP",
        },
    }
    audit = load_json(root / AUDIT_PATH)
    if (root / AUDIT_PATH).read_bytes() != pretty_json(audit).encode("utf-8"):
        raise RuntimeError("Compact audit canonical byte closure drifted")
    expected_audit = {
        "schema": "companies-house-relationship-parquet-audit-v1",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "engine": {"name": "duckdb", "version": DUCKDB_VERSION, "threads": 1},
        "datasets": expected_datasets,
    }
    distinct_companies = len({str(row[3]) for row in rows})
    if (
        audit != expected_audit
        or manifest.get("datasets") != expected_datasets
        or manifest.get("companies_with_repd_candidates") != distinct_companies
        or manifest.get("company_repd_candidates") != relationships["rows"]
        or manifest.get("solar_company_repd_relationships") != solar["rows"]
    ):
        raise RuntimeError("Stored DuckDB audit or manifest differs from landed Parquet readback")
    report_path = root / REPORT_PATH
    report = load_json(report_path)
    selection = report.get("selection_summary")
    if (
        not isinstance(selection, dict)
        or set(selection)
        != {
            "selected_companies",
            "basic_company_rows_scanned",
            "assets_gte_10m_companies",
            "energy_relevant_large_companies",
            "probable_project_spvs",
            "companies_with_repd_candidates",
            "candidate_relationship_rows",
            "btm_tag_counts",
        }
        or any(
            type(selection.get(key)) is not int or selection.get(key, -1) < 0
            for key in set(selection) - {"btm_tag_counts"}
        )
        or selection.get("selected_companies") != EXPECTED_SELECTED_COMPANIES
        or selection.get("basic_company_rows_scanned", 0) <= EXPECTED_SELECTED_COMPANIES
        or manifest.get("basic_company_rows_scanned")
        != selection.get("basic_company_rows_scanned")
        or selection.get("companies_with_repd_candidates") != distinct_companies
        or selection.get("candidate_relationship_rows") != relationships["rows"]
        or not isinstance(selection.get("btm_tag_counts"), dict)
        or any(
            not isinstance(key, str) or type(value) is not int or value < 0
            for key, value in selection.get("btm_tag_counts", {}).items()
        )
    ):
        raise RuntimeError("Aggregate selection report drifted")
    expected_report = {
        "schema": "companies-house-cross-repository-relationship-report-v1",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "basic_company_rows_scanned": selection["basic_company_rows_scanned"],
        "companies_selected": EXPECTED_SELECTED_COMPANIES,
        "companies_with_repd_candidates": distinct_companies,
        "company_repd_candidates": relationships["rows"],
        "solar_company_repd_relationships": solar["rows"],
        "selection_summary": selection,
        "durable_output": {
            "primary_product": "CROSS_REPOSITORY_RELATIONSHIP_REPORT",
            "company_master_files": 0,
            "company_master_rows": 0,
            "embedded_relationship_json_fields": 0,
            "raw_company_files": 0,
            "relationship_tables": [RELATIONSHIP_PARQUET.as_posix(), SOLAR_PARQUET.as_posix()],
        },
        "datasets": expected_datasets,
    }
    if report != expected_report or report_path.read_bytes() != pretty_json(report).encode("utf-8"):
        raise RuntimeError("Aggregate relationship report or canonical bytes drifted")
    if manifest.get("audit") != receipt(root / AUDIT_PATH, root):
        raise RuntimeError("Audit receipt drifted")
    if manifest.get("report") != receipt(report_path, root):
        raise RuntimeError("Report receipt drifted")
    for evidence in manifest.get("evidence", []):
        path = root / str(evidence.get("path", "__missing__"))
        if not path.is_file() or receipt(path, root) != evidence:
            raise RuntimeError("Evidence receipt drifted")
    files, total = exact_file_closure(root, manifest)
    return {
        "status": "PASS",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "basic_company_rows_scanned": selection["basic_company_rows_scanned"],
        "companies_selected": EXPECTED_SELECTED_COMPANIES,
        "companies_with_repd_candidates": distinct_companies,
        "company_repd_candidates": relationships["rows"],
        "solar_company_repd_relationships": solar["rows"],
        "candidate_files": len(files),
        "candidate_bytes": total,
        "source_commit": expected_source_commit,
    }


def build(
    root: Path,
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
) -> dict[str, Any]:
    doctor(root)
    if output.exists():
        raise RuntimeError("Compact candidate target must be absent")
    if not SOURCE_COMMIT.fullmatch(source_commit):
        raise RuntimeError("Generation source commit is invalid")
    inputs = validate_inputs(
        plan_path,
        receipts_root,
        reports_root,
        repd_root,
        basic_root,
        accounts_path,
        rest_evidence_path,
        basic_report_path,
    )
    account_facts = inputs.pop("account_facts")
    raw_records, selection_summary = select_relationship_records(
        inputs["basic_archive"], account_facts, repd_root
    )
    del account_facts
    if selection_summary["selected_companies"] != EXPECTED_SELECTED_COMPANIES:
        raise RuntimeError(
            "Pinned transient company scan drifted: "
            f"expected={EXPECTED_SELECTED_COMPANIES}, actual={selection_summary['selected_companies']}"
        )
    records = enrich_relationship_records(raw_records, inputs["projects"])
    del raw_records
    if len(records) != selection_summary["companies_with_repd_candidates"]:
        raise RuntimeError("Relationship-company count drifted during enrichment")
    output.mkdir(parents=True, exist_ok=False)
    evidence = BASE.copy_evidence(
        output,
        plan_path,
        receipts_root,
        reports_root,
        inputs["receipts"],
        inputs["extractions"],
        rest_evidence_path,
        basic_report_path,
    )
    audit = build_datasets(output, records, source_commit)
    (output / AUDIT_PATH).write_text(pretty_json(audit), encoding="utf-8")
    relationship_count = audit["datasets"]["company_repd_candidates"]["rows"]
    solar_count = audit["datasets"]["solar_company_repd_relationships"]["rows"]
    if relationship_count != selection_summary["candidate_relationship_rows"]:
        raise RuntimeError("Relationship count drifted during enrichment")
    report = {
        "schema": "companies-house-cross-repository-relationship-report-v1",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "status": "PASS",
        "basic_company_rows_scanned": selection_summary["basic_company_rows_scanned"],
        "companies_selected": EXPECTED_SELECTED_COMPANIES,
        "companies_with_repd_candidates": len(records),
        "company_repd_candidates": relationship_count,
        "solar_company_repd_relationships": solar_count,
        "selection_summary": selection_summary,
        "durable_output": {
            "primary_product": "CROSS_REPOSITORY_RELATIONSHIP_REPORT",
            "company_master_files": 0,
            "company_master_rows": 0,
            "embedded_relationship_json_fields": 0,
            "raw_company_files": 0,
            "relationship_tables": [RELATIONSHIP_PARQUET.as_posix(), SOLAR_PARQUET.as_posix()],
        },
        "datasets": audit["datasets"],
    }
    (output / REPORT_PATH).write_text(pretty_json(report), encoding="utf-8")
    manifest = {
        "schema": "companies-house-relationship-report-candidate-v1",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "source_commit": source_commit,
        "supersedes_failed_run_id": SUPERSEDED_FAILED_RUN_ID,
        "deployment_state": "not-authorised",
        "promotion_eligible": False,
        "coverage": BASE.COVERAGE,
        "threshold_gbp": 10_000_000,
        "financial_currency": "GBP",
        "basic_company_rows_scanned": selection_summary["basic_company_rows_scanned"],
        "companies_selected": EXPECTED_SELECTED_COMPANIES,
        "companies_with_repd_candidates": len(records),
        "company_repd_candidates": relationship_count,
        "solar_company_repd_relationships": solar_count,
        "privacy": BASE.PRIVACY,
        "usage_context": "NON_COMMERCIAL_OPEN_SOURCE",
        "source_licences": ENGINE.MATERIALISED_SOURCES,
        "source_rights_are_distinct_from_usage_context": True,
        "filing_truth_caveat": FILING_TRUTH_CAVEAT,
        "relationship_truth_caveat": RELATIONSHIP_TRUTH_CAVEAT,
        "publication": PUBLICATION,
        "inputs": {
            "acquisition_run_id": EXPECTED_ACQUISITION_RUN_ID,
            "acquisition_source_commit": EXPECTED_ACQUISITION_SOURCE_COMMIT,
            "retained_artifacts": RETAINED_ARTIFACTS,
            "source_parent_commit": EXPECTED_MAIN_PARENT_COMMIT,
            "companies_base_commit": BASE.BASE_COMMIT,
            "pipelinenews_commit": EXPECTED_PIPELINENEWS_COMMIT,
            "download_plan_sha256": BASE.EXPECTED_PLAN_SHA256,
            "basic_archive_sha256": digest(inputs["basic_archive"]),
            "basic_validation_sha256": digest(basic_report_path),
            "accounts_latest_sha256": digest(accounts_path),
            "accounts_latest_records": inputs["accounts_count"],
            "repd": inputs["repd_manifest"],
            "repd_runtime_read": {
                "repository": "Ventusltd/pipelinenews",
                "commit": EXPECTED_PIPELINENEWS_COMMIT,
                "path": "data/projects",
                "mode": "read-only sparse checkout",
                "foreign_repository_files_committed": False,
                "foreign_data_materialised": True,
            },
            "optional_rest": {
                "enabled": inputs["rest_evidence"]["enabled"],
                "status": inputs["rest_evidence"]["status"],
                "evidence_sha256": BASE.EXPECTED_REST_EVIDENCE_SHA256,
            },
            "news": {"included": False, "identity_policy": "annotation-only"},
        },
        "datasets": audit["datasets"],
        "report": receipt(output / REPORT_PATH, output),
        "evidence": evidence,
        "audit": receipt(output / AUDIT_PATH, output),
        "output_policy": {
            "canonical_relationship_format": "PARQUET",
            "aggregate_report_format": "JSON",
            "duckdb_version": DUCKDB_VERSION,
            "relationship_tables": 2,
            "company_master_files": 0,
            "company_master_rows": 0,
            "embedded_relationship_json_fields": 0,
            "logical_json_cartridges": 0,
            "raw_company_json_files": 0,
            "raw_archives": 0,
            "duplicate_corpus_builds": 0,
            "maximum_file_bytes": MAXIMUM_FILE_BYTES,
            "maximum_candidate_total_bytes": MAXIMUM_TOTAL_BYTES,
            "exact_file_closure_enforced": True,
        },
    }
    (output / MANIFEST_PATH).write_text(pretty_json(manifest), encoding="utf-8")
    del records, inputs
    return verify(output, source_commit)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor")
    doctor_parser.add_argument("--root", type=Path, required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--plan", type=Path, required=True)
    build_parser.add_argument("--receipts", type=Path, required=True)
    build_parser.add_argument("--reports", type=Path, required=True)
    build_parser.add_argument("--repd", type=Path, required=True)
    build_parser.add_argument("--basic", type=Path, required=True)
    build_parser.add_argument("--accounts", type=Path, required=True)
    build_parser.add_argument("--rest-evidence", type=Path, required=True)
    build_parser.add_argument("--basic-report", type=Path, required=True)
    build_parser.add_argument("--source-commit", required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--expected-source-commit", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "doctor":
        result = doctor(args.root.resolve())
    elif args.command == "verify":
        result = verify(args.root.resolve(), args.expected_source_commit)
    else:
        result = build(
            args.root.resolve(),
            args.output.resolve(),
            args.plan.resolve(),
            args.receipts.resolve(),
            args.reports.resolve(),
            args.repd.resolve(),
            args.basic.resolve(),
            args.accounts.resolve(),
            args.rest_evidence.resolve(),
            args.basic_report.resolve(),
            args.source_commit,
        )
    print(pretty_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
