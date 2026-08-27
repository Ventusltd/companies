#!/usr/bin/env python3
"""Small deterministic end-to-end gate for the Companies House compiler."""
from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "build/python/202608262245-compile-companies-house.py"


def write_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    raw = root / "raw"
    repd = root / "repd"
    output = root / "output"
    raw.mkdir()
    repd.mkdir()
    rows = [
        {"CompanyName": "LOW CARBON LIMITED", "CompanyNumber": "01234567", "CompanyStatus": "Active", "RegAddress.PostCode": "SW1A 1AA", "SICCode.SicText_1": "35110 - Production of electricity"},
        {"CompanyName": "BEACON FEN SOLAR FARM LIMITED", "CompanyNumber": "AB123456", "CompanyStatus": "Active", "RegAddress.PostCode": "PE20 1AA", "SICCode.SicText_1": "35110 - Production of electricity"},
        {"CompanyName": "GENERIC PROPERTY HOLDINGS LIMITED", "CompanyNumber": "11111111", "CompanyStatus": "Active", "RegAddress.PostCode": "W1 1AA", "SICCode.SicText_1": "68209 - Other letting"},
        {"CompanyName": "ACME GLASS LIMITED", "CompanyNumber": "22222222", "CompanyStatus": "Active", "RegAddress.PostCode": "S1 1AA", "SICCode.SicText_1": "23190 - Manufacture of other glass"},
        {"CompanyName": "NEWCO LIMITED", "CompanyNumber": "87654321", "CompanyStatus": "Active", "RegAddress.PostCode": "AB1 1AA", "SICCode.SicText_1": "70100 - Head offices", "PreviousName_1.CompanyName": "OLD WIND ENERGY LIMITED"},
    ]
    csv_path = root / "BasicCompanyData.csv"
    fieldnames = sorted({key for row in rows for key in row})
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with zipfile.ZipFile(raw / "BasicCompanyDataAsOneFile-2026-08-01.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(csv_path, csv_path.name)
    accounts = root / "accounts.ndjson"
    facts = [
        {"company_number": "01234567", "accounts_date": "2025-12-31", "total_assets": 15_000_000, "net_assets": 8_000_000},
        {"company_number": "AB123456", "accounts_date": "2025-12-31", "total_assets": 1_000_000, "net_assets": 500_000},
        {"company_number": "11111111", "accounts_date": "2025-12-31", "total_assets": 25_000_000, "net_assets": 20_000_000},
        {"company_number": "22222222", "accounts_date": "2025-12-31", "total_assets": 9_000_000, "net_assets": 20_000_000},
        {"company_number": "87654321", "accounts_date": "2025-12-31", "total_assets": 1_000_000, "net_assets": 500_000},
    ]
    accounts.write_text("".join(json.dumps(row) + "\n" for row in facts))
    (repd / "projects.json").write_text(json.dumps({"projects": [
        {"repd_ref": "13599", "name": "Beacon Fen Energy Park", "operator": "Low Carbon Limited", "capacity_mw": 400},
        {"repd_ref": "90001", "name": "Old Wind Farm", "operator": "Old Wind Energy Limited", "capacity_mw": 80},
    ]}))
    return raw, accounts, repd, output


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        raw, accounts, repd, output = write_fixture(root)
        subprocess.run([
            "python", str(COMPILER), "--raw", str(raw), "--accounts", str(accounts),
            "--repd", str(repd), "--output", str(output), "--stamp", "202608270257",
        ], check=True)
        cartridges = {}
        for path in output.glob("*-v1.json"):
            if path.name == "manifest-v1.json":
                continue
            cartridges[path.stem.removesuffix("-v1")] = json.loads(path.read_text())["records"]
        assert len(cartridges["industrial-assets-gte-10m"]) == 2
        assert len(cartridges["repd-linked"]) == 3
        assert len(cartridges["project-spv-candidates"]) == 1
        assert len(cartridges["btm-opportunities"]) == 1
        records = {row["company_number"]: row for rows in cartridges.values() for row in rows}
        assert "11111111" not in records
        assert records["01234567"]["classification"] == "CONFIRMED_REPD_COMPANY"
        assert records["AB123456"]["classification"] == "PROBABLE_PROJECT_SPV"
        assert records["22222222"]["classification"] == "UNRESOLVED_CANDIDATE"
        assert records["87654321"]["classification"] == "CONFIRMED_REPD_COMPANY"
        assert "PREVIOUS_LEGAL_NAME_MATCH" in records["87654321"]["evidence"]
        assert "BTM_GLASS_CEMENT_MINERALS" in records["22222222"]["btm_tags"]
        forbidden = {"director_name", "date_of_birth", "residential_address", "individual_psc"}
        assert not forbidden.intersection({key for row in records.values() for key in row})
        manifest = json.loads((output / "manifest-v1.json").read_text())
        assert manifest["schema"] == "companies-house-manifest-v1"
        assert manifest["financial_currency"] == "GBP"
        print(json.dumps({"status": "PASS", "selected_companies": len(records), "cartridges": {key: len(value) for key, value in cartridges.items()}}, sort_keys=True))


if __name__ == "__main__":
    main()
