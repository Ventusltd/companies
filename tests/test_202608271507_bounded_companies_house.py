#!/usr/bin/env python3
"""Deterministic fixtures for the bounded Companies House candidate generation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


PLAN = load("bounded_plan", "build/python/202608271507-freeze-companies-house-plan.py")
DOWNLOAD = load("bounded_download", "build/python/202608271507-download-planned-archive.py")
EXTRACT = load("bounded_extract", "build/python/202608271507-extract-bounded-accounts.py")
VERIFY = load("bounded_verify", "build/python/202608271507-verify-companies-house-candidate.py")


def rejected(callable_, contains: str) -> None:
    try:
        callable_()
    except RuntimeError as exc:
        assert contains.lower() in str(exc).lower(), (contains, str(exc))
        return
    raise AssertionError(f"Expected RuntimeError containing {contains!r}")


def test_source_manifest() -> None:
    path = ROOT / "manifests/202608271507-bounded-companies-house-candidate.json"
    manifest = json.loads(path.read_text())
    assert manifest["generation"] == "202608271507"
    assert manifest["base_commit"] == "145da3dc6ff7541edb008676528636c11ba428ee"
    assert manifest["deployment_state"] == "not-authorised"
    assert len(manifest["source_files"]) == 7
    for receipt in manifest["source_files"]:
        source = ROOT / receipt["path"]
        assert source.is_file(), receipt
        if receipt["sha256"] != "SELF":
            assert hashlib.sha256(source.read_bytes()).hexdigest() == receipt["sha256"], receipt


def test_plan() -> None:
    monthly = [
        f"https://download.companieshouse.gov.uk/Accounts_Monthly_Data-{month}2026.zip"
        for month in ("April", "May", "June", "July")
    ]
    basic = [
        "https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-2026-07-01.zip",
        "https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-2026-08-01.zip",
    ]
    original_probe = PLAN.probe

    def fake_probe(row):
        kind, url = row
        return {
            "kind": kind,
            "url": url,
            "resolved_url": url,
            "filename": url.rsplit("/", 1)[-1],
            "bytes": 2_000_000_000 if kind == "accounts" else 800_000_000,
            "etag": '"fixture"',
            "last_modified": "Thu, 27 Aug 2026 00:00:00 GMT",
        }

    PLAN.probe = fake_probe
    try:
        plan = PLAN.build_plan(monthly, basic)
    finally:
        PLAN.probe = original_probe
    assert plan["generation"] == "202608271507"
    assert plan["total_bytes"] == 6_800_000_000
    assert [row["kind"] for row in plan["files"]] == ["accounts", "accounts", "accounts", "basic"]
    assert "May2026" in plan["files"][0]["filename"]
    rejected(lambda: PLAN.require_official("https://example.test/archive.zip", suffix=".zip"), "outside")
    rejected(
        lambda: PLAN.require_official(
            "https://download.companieshouse.gov.uk/archive.zip?unexpected=1", suffix=".zip"
        ),
        "outside",
    )
    oversize_probe = PLAN.probe

    def too_large(row):
        item = fake_probe(row)
        item["bytes"] = 4_000_000_001
        return item

    PLAN.probe = too_large
    try:
        rejected(lambda: PLAN.build_plan(monthly, basic), "per-file")
    finally:
        PLAN.probe = oversize_probe


def test_optional_rest_skips_without_secret(root: Path) -> None:
    previous = os.environ.pop("COMPANIES_HOUSE_API_KEY", None)
    try:
        evidence = PLAN.optional_rest_evidence(root / "rest-evidence.json")
    finally:
        if previous is not None:
            os.environ["COMPANIES_HOUSE_API_KEY"] = previous
    assert evidence == {
        "schema": "companies-house-optional-rest-evidence-v1",
        "generation": "202608271507",
        "endpoint": "https://api.company-information.service.gov.uk/company/00000006",
        "enabled": False,
        "status": "SKIPPED",
        "reason": "optional-secret-not-configured",
    }


def fixture_plan(root: Path) -> tuple[Path, list[dict]]:
    files = []
    for index in range(4):
        kind = "accounts" if index < 3 else "basic"
        filename = f"Accounts_Monthly_Data-{index}.zip" if kind == "accounts" else "BasicCompanyDataAsOneFile-2026-08-01.zip"
        url = f"https://download.companieshouse.gov.uk/{filename}"
        files.append(
            {
                "kind": kind,
                "url": url,
                "resolved_url": url,
                "filename": filename,
                "bytes": 2048 + index,
                "etag": f'"fixture-{index}"',
                "last_modified": "Thu, 27 Aug 2026 00:00:00 GMT",
            }
        )
    plan = {
        "schema": "companies-house-bounded-download-plan-v1",
        "generation": "202608271507",
        "base_commit": "145da3dc6ff7541edb008676528636c11ba428ee",
        "deployment_state": "not-authorised",
        "planned_at": "2026-08-27T14:07:00+00:00",
        "official_host": "download.companieshouse.gov.uk",
        "accounts_months": 3,
        "file_limit": 4,
        "maximum_archive_bytes": 4_000_000_000,
        "maximum_total_bytes": 12_000_000_000,
        "total_bytes": sum(row["bytes"] for row in files),
        "files": files,
        "licence": PLAN.OGL,
    }
    path = root / "plan.json"
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    return path, files


def test_download_plan_loading(root: Path) -> None:
    plan_path, files = fixture_plan(root)
    plan, item = DOWNLOAD.load_item(plan_path, 2)
    assert plan["generation"] == "202608271507"
    assert item == files[2]
    rejected(lambda: DOWNLOAD.load_item(plan_path, 4), "range")
    unsafe = json.loads(plan_path.read_text())
    unsafe["files"][0]["filename"] = "../archive.zip"
    plan_path.write_text(json.dumps(unsafe))
    rejected(lambda: DOWNLOAD.load_item(plan_path, 0), "unsafe")
    plan_path, _files = fixture_plan(root)
    bad = json.loads(plan_path.read_text())
    bad["deployment_state"] = "authorised"
    plan_path.write_text(json.dumps(bad))
    rejected(lambda: DOWNLOAD.load_item(plan_path, 0), "quarantined")


def xbrl(company_number: str, total_assets: int, date: str) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<xbrl>
  <context id="c1"><period><instant>{date}</instant></period></context>
  <TotalAssets contextRef="c1">{total_assets}</TotalAssets>
  <NetAssetsLiabilities contextRef="c1">5000000</NetAssetsLiabilities>
</xbrl>
""".encode()


def test_extractor(root: Path) -> None:
    archive = root / "Accounts_Monthly_Data-Fixture.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("Prod_01234567_20251231.xml", xbrl("01234567", 15_000_000, "2025-12-31"))
        handle.writestr("Prod_AB123456_20260131.xml", xbrl("AB123456", 20_000_000, "2026-01-31"))
        handle.writestr("padding.bin", bytes(range(256)) * 8, compress_type=zipfile.ZIP_STORED)
    output = root / "accounts.ndjson"
    report = root / "extraction.json"
    result = EXTRACT.extract(archive, output, report)
    assert result["status"] == "PASS"
    assert result["records"] == 2
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert records[0]["company_number"] == "01234567"
    assert records[0]["total_assets"] == 15_000_000
    second = root / "accounts-second.ndjson"
    second_report = root / "extraction-second.json"
    EXTRACT.extract(archive, second, second_report)
    assert output.read_bytes() == second.read_bytes()
    unsafe = zipfile.ZipInfo("../escape.xml")
    rejected(lambda: EXTRACT.validate_member(unsafe, {"members": 0, "expanded_bytes": 0}), "unsafe")
    bomb = zipfile.ZipInfo("bomb.xml")
    bomb.file_size = 10_000
    bomb.compress_size = 1
    rejected(lambda: EXTRACT.validate_member(bomb, {"members": 0, "expanded_bytes": 0}), "ratio")
    duplicate = root / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(duplicate, "w") as handle:
            handle.writestr("Prod_01234567_20251231.xml", xbrl("01234567", 1, "2025-12-31"))
            handle.writestr("Prod_01234567_20251231.xml", xbrl("01234567", 2, "2025-12-31"))
            handle.writestr("padding.bin", bytes(range(256)) * 8, compress_type=zipfile.ZIP_STORED)
    rejected(lambda: EXTRACT.extract(duplicate, root / "duplicate.ndjson", root / "duplicate.json"), "duplicate")
    basic = root / "BasicCompanyDataAsOneFile-2026-08-01.zip"
    with zipfile.ZipFile(basic, "w") as handle:
        handle.writestr(
            "BasicCompanyDataAsOneFile-2026-08-01.csv",
            "CompanyName,CompanyNumber\nTEST LIMITED,01234567\n" * 30,
            compress_type=zipfile.ZIP_STORED,
        )
    basic_report = EXTRACT.validate_basic_snapshot(basic, root / "basic-validation.json")
    assert basic_report["status"] == "PASS"
    assert basic_report["csv_members"] == 1


def write_verifier_fixture(root: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
    plan_path, files = fixture_plan(root)
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    evidence = root / "evidence-input"
    evidence.mkdir()
    archive_hashes = {}
    basic = root / "basic"
    basic.mkdir()
    for index, item in enumerate(files):
        if item["kind"] == "basic":
            basic_archive = basic / item["filename"]
            basic_archive.write_bytes((f"basic-{index}".encode() * 512)[: item["bytes"]].ljust(item["bytes"], b"x"))
            archive_hash = hashlib.sha256(basic_archive.read_bytes()).hexdigest()
        else:
            archive_hash = hashlib.sha256(f"archive-{index}".encode()).hexdigest()
        archive_hashes[item["filename"]] = archive_hash
        receipt = {
            "schema": "companies-house-bounded-download-receipt-v1",
            "generation": "202608271507",
            "base_commit": "145da3dc6ff7541edb008676528636c11ba428ee",
            "plan_sha256": plan_sha,
            "index": index,
            **item,
            "sha256": archive_hash,
            "retrieved_at": "2026-08-27T14:07:00+00:00",
        }
        (evidence / f"receipt-{index}.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        if item["kind"] == "accounts":
            ndjson = evidence / f"accounts-{index}.ndjson"
            ndjson.write_text(
                json.dumps({"company_number": f"0000000{index + 1}", "accounts_date": "2025-12-31", "total_assets": 15_000_000})
                + "\n"
            )
            extraction = {
                "schema": "companies-house-bounded-extraction-report-v1",
                "generation": "202608271507",
                "status": "PASS",
                "archive_filename": item["filename"],
                "archive_bytes": item["bytes"],
                "archive_sha256": archive_hash,
                "records": 1,
                "parse_error_rate": 0,
                "output_sha256": hashlib.sha256(ndjson.read_bytes()).hexdigest(),
            }
            (evidence / f"extraction-{index}.json").write_text(json.dumps(extraction, indent=2, sort_keys=True) + "\n")
    rest_evidence = root / "rest-evidence.json"
    rest_evidence.write_text(
        json.dumps(
            {
                "schema": "companies-house-optional-rest-evidence-v1",
                "generation": "202608271507",
                "endpoint": "https://api.company-information.service.gov.uk/company/00000006",
                "enabled": False,
                "status": "SKIPPED",
                "reason": "optional-secret-not-configured",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    basic_item = next(item for item in files if item["kind"] == "basic")
    basic_report = evidence / "basic-validation.json"
    basic_report.write_text(
        json.dumps(
            {
                "schema": "companies-house-bounded-basic-validation-v1",
                "generation": "202608271507",
                "status": "PASS",
                "archive_filename": basic_item["filename"],
                "archive_bytes": basic_item["bytes"],
                "archive_sha256": archive_hashes[basic_item["filename"]],
                "members": 1,
                "csv_members": 1,
                "expanded_bytes": 4096,
                "completed_at": "2026-08-27T14:07:00+00:00",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    repd = root / "repd"
    repd.mkdir()
    (repd / "projects.json").write_text(
        json.dumps(
            {
                "projects": [
                    {
                        "repd_ref": "13599",
                        "gg_project_id": "GG2050-REPD-13599",
                        "name": "Beacon Fen Energy Park",
                        "operator": "Low Carbon Limited",
                        "technology": "solar",
                        "capacity_mw": 400,
                        "status": "Application Submitted",
                        "geometry_status": "valid",
                        "latitude": 52.9,
                        "longitude": -0.2,
                    }
                ]
            }
        )
    )
    raw = root / "raw"
    raw.mkdir()
    record = {
        "company_name": "LOW CARBON LIMITED",
        "company_number": "01234567",
        "company_status": "Active",
        "sic_codes": ["35110 - Production of electricity"],
        "accounts_date": "2025-12-31",
        "total_assets": 15_000_000,
        "net_assets": 8_000_000,
        "assets_gte_10m": True,
        "energy_relevant_large_company": True,
        "btm_tags": ["INDUSTRIAL_SIC_B_TO_E"],
        "repd_name_candidates": [
            {
                "repd_ref": "13599",
                "project": "Beacon Fen Energy Park",
                "operator": "Low Carbon Limited",
                "capacity_mw": 400,
                "match_type": "EXACT_OPERATOR_NAME",
            }
        ],
        "probable_project_spv": False,
    }
    raw_files = {}
    for name in sorted(VERIFY.EXPECTED_CARTRIDGES):
        path = raw / f"{name}-v1.json"
        path.write_text(json.dumps({"schema": "companies-house-cartridge-v1", "records": [record]}))
        raw_files[name] = {"path": path.name, "records": 1, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (raw / "manifest-v1.json").write_text(json.dumps({"schema": "companies-house-manifest-v1", "files": raw_files}))
    accounts = root / "accounts-latest.ndjson"
    accounts.write_text(json.dumps({"company_number": "01234567", "accounts_date": "2025-12-31", "total_assets": 15_000_000}) + "\n")
    return plan_path, evidence, repd, raw, basic, accounts, rest_evidence, basic_report


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_verifier(root: Path) -> None:
    plan, evidence, repd, raw, basic, accounts, rest_evidence, basic_report = write_verifier_fixture(root)
    first = root / "candidate-a"
    second = root / "candidate-b"
    source_commit = "a" * 40
    VERIFY.seal(raw, first, plan, evidence, evidence, repd, basic, accounts, rest_evidence, basic_report, source_commit)
    VERIFY.seal(raw, second, plan, evidence, evidence, repd, basic, accounts, rest_evidence, basic_report, source_commit)
    assert tree_bytes(first) == tree_bytes(second)
    verification = VERIFY.verify(first)
    assert verification["status"] == "PASS", verification
    record = json.loads((first / "repd-linked-v1.json").read_text())["records"][0]
    assert record["classification"] == "REPD_NAME_CANDIDATE"
    assert record["repd_name_candidates"][0]["atlas_url"].startswith(
        "https://globalgrid2050.com/repd_grid_atlasv8/?repd_ref=13599"
    )
    assert json.loads((first / "manifest-v1.json").read_text())["deployment_state"] == "not-authorised"
    raw_record_path = raw / "repd-linked-v1.json"
    payload = json.loads(raw_record_path.read_text())
    payload["records"][0]["director_name"] = "Forbidden"
    raw_record_path.write_text(json.dumps(payload))
    raw_manifest_path = raw / "manifest-v1.json"
    raw_manifest = json.loads(raw_manifest_path.read_text())
    raw_manifest["files"]["repd-linked"]["sha256"] = hashlib.sha256(raw_record_path.read_bytes()).hexdigest()
    raw_manifest_path.write_text(json.dumps(raw_manifest))
    rejected(
        lambda: VERIFY.seal(
            raw,
            root / "privacy-rejected",
            plan,
            evidence,
            evidence,
            repd,
            basic,
            accounts,
            rest_evidence,
            basic_report,
            source_commit,
        ),
        "prohibited",
    )


def main() -> None:
    test_source_manifest()
    test_plan()
    with tempfile.TemporaryDirectory() as temporary:
        test_download_plan_loading(Path(temporary))
    with tempfile.TemporaryDirectory() as temporary:
        test_optional_rest_skips_without_secret(Path(temporary))
    with tempfile.TemporaryDirectory() as temporary:
        test_extractor(Path(temporary))
    with tempfile.TemporaryDirectory() as temporary:
        test_verifier(Path(temporary))
    print(json.dumps({"status": "PASS", "generation": "202608271507", "fixtures": 6, "network_requests": 0}))


if __name__ == "__main__":
    main()
