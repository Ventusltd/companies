#!/usr/bin/env python3
"""Fail closed on Companies House cartridge, identity and privacy drift."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

COMPANY_NUMBER = re.compile(r"^(?:[A-Z]{2}\d{6}|\d{8})$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CLASSIFICATIONS = {
    "CONFIRMED_REPD_COMPANY",
    "PROBABLE_PROJECT_SPV",
    "RENEWABLE_COMPANY",
    "UNRESOLVED_CANDIDATE",
}
MATCH_TYPES = {"EXACT_OPERATOR_NAME", "EXACT_PROJECT_NAME", "PROJECT_NAME_SPV_CANDIDATE"}
FORBIDDEN_KEYS = {
    "director_name",
    "date_of_birth",
    "residential_address",
    "individual_psc",
    "confirmed_energy_demand",
    "credit_score",
    "bankability_score",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from keys(child)


def verify(root: Path) -> dict:
    errors = []
    manifest_path = root / "manifest-v1.json"
    if not manifest_path.is_file():
        return {"schema": "companies-house-verification-v1", "status": "FAIL", "errors": ["manifest-v1.json missing"]}
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "companies-house-manifest-v1": errors.append("manifest schema")
    if manifest.get("threshold_gbp") != 10_000_000: errors.append("threshold_gbp")
    if manifest.get("financial_currency") != "GBP": errors.append("financial_currency")
    inputs = manifest.get("inputs", {})
    for label, value in (("accounts_sha256", inputs.get("accounts_sha256")), ("news_sha256", inputs.get("news_sha256")), ("repd.sha256", inputs.get("repd", {}).get("sha256"))):
        if not isinstance(value, str) or not SHA256.fullmatch(value): errors.append(label)
    if "NEWS can never establish" not in inputs.get("identity_rule", "") and "news only annotates" not in inputs.get("identity_rule", ""):
        errors.append("identity_rule")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files: errors.append("manifest files")
    canonical = {}
    cartridge_counts = {}
    for cartridge, receipt in (files or {}).items():
        relative = receipt.get("path", "")
        if Path(relative).name != relative or not relative.endswith(".json"):
            errors.append(f"{cartridge}: unsafe path"); continue
        path = root / relative
        if not path.is_file(): errors.append(f"{cartridge}: missing"); continue
        if digest(path) != receipt.get("sha256"): errors.append(f"{cartridge}: sha256")
        payload = json.loads(path.read_text())
        if payload.get("schema") != "companies-house-cartridge-v1": errors.append(f"{cartridge}: schema")
        records = payload.get("records")
        if not isinstance(records, list): errors.append(f"{cartridge}: records"); continue
        if len(records) != receipt.get("records"): errors.append(f"{cartridge}: count")
        cartridge_counts[cartridge] = len(records)
        seen = set()
        for index, record in enumerate(records):
            prefix = f"{cartridge}[{index}]"
            number = record.get("company_number", "")
            if not COMPANY_NUMBER.fullmatch(number): errors.append(f"{prefix}: company_number")
            if number in seen: errors.append(f"{prefix}: duplicate company_number")
            seen.add(number)
            serialised = json.dumps(record, sort_keys=True, separators=(",", ":"))
            if number in canonical and canonical[number] != serialised: errors.append(f"{prefix}: cross-cartridge drift")
            canonical[number] = serialised
            leaked = FORBIDDEN_KEYS.intersection(keys(record))
            if leaked: errors.append(f"{prefix}: forbidden {sorted(leaked)}")
            if record.get("classification") not in CLASSIFICATIONS: errors.append(f"{prefix}: classification")
            if record.get("financial_currency") != "GBP": errors.append(f"{prefix}: currency")
            matches = record.get("repd_name_candidates", [])
            if record.get("repd_news_count", 0) and not matches: errors.append(f"{prefix}: NEWS without REPD")
            for match in matches:
                if match.get("match_type") not in MATCH_TYPES: errors.append(f"{prefix}: match_type")
                ref = str(match.get("repd_ref", ""))
                atlas = match.get("atlas_url")
                if atlas:
                    parsed = urlparse(atlas); query = parse_qs(parsed.query)
                    if parsed.scheme != "https" or parsed.netloc != "globalgrid2050.com" or parsed.path != "/repd_grid_atlasv8/": errors.append(f"{prefix}: atlas host")
                    if query.get("repd_ref") != [ref]: errors.append(f"{prefix}: atlas repd_ref")
                elif match.get("latitude") is not None or match.get("longitude") is not None:
                    errors.append(f"{prefix}: atlas missing")
                news = match.get("latest_canonical_news", [])
                if match.get("canonical_news_count", 0) < len(news): errors.append(f"{prefix}: news count")
                for item in news:
                    if item.get("role") != "PRIMARY_MATCH" or not item.get("gg_article_id"): errors.append(f"{prefix}: non-primary NEWS")
            if cartridge == "industrial-assets-gte-10m" and (not record.get("assets_gte_10m") or "INDUSTRIAL_SIC_B_TO_E" not in record.get("btm_tags", [])):
                errors.append(f"{prefix}: industrial gate")
            if cartridge == "energy-relevant-assets-gte-10m" and not record.get("energy_relevant_large_company"):
                errors.append(f"{prefix}: energy-relevant gate")
            if cartridge == "repd-linked" and not matches: errors.append(f"{prefix}: REPD gate")
            if cartridge == "project-spv-candidates" and record.get("classification") != "PROBABLE_PROJECT_SPV": errors.append(f"{prefix}: SPV gate")
            if cartridge == "btm-opportunities":
                if not record.get("btm_opportunity") or not any(tag.startswith("BTM_") for tag in record.get("btm_tags", [])):
                    errors.append(f"{prefix}: BTM gate")
    privacy = manifest.get("privacy", {})
    if privacy != {"directors": False, "individual_psc": False, "residential_addresses": False}: errors.append("privacy contract")
    return {"schema": "companies-house-verification-v1", "status": "FAIL" if errors else "PASS", "companies": len(canonical), "cartridges": cartridge_counts, "errors": errors[:100]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    report = verify(Path(args.input))
    rendered = json.dumps(report, indent=2) + "\n"
    if args.report: Path(args.report).write_text(rendered)
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
