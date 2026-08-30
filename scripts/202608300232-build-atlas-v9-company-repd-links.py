#!/usr/bin/env python3
"""Build compact deterministic Companies ↔ REPD ↔ Atlas V9 deep-link relations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urlparse

import duckdb

MIN_RENDER_READY_GENERATION = "202608292311"
VALID_TECHNOLOGIES = {"solar", "bess", "wind_onshore", "wind_offshore"}
PARQUET_ROOTS = {"data", "derived", "reports", "relationships", "outputs", "output"}
EXCLUDED_PARTS = {"raw", "bulk", "archive", "archives", "cache", "downloads", "work", "tmp", "node_modules", ".git"}
TEXT_EXTENSIONS = {".html", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".json"}
SOURCE_ROOTS = {"ui", "src", "javascript", "templates", "compiler", "app", "public", "scripts"}
TIMESTAMPED = re.compile(r"^\d{12}(?:-|$)")
MAX_INPUT_BYTES = 100 * 1024 * 1024
OLD_BASES = (
    "https://globalgrid2050.com/repd_grid_atlasv8/",
    "https://globalgrid2050.com/repd_grid_atlasv8",
    "http://globalgrid2050.com/repd_grid_atlasv8/",
    "http://globalgrid2050.com/repd_grid_atlasv8",
)
OLD_V9 = re.compile(r"https://ventusltd\.github\.io/gridatlas/\d{12}-atlas-v9/?")
REF_COLUMNS = ("repd_ref", "repd_reference", "repd_ref_id", "repd_reference_id", "ref_id")
TECH_COLUMNS = ("technology", "tech", "repd_technology", "technology_type")
COMPANY_COLUMNS = ("company_number", "company_no", "companies_house_number", "ch_company_number")
ROLE_COLUMNS = ("role", "company_role", "relationship_role", "relationship_type")
STATUS_COLUMNS = ("status", "match_status", "relationship_status", "method_status")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def first_column(columns: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
    return None


def normalise_company_number(value: object) -> str | None:
    text = re.sub(r"\s+", "", str(value or "").upper())
    return text if re.fullmatch(r"[A-Z0-9]{6,10}", text) else None


def normalise_ref(value: object) -> str | None:
    text = str(value or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9-]{1,40}", text) else None


def normalise_technology(value: object) -> str | None:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    if "solar" in text or text in {"pv", "photovoltaic"}:
        return "solar"
    if "battery" in text or "bess" in text or "storage" in text:
        return "bess"
    if "wind" in text and "offshore" in text:
        return "wind_offshore"
    if "wind" in text and "onshore" in text:
        return "wind_onshore"
    return None


def normalise_base(value: str) -> str:
    parsed = urlparse(value)
    require(parsed.scheme == "https", "Atlas base must use HTTPS")
    require(parsed.netloc in {"globalgrid2050.com", "www.globalgrid2050.com"}, "Atlas base must use GlobalGrid2050")
    require(re.fullmatch(r"/\d{12}-atlas-v9/", parsed.path) is not None, "Atlas base is not immutable")
    return value.rstrip("/") + "/"


def build_url(base: str, repd_ref: str, technology: str) -> str:
    require(technology in VALID_TECHNOLOGIES, "invalid Atlas technology")
    return base + "?" + urlencode({"repd_ref": repd_ref, "technology": technology})


def candidate_parquets(root: Path) -> Iterable[Path]:
    for top in sorted(PARQUET_ROOTS):
        directory = root / top
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.parquet")):
            relative = path.relative_to(root)
            lower_parts = {part.lower() for part in relative.parts}
            if lower_parts & EXCLUDED_PARTS:
                continue
            if path.name == "atlas_v9_company_repd_links.parquet":
                continue
            if path.stat().st_size > MAX_INPUT_BYTES:
                continue
            yield path


def mutable_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        relative = path.relative_to(root)
        first = relative.parts[0]
        if first in {".git", ".github", "node_modules", "archive", "archives", "releases", "data", "derived", "reports", "state"}:
            continue
        if TIMESTAMPED.match(first):
            continue
        if len(relative.parts) > 1 and first not in SOURCE_ROOTS:
            continue
        if relative.as_posix() == "scripts/202608300232-build-atlas-v9-company-repd-links.py":
            continue
        yield path


def rewrite_sources(root: Path, base_url: str) -> tuple[list[str], int]:
    changed: list[str] = []
    replacements = 0
    for path in mutable_text_files(root):
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = original
        count = 0
        for old in OLD_BASES:
            occurrences = updated.count(old)
            if occurrences:
                updated = updated.replace(old, base_url)
                count += occurrences
        updated, v9_count = OLD_V9.subn(base_url, updated)
        count += v9_count
        if count:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(root).as_posix())
            replacements += count
    return changed, replacements


def extract_rows(connection: duckdb.DuckDBPyConnection, root: Path, path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    escaped = sql_path(path)
    description = connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{escaped}')").fetchall()
    names = [str(row[0]) for row in description]
    columns = {name.lower(): name for name in names}
    ref_column = first_column(columns, REF_COLUMNS)
    tech_column = first_column(columns, TECH_COLUMNS)
    company_column = first_column(columns, COMPANY_COLUMNS)
    role_column = first_column(columns, ROLE_COLUMNS)
    status_column = first_column(columns, STATUS_COLUMNS)
    source = path.relative_to(root).as_posix()
    evidence = {
        "path": source,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "columns": names,
        "eligible": bool(ref_column and tech_column and company_column),
        "rows_scanned": 0,
        "rows_linked": 0,
        "rows_abstained": 0,
    }
    if not evidence["eligible"]:
        return [], evidence

    projections = [
        f"CAST({quote_identifier(company_column)} AS VARCHAR) AS company_number",
        f"CAST({quote_identifier(ref_column)} AS VARCHAR) AS repd_ref",
        f"CAST({quote_identifier(tech_column)} AS VARCHAR) AS technology",
        f"CAST({quote_identifier(role_column)} AS VARCHAR) AS role" if role_column else "NULL::VARCHAR AS role",
        f"CAST({quote_identifier(status_column)} AS VARCHAR) AS source_status" if status_column else "NULL::VARCHAR AS source_status",
    ]
    result = connection.execute(
        f"SELECT {', '.join(projections)} FROM read_parquet('{escaped}')"
    ).fetchall()
    linked: list[dict[str, str]] = []
    for company_value, ref_value, tech_value, role_value, source_status_value in result:
        evidence["rows_scanned"] += 1
        company_number = normalise_company_number(company_value)
        repd_ref = normalise_ref(ref_value)
        technology = normalise_technology(tech_value)
        if not company_number or not repd_ref or not technology:
            evidence["rows_abstained"] += 1
            continue
        role = str(role_value or "").strip()[:120]
        source_status = str(source_status_value or "").strip()[:120]
        linked.append({
            "relationship_id": stable_id(company_number, repd_ref, technology, source),
            "company_number": company_number,
            "repd_ref": repd_ref,
            "technology": technology,
            "role": role,
            "source_status": source_status,
            "source_artifact": source,
            "evidence_class": "OFFICIAL_REPD_REFERENCE_RELATION",
            "link_status": "LINKED",
        })
        evidence["rows_linked"] += 1
    return linked, evidence


def write_parquet(connection: duckdb.DuckDBPyConnection, rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    jsonl = output.with_suffix(".jsonl.tmp")
    with jsonl.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    escaped_jsonl = sql_path(jsonl)
    escaped_output = sql_path(output)
    if rows:
        connection.execute(
            f"""
            COPY (
              SELECT relationship_id, company_number, repd_ref, technology, role,
                     source_status, source_artifact, evidence_class, link_status,
                     atlas_v9_url, producer
              FROM read_json_auto('{escaped_jsonl}', format='newline_delimited')
              ORDER BY company_number, repd_ref, technology, source_artifact
            ) TO '{escaped_output}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 10000)
            """
        )
    else:
        connection.execute(
            f"""
            COPY (
              SELECT
                NULL::VARCHAR AS relationship_id,
                NULL::VARCHAR AS company_number,
                NULL::VARCHAR AS repd_ref,
                NULL::VARCHAR AS technology,
                NULL::VARCHAR AS role,
                NULL::VARCHAR AS source_status,
                NULL::VARCHAR AS source_artifact,
                NULL::VARCHAR AS evidence_class,
                NULL::VARCHAR AS link_status,
                NULL::VARCHAR AS atlas_v9_url,
                NULL::VARCHAR AS producer
              WHERE FALSE
            ) TO '{escaped_output}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    jsonl.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gridatlas", required=True, type=Path)
    parser.add_argument("--globalgrid", required=True, type=Path)
    parser.add_argument("--repo-root", default=".", type=Path)
    args = parser.parse_args()

    atlas_state = load(args.gridatlas / "state/live-set.json")
    generation = str(atlas_state.get("generation") or "")
    if generation < MIN_RENDER_READY_GENERATION:
        print(json.dumps({"classification": "WAITING_FOR_RENDER_READY_PROMOTION", "generation": generation}, sort_keys=True))
        return 0
    verification = atlas_state.get("verification") or {}
    current = atlas_state.get("current") or {}
    require(verification.get("promotion_eligible") is True, "Atlas release is not promotion eligible")
    require(int(verification.get("failed_gates", -1)) == 0, "Atlas release has failed gates")
    release_id = str(current.get("release_id") or "")
    require(re.fullmatch(r"\d{12}-atlas-v9", release_id) is not None, "invalid Atlas release id")

    global_pointer = load(args.globalgrid / "state/gridatlas-v9-current.json")
    require(global_pointer.get("release_id") == release_id, "GlobalGrid mirror and Atlas pointer disagree")
    require(global_pointer.get("classification") == "MIRRORED_PROMOTED_GRIDATLAS_V9", "GlobalGrid mirror is not promoted")
    base_url = normalise_base(str(global_pointer.get("globalgrid_live_url") or ""))

    root = args.repo_root.resolve()
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=1")
    connection.execute("SET preserve_insertion_order=true")
    all_rows: list[dict[str, str]] = []
    sources: list[dict[str, Any]] = []
    for path in candidate_parquets(root):
        rows, evidence = extract_rows(connection, root, path)
        all_rows.extend(rows)
        sources.append(evidence)

    unique: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for row in all_rows:
        row["atlas_v9_url"] = build_url(base_url, row["repd_ref"], row["technology"])
        row["producer"] = "companies/scripts/202608300232-build-atlas-v9-company-repd-links.py"
        key = (row["company_number"], row["repd_ref"], row["technology"], row["source_artifact"])
        unique[key] = row
    rows = [unique[key] for key in sorted(unique)]

    output = root / "derived/atlas_v9_company_repd_links.parquet"
    write_parquet(connection, rows, output)
    linked_count = int(connection.execute(f"SELECT count(*) FROM read_parquet('{sql_path(output)}')").fetchone()[0])
    require(linked_count == len(rows), "derived Parquet row closure mismatch")
    connection.close()

    changed_sources, replacement_count = rewrite_sources(root, base_url)
    pointer = {
        "schema": "companies.atlas-v9-pointer.v1",
        "classification": "PROMOTED_ATLAS_V9_RELATION_SOURCE",
        "generation": generation,
        "release_id": release_id,
        "base_url": base_url,
        "privacy": "NO_PERSONAL_DATA",
        "raw_companies_house_data_stored": False,
    }
    pointer_path = root / "state/atlas-v9-current.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    manifest = {
        "schema": "companies.atlas-v9-company-repd-links-manifest.v1",
        "classification": "DETERMINISTIC_COMPACT_RELATION_BUILT",
        "generation": generation,
        "release_id": release_id,
        "base_url": base_url,
        "output": output.relative_to(root).as_posix(),
        "output_rows": linked_count,
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "compression": "ZSTD",
        "source_files": sources,
        "source_rows_scanned": sum(int(item["rows_scanned"]) for item in sources),
        "source_rows_linked_before_deduplication": sum(int(item["rows_linked"]) for item in sources),
        "source_rows_abstained": sum(int(item["rows_abstained"]) for item in sources),
        "mutable_source_files_rewritten": sorted(changed_sources),
        "mutable_source_replacement_count": replacement_count,
        "raw_companies_house_data_stored": False,
        "personal_data": False,
        "columns": [
            "relationship_id", "company_number", "repd_ref", "technology", "role",
            "source_status", "source_artifact", "evidence_class", "link_status",
            "atlas_v9_url", "producer"
        ],
    }
    manifest_path = root / "reports/atlas-v9-company-repd-links-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(f"COMPANIES_ATLAS_V9_BUILD_FAILED: {error}", file=sys.stderr)
        raise
