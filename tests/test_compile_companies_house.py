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


def write_fixture(root: Path) -> tuple[Path, Path, Path, Path, Path]:
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
        {"repd_ref": "13599", "gg_project_id": "GG2050-REPD-13599", "name": "Beacon Fen Energy Park", "operator": "Low Carbon Limited", "capacity_mw": 400, "technology": "solar", "status": "Application Submitted", "geometry_status": "valid", "latitude": 52.9, "longitude": -0.2},
        {"repd_ref": "90001", "gg_project_id": "GG2050-REPD-90001", "name": "Old Wind Farm", "operator": "Old Wind Energy Limited", "capacity_mw": 80, "technology": "wind_onshore", "status": "Operational", "geometry_status": "missing", "latitude": None, "longitude": None},
    ]}))
    news=root / "news.json"
    news.write_text(json.dumps({"schema":"globalgrid2050.major-project-news.v9.5.1","canonical_items":[
        {"gg_article_id":"GG2050-NEWS-BEACON","repd_ref":"13599","role":"PRIMARY_MATCH","eligible_for_news_signal":True,"event":"CONSENT","headline":"Beacon Fen consent","published":"2026-08-21","source":"GOV.UK","url":"https://example.test/beacon","confidence":91},
        {"gg_article_id":"GG2050-NEWS-RELATED","repd_ref":"13599","role":"RELATED_DEVELOPMENT","eligible_for_news_signal":False,"event":"PROJECT UPDATE","headline":"Excluded related item","published":"2026-08-22","source":"Example","url":"https://example.test/related","confidence":40},
    ]}))
    return raw, accounts, repd, news, output


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        raw, accounts, repd, news, output = write_fixture(root)
        subprocess.run([
            "python", str(COMPILER), "--raw", str(raw), "--accounts", str(accounts),
            "--repd", str(repd), "--news", str(news), "--output", str(output), "--stamp", "202608270257",
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
        assert records["01234567"]["repd_news_count"] == 1
        beacon=next(item for item in records["01234567"]["repd_name_candidates"] if item["repd_ref"]=="13599")
        assert beacon["atlas_url"].startswith("https://globalgrid2050.com/repd_grid_atlasv8/?repd_ref=13599")
        assert beacon["canonical_news_count"] == 1
        assert beacon["latest_canonical_news"][0]["gg_article_id"] == "GG2050-NEWS-BEACON"
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
        assert manifest["inputs"]["news_sha256"]
        assert manifest["inputs"]["repd"]["files"] == 1
        print(json.dumps({"status": "PASS", "selected_companies": len(records), "cartridges": {key: len(value) for key, value in cartridges.items()}}, sort_keys=True))


if __name__ == "__main__":
    main()
