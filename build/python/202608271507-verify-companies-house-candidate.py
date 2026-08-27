#!/usr/bin/env python3
"""Seal and independently verify the immutable bounded Companies candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

GENERATION = "202608271507"
BASE_COMMIT = "145da3dc6ff7541edb008676528636c11ba428ee"
PIPELINENEWS_COMMIT = "35f35ada161223fb3ee19e525664ee7f17df1ddd"
FIXED_GENERATED_AT = "2026-08-27T14:07:00Z"
MAXIMUM_TOTAL_BYTES = 200_000_000
MAXIMUM_FILE_BYTES = 90_000_000
OGL = {
    "name": "Open Government Licence v3.0",
    "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    "attribution": "Contains public sector information licensed under the Open Government Licence v3.0. Source: Companies House.",
    "rights_caveat": "OGL applies to Crown copyright material; third-party rights and data-protection duties may still apply.",
    "accuracy_caveat": "Companies House records what was filed; it does not verify every filed statement.",
}
EXPECTED_CARTRIDGES = {
    "industrial-assets-gte-10m",
    "energy-relevant-assets-gte-10m",
    "repd-linked",
    "project-spv-candidates",
    "btm-opportunities",
}
COMPANY_NUMBER = re.compile(r"^(?:[A-Z]{2}\d{6}|\d{8})$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
CLASSIFICATIONS = {
    "REPD_NAME_CANDIDATE",
    "PROBABLE_PROJECT_SPV",
    "ENERGY_RELEVANT_LARGE_COMPANY",
    "UNRESOLVED_CANDIDATE",
}
FORBIDDEN_KEYS = {
    "director",
    "directorname",
    "directors",
    "dateofbirth",
    "dob",
    "residentialaddress",
    "homeaddress",
    "individualpsc",
    "psc",
    "creditscore",
    "bankabilityscore",
    "bankability",
    "riskrating",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def normal_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def recursive_keys(value) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            result.add(normal_key(str(key)))
            result.update(recursive_keys(child))
    elif isinstance(value, list):
        for child in value:
            result.update(recursive_keys(child))
    return result


def require_private_safe(value, label: str) -> None:
    leaked = recursive_keys(value).intersection(FORBIDDEN_KEYS)
    if leaked:
        raise RuntimeError(f"{label} contains prohibited personal/scoring keys: {sorted(leaked)}")


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text())
    if (
        plan.get("schema") != "companies-house-bounded-download-plan-v1"
        or plan.get("generation") != GENERATION
        or plan.get("base_commit") != BASE_COMMIT
        or plan.get("deployment_state") != "not-authorised"
        or plan.get("accounts_months") != 3
        or plan.get("file_limit") != 4
        or plan.get("maximum_archive_bytes") != 4_000_000_000
        or plan.get("maximum_total_bytes") != 12_000_000_000
        or plan.get("licence") != OGL
    ):
        raise RuntimeError("Download plan violates the fixed bounded contract")
    files = plan.get("files")
    if not isinstance(files, list) or len(files) != 4:
        raise RuntimeError("Download plan does not contain four files")
    if sum(item.get("bytes", 0) for item in files) != plan.get("total_bytes"):
        raise RuntimeError("Download plan byte closure is inconsistent")
    if plan["total_bytes"] > plan["maximum_total_bytes"]:
        raise RuntimeError("Download plan exceeded its ceiling")
    if [item.get("kind") for item in files].count("accounts") != 3 or [item.get("kind") for item in files].count("basic") != 1:
        raise RuntimeError("Download plan kind closure is invalid")
    if any(not isinstance(item.get("bytes"), int) or item["bytes"] > 4_000_000_000 for item in files):
        raise RuntimeError("Download plan per-archive ceiling is invalid")
    return plan


def collect_receipts(root: Path, plan: dict) -> list[dict]:
    paths = sorted(root.rglob("receipt-*.json"))
    if len(paths) != 4:
        raise RuntimeError(f"Expected four acquisition receipts, received {len(paths)}")
    plan_sha = digest(Path(plan["_path"]))
    receipts = [json.loads(path.read_text()) for path in paths]
    by_index: dict[int, dict] = {}
    for receipt in receipts:
        if (
            receipt.get("schema") != "companies-house-bounded-download-receipt-v1"
            or receipt.get("generation") != GENERATION
            or receipt.get("base_commit") != BASE_COMMIT
            or receipt.get("plan_sha256") != plan_sha
        ):
            raise RuntimeError("Acquisition receipt violates the fixed contract")
        index = receipt.get("index")
        if not isinstance(index, int) or index in by_index:
            raise RuntimeError("Acquisition receipt index is invalid or duplicated")
        by_index[index] = receipt
    for index, item in enumerate(plan["files"]):
        receipt = by_index.get(index)
        if not receipt:
            raise RuntimeError(f"Missing acquisition receipt {index}")
        for key in ("kind", "url", "resolved_url", "filename", "bytes", "etag", "last_modified"):
            if receipt.get(key) != item.get(key):
                raise RuntimeError(f"Receipt {index} drifted from plan field {key}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256", ""))):
            raise RuntimeError(f"Receipt {index} lacks an archive SHA-256")
    return [by_index[index] for index in range(4)]


def collect_extractions(root: Path, receipts: list[dict]) -> list[dict]:
    paths = sorted(root.rglob("extraction-*.json"))
    if len(paths) != 3:
        raise RuntimeError(f"Expected three extraction reports, received {len(paths)}")
    reports = [json.loads(path.read_text()) for path in paths]
    account_receipts = {item["filename"]: item for item in receipts if item["kind"] == "accounts"}
    if {item.get("archive_filename") for item in reports} != set(account_receipts):
        raise RuntimeError("Extraction/archive receipt closure is inconsistent")
    for path, report in zip(paths, reports):
        receipt = account_receipts[report["archive_filename"]]
        match = re.fullmatch(r"extraction-(\d+)\.json", path.name)
        ndjson = path.with_name(f"accounts-{match.group(1)}.ndjson") if match else path.with_name("__missing__")
        if (
            report.get("schema") != "companies-house-bounded-extraction-report-v1"
            or report.get("generation") != GENERATION
            or report.get("status") != "PASS"
            or report.get("archive_sha256") != receipt["sha256"]
            or report.get("archive_bytes") != receipt["bytes"]
            or report.get("records", 0) < 1
            or report.get("parse_error_rate", 1) > 0.02
            or not ndjson.is_file()
            or report.get("output_sha256") != digest(ndjson)
        ):
            raise RuntimeError("Extraction report violates the bounded contract")
    return sorted(reports, key=lambda row: row["archive_filename"])


def load_rest_evidence(path: Path) -> dict:
    evidence = json.loads(path.read_text())
    if (
        evidence.get("schema") != "companies-house-optional-rest-evidence-v1"
        or evidence.get("generation") != GENERATION
        or evidence.get("endpoint") != "https://api.company-information.service.gov.uk/company/00000006"
    ):
        raise RuntimeError("Optional REST evidence violates the fixed contract")
    if evidence.get("enabled") is False:
        if evidence.get("status") != "SKIPPED" or evidence.get("reason") != "optional-secret-not-configured":
            raise RuntimeError("Disabled optional REST evidence is malformed")
    elif evidence.get("enabled") is True:
        if (
            evidence.get("status") != "PASS"
            or not isinstance(evidence.get("rate_limit"), int)
            or not isinstance(evidence.get("rate_remaining"), int)
            or not isinstance(evidence.get("rate_reset"), int)
            or evidence.get("response_body_retained") is not False
            or evidence.get("credential_retained") is not False
        ):
            raise RuntimeError("Enabled optional REST evidence is malformed")
    else:
        raise RuntimeError("Optional REST evidence lacks an explicit enabled state")
    serialised = json.dumps(evidence, sort_keys=True).lower()
    if "authorization" in serialised or "api_key" in serialised or "apikey" in serialised:
        raise RuntimeError("Optional REST evidence retained credential-shaped material")
    return evidence


def load_basic_report(path: Path, receipt: dict) -> dict:
    report = json.loads(path.read_text())
    if (
        report.get("schema") != "companies-house-bounded-basic-validation-v1"
        or report.get("generation") != GENERATION
        or report.get("status") != "PASS"
        or report.get("archive_filename") != receipt.get("filename")
        or report.get("archive_bytes") != receipt.get("bytes")
        or report.get("archive_sha256") != receipt.get("sha256")
        or report.get("csv_members") != 1
        or not isinstance(report.get("expanded_bytes"), int)
        or report["expanded_bytes"] < 1
        or report["expanded_bytes"] > 12_000_000_000
    ):
        raise RuntimeError("Basic snapshot validation report violates the bounded contract")
    return report


def repd_closure(root: Path) -> tuple[dict[str, dict], dict]:
    projects: dict[str, dict] = {}
    files = []
    for path in sorted(root.glob("*.json")):
        file_hash = digest(path)
        payload = json.loads(path.read_text())
        files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": file_hash})
        for project in payload.get("projects", []):
            ref = str(project.get("repd_ref", ""))
            if ref:
                projects[ref] = project
    if not projects or not files:
        raise RuntimeError("Frozen REPD input closure is empty")
    closure_hash = hashlib.sha256(
        "".join(f"{item['path']}\0{item['sha256']}\n" for item in files).encode()
    ).hexdigest()
    return projects, {"files": files, "sha256": closure_hash, "projects": len(projects)}


def atlas_url(project: dict) -> str | None:
    latitude = project.get("latitude")
    longitude = project.get("longitude")
    if project.get("geometry_status") != "valid" or latitude is None or longitude is None:
        return None
    query = urllib.parse.urlencode(
        {
            "repd_ref": str(project["repd_ref"]),
            "project": project.get("name", ""),
            "technology": project.get("technology", ""),
            "capacity_mw": project.get("capacity_mw", ""),
            "latitude": latitude,
            "longitude": longitude,
            "zoom": "12",
        }
    )
    return f"https://globalgrid2050.com/repd_grid_atlasv8/?{query}"


def enrich(record: dict, projects: dict[str, dict]) -> dict:
    result = json.loads(json.dumps(record))
    matches = []
    for match in result.get("repd_name_candidates", []):
        ref = str(match.get("repd_ref", ""))
        project = projects.get(ref)
        if not project:
            raise RuntimeError(f"REPD candidate {ref} is outside the frozen project spine")
        enriched = {
            **match,
            "repd_ref": ref,
            "gg_project_id": project.get("gg_project_id") or f"GG2050-REPD-{ref}",
            "project": project.get("name", match.get("project", "")),
            "operator": project.get("operator", match.get("operator", "")),
            "technology": project.get("technology"),
            "capacity_mw": project.get("capacity_mw"),
            "status": project.get("status"),
            "latitude": project.get("latitude"),
            "longitude": project.get("longitude"),
            "atlas_url": atlas_url(project),
        }
        matches.append(enriched)
    result["repd_name_candidates"] = sorted(matches, key=lambda row: (row["repd_ref"], row.get("match_type", "")))
    if matches:
        classification = "REPD_NAME_CANDIDATE"
    elif result.get("probable_project_spv"):
        classification = "PROBABLE_PROJECT_SPV"
    elif result.get("energy_relevant_large_company"):
        classification = "ENERGY_RELEVANT_LARGE_COMPANY"
    else:
        classification = "UNRESOLVED_CANDIDATE"
    result["classification"] = classification
    result["financial_currency"] = "GBP"
    result["news_identity_policy"] = "NEWS_MAY_ANNOTATE_BUT_NEVER_ESTABLISH_IDENTITY"
    require_private_safe(result, f"company {result.get('company_number', '')}")
    return result


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
    if not COMMIT_SHA.fullmatch(source_commit):
        raise RuntimeError("Generation source commit is not an exact SHA")
    plan = load_plan(plan_path)
    plan["_path"] = str(plan_path)
    receipts = collect_receipts(receipts_root, plan)
    extractions = collect_extractions(reports_root, receipts)
    basic_receipt = next(item for item in receipts if item["kind"] == "basic")
    rest_evidence = load_rest_evidence(rest_evidence_path)
    basic_report = load_basic_report(basic_report_path, basic_receipt)
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
    seen_account_numbers = set()
    with accounts_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            number = str(row.get("company_number", ""))
            if not COMPANY_NUMBER.fullmatch(number) or number in seen_account_numbers:
                raise RuntimeError("Merged accounts input contains an invalid or duplicated company number")
            seen_account_numbers.add(number)
            account_records += 1
    if not account_records:
        raise RuntimeError("Merged accounts input is empty")
    projects, repd_manifest = repd_closure(repd_root)
    raw_manifest = json.loads((raw_root / "manifest-v1.json").read_text())
    raw_files = raw_manifest.get("files", {})
    if set(raw_files) != EXPECTED_CARTRIDGES:
        raise RuntimeError("Compiler cartridge closure is unexpected")
    output.mkdir(parents=True, exist_ok=False)
    files: dict[str, dict] = {}
    canonical: dict[str, str] = {}
    for name in sorted(EXPECTED_CARTRIDGES):
        source = raw_root / raw_files[name]["path"]
        payload = json.loads(source.read_text())
        records = payload.get("records")
        if payload.get("schema") != "companies-house-cartridge-v1" or not isinstance(records, list):
            raise RuntimeError(f"Raw cartridge is malformed: {name}")
        if digest(source) != raw_files[name].get("sha256") or len(records) != raw_files[name].get("records"):
            raise RuntimeError(f"Raw compiler receipt failed for cartridge: {name}")
        sealed_records = []
        seen = set()
        for record in records:
            number = str(record.get("company_number", ""))
            if not COMPANY_NUMBER.fullmatch(number) or number in seen:
                raise RuntimeError(f"Invalid or duplicated company number in {name}")
            seen.add(number)
            item = enrich(record, projects)
            serialised = json.dumps(item, sort_keys=True, separators=(",", ":"))
            if number in canonical and canonical[number] != serialised:
                raise RuntimeError(f"Cross-cartridge drift for company {number}")
            canonical[number] = serialised
            sealed_records.append(item)
        sealed_records.sort(key=lambda row: row["company_number"])
        path = output / f"{name}-v1.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "companies-house-cartridge-v1",
                    "snapshot_id": GENERATION,
                    "generated_at": FIXED_GENERATED_AT,
                    "coverage": "BOUNDED_THREE_MONTH_CANDIDATE",
                    "licence": OGL,
                    "records": sealed_records,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        files[name] = {"path": path.name, "records": len(sealed_records), "bytes": path.stat().st_size, "sha256": digest(path)}
    evidence = output / "evidence"
    evidence.mkdir()
    evidence_files = []
    source_evidence = [
        ("download-plan.json", plan_path),
        ("rest-api.json", rest_evidence_path),
        ("basic-validation.json", basic_report_path),
    ]
    source_evidence += [(f"receipt-{row['index']}.json", next(path for path in receipts_root.rglob("receipt-*.json") if json.loads(path.read_text()).get("index") == row["index"])) for row in receipts]
    for index, report in enumerate(extractions):
        source_path = next(path for path in reports_root.rglob("extraction-*.json") if json.loads(path.read_text()).get("archive_filename") == report["archive_filename"])
        source_evidence.append((f"extraction-{index}.json", source_path))
    for name, source in source_evidence:
        target = evidence / name
        shutil.copyfile(source, target)
        evidence_files.append({"path": f"evidence/{name}", "bytes": target.stat().st_size, "sha256": digest(target)})
    manifest = {
        "schema": "companies-house-bounded-candidate-v1",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "promotion_eligible": False,
        "coverage": {
            "kind": "bounded-three-month-candidate",
            "accounts_months": 3,
            "partial_coverage": True,
            "annual_bootstrap": False,
        },
        "threshold_gbp": 10_000_000,
        "financial_currency": "GBP",
        "inputs": {
            "companies_base_commit": BASE_COMMIT,
            "generation_source_commit": source_commit,
            "pipelinenews_commit": PIPELINENEWS_COMMIT,
            "repd": repd_manifest,
            "download_plan_sha256": digest(plan_path),
            "basic_archive_sha256": digest(basic_archive),
            "accounts_latest_sha256": digest(accounts_path),
            "accounts_latest_records": account_records,
            "optional_rest": {
                "enabled": rest_evidence["enabled"],
                "status": rest_evidence["status"],
                "evidence_sha256": digest(rest_evidence_path),
            },
            "basic_validation_sha256": digest(basic_report_path),
            "news": {"included": False, "identity_policy": "annotation-only"},
        },
        "files": files,
        "evidence": evidence_files,
        "companies": len(canonical),
        "privacy": {
            "directors": False,
            "individual_psc": False,
            "dates_of_birth": False,
            "residential_addresses": False,
            "credit_scores": False,
            "bankability_scores": False,
        },
        "licence": OGL,
    }
    manifest_path = output / "manifest-v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    verification = verify(output)
    if verification["status"] != "PASS":
        raise RuntimeError("Sealed candidate failed independent verification")
    return manifest


def verify(root: Path) -> dict:
    errors: list[str] = []
    try:
        manifest = json.loads((root / "manifest-v1.json").read_text())
    except Exception as exc:
        return {"schema": "companies-house-bounded-verification-v1", "status": "FAIL", "errors": [f"manifest: {exc}"]}
    expected = {
        "schema": "companies-house-bounded-candidate-v1",
        "generation": GENERATION,
        "generated_at": FIXED_GENERATED_AT,
        "deployment_state": "not-authorised",
        "promotion_eligible": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"manifest {key}")
    if manifest.get("coverage") != {"kind": "bounded-three-month-candidate", "accounts_months": 3, "partial_coverage": True, "annual_bootstrap": False}:
        errors.append("coverage")
    if manifest.get("licence") != OGL:
        errors.append("Open Government Licence attribution")
    if manifest.get("privacy") != {
        "directors": False,
        "individual_psc": False,
        "dates_of_birth": False,
        "residential_addresses": False,
        "credit_scores": False,
        "bankability_scores": False,
    }:
        errors.append("privacy contract")
    inputs = manifest.get("inputs", {})
    if inputs.get("companies_base_commit") != BASE_COMMIT or inputs.get("pipelinenews_commit") != PIPELINENEWS_COMMIT:
        errors.append("input commit boundary")
    if not COMMIT_SHA.fullmatch(str(inputs.get("generation_source_commit", ""))):
        errors.append("generation source SHA")
    files = manifest.get("files", {})
    if set(files) != EXPECTED_CARTRIDGES:
        errors.append("cartridge closure")
    canonical: dict[str, str] = {}
    total_bytes = (root / "manifest-v1.json").stat().st_size
    for name, receipt in files.items():
        path = root / str(receipt.get("path", "__missing__"))
        if not path.is_file():
            errors.append(f"{name}: missing")
            continue
        size = path.stat().st_size
        total_bytes += size
        if size > MAXIMUM_FILE_BYTES or digest(path) != receipt.get("sha256") or size != receipt.get("bytes"):
            errors.append(f"{name}: file receipt")
        payload = json.loads(path.read_text())
        records = payload.get("records")
        if (
            payload.get("schema") != "companies-house-cartridge-v1"
            or payload.get("snapshot_id") != GENERATION
            or payload.get("generated_at") != FIXED_GENERATED_AT
            or payload.get("coverage") != "BOUNDED_THREE_MONTH_CANDIDATE"
            or payload.get("licence") != OGL
            or not isinstance(records, list)
            or len(records) != receipt.get("records")
        ):
            errors.append(f"{name}: payload contract")
            continue
        seen = set()
        for record in records:
            number = str(record.get("company_number", ""))
            if not COMPANY_NUMBER.fullmatch(number) or number in seen:
                errors.append(f"{name}: company number")
            seen.add(number)
            if record.get("classification") not in CLASSIFICATIONS or record.get("financial_currency") != "GBP":
                errors.append(f"{name}: classification/currency")
            leaked = recursive_keys(record).intersection(FORBIDDEN_KEYS)
            if leaked:
                errors.append(f"{name}: privacy")
            for match in record.get("repd_name_candidates", []):
                ref = str(match.get("repd_ref", ""))
                if match.get("gg_project_id") != f"GG2050-REPD-{ref}" and not str(match.get("gg_project_id", "")).endswith(ref):
                    errors.append(f"{name}: project identity")
                atlas = match.get("atlas_url")
                if atlas:
                    parsed = urllib.parse.urlsplit(atlas)
                    query = urllib.parse.parse_qs(parsed.query)
                    if parsed.scheme != "https" or parsed.netloc != "globalgrid2050.com" or parsed.path != "/repd_grid_atlasv8/" or query.get("repd_ref") != [ref]:
                        errors.append(f"{name}: Atlas link")
            serialised = json.dumps(record, sort_keys=True, separators=(",", ":"))
            if number in canonical and canonical[number] != serialised:
                errors.append(f"{name}: cross-cartridge drift")
            canonical[number] = serialised
    evidence = manifest.get("evidence", [])
    expected_evidence = {
        "evidence/download-plan.json",
        "evidence/rest-api.json",
        "evidence/basic-validation.json",
        *{f"evidence/receipt-{index}.json" for index in range(4)},
        *{f"evidence/extraction-{index}.json" for index in range(3)},
    }
    if len(evidence) != 10 or {item.get("path") for item in evidence} != expected_evidence:
        errors.append("evidence closure")
    for receipt in evidence:
        path = root / str(receipt.get("path", "__missing__"))
        if not path.is_file() or digest(path) != receipt.get("sha256") or path.stat().st_size != receipt.get("bytes"):
            errors.append("evidence receipt")
            continue
        total_bytes += path.stat().st_size
    try:
        copied_plan = root / "evidence/download-plan.json"
        plan = load_plan(copied_plan)
        if digest(copied_plan) != inputs.get("download_plan_sha256"):
            errors.append("download plan input receipt")
        rest = load_rest_evidence(root / "evidence/rest-api.json")
        rest_input = inputs.get("optional_rest", {})
        if rest_input != {
            "enabled": rest["enabled"],
            "status": rest["status"],
            "evidence_sha256": digest(root / "evidence/rest-api.json"),
        }:
            errors.append("optional REST input receipt")
        copied_receipts = []
        for index in range(4):
            receipt = json.loads((root / f"evidence/receipt-{index}.json").read_text())
            if receipt.get("index") != index or receipt.get("plan_sha256") != digest(copied_plan):
                errors.append(f"receipt {index} plan binding")
            copied_receipts.append(receipt)
        basic_receipt = next(item for item in copied_receipts if item.get("kind") == "basic")
        load_basic_report(root / "evidence/basic-validation.json", basic_receipt)
        if digest(root / "evidence/basic-validation.json") != inputs.get("basic_validation_sha256"):
            errors.append("basic validation input receipt")
        if basic_receipt.get("sha256") != inputs.get("basic_archive_sha256"):
            errors.append("basic archive input receipt")
        account_receipts = {item.get("filename"): item for item in copied_receipts if item.get("kind") == "accounts"}
        extraction_archives = set()
        for index in range(3):
            report = json.loads((root / f"evidence/extraction-{index}.json").read_text())
            receipt = account_receipts.get(report.get("archive_filename"))
            if (
                not receipt
                or report.get("schema") != "companies-house-bounded-extraction-report-v1"
                or report.get("status") != "PASS"
                or report.get("archive_sha256") != receipt.get("sha256")
                or report.get("archive_bytes") != receipt.get("bytes")
            ):
                errors.append(f"extraction {index} receipt")
            extraction_archives.add(report.get("archive_filename"))
        if extraction_archives != set(account_receipts):
            errors.append("extraction archive closure")
        if plan.get("total_bytes", 12_000_000_001) > 12_000_000_000:
            errors.append("download plan ceiling")
    except Exception as exc:
        errors.append(f"evidence semantics: {exc}")
    if total_bytes > MAXIMUM_TOTAL_BYTES:
        errors.append("candidate byte ceiling")
    if len(canonical) != manifest.get("companies") or not canonical:
        errors.append("company closure")
    return {
        "schema": "companies-house-bounded-verification-v1",
        "generation": GENERATION,
        "status": "FAIL" if errors else "PASS",
        "companies": len(canonical),
        "bytes": total_bytes,
        "errors": errors[:100],
    }


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
                raise RuntimeError("Seal mode requires all frozen bulk, REST-evidence, REPD and source inputs")
            result = seal(
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
            summary = {"schema": result["schema"], "generation": GENERATION, "status": "PASS", "companies": result["companies"]}
        else:
            summary = verify(args.input)
        rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered)
        print(rendered, end="")
        return 0 if summary.get("status") == "PASS" else 1
    except Exception as exc:
        failure = {"schema": "companies-house-bounded-verification-v1", "generation": GENERATION, "status": "FAIL", "errors": [str(exc)]}
        rendered = json.dumps(failure, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered)
        print(rendered, end="", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
