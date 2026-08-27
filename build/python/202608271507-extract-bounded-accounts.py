#!/usr/bin/env python3
"""Bounded, receipt-producing extraction of selected public XBRL account facts."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

GENERATION = "202608271507"
MAX_ARCHIVE_BYTES = 4_000_000_000
MAX_MEMBERS = 2_000_000
MAX_TOTAL_EXPANDED_BYTES = 60_000_000_000
MAX_MEMBER_BYTES = 32_000_000
MAX_BASIC_MEMBERS = 16
MAX_BASIC_EXPANDED_BYTES = 12_000_000_000
MAX_NESTED_ZIP_BYTES = 100_000_000
MAX_COMPRESSION_RATIO = 250
MAX_NESTING = 1
MAX_PARSE_ERROR_RATE = 0.02
COMPANY_NUMBER = re.compile(r"(?:^|_)([A-Z]{2}\d{6}|\d{8})(?:_|\.)", re.I)
WANTED = {
    "totalassets": "total_assets",
    "totalassetslesscurrentliabilities": "total_assets_less_current_liabilities",
    "netassetsliabilities": "net_assets",
    "turnoverrevenue": "turnover",
    "turnover": "turnover",
    "cashbankinhand": "cash",
    "cashandcashequivalents": "cash",
}


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def local(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.split(":")[-1].split("}")[-1].lower())


def number(text: str | None, scale: str | None, sign: str | None) -> int | float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.()\-]", "", text).replace("(", "-").replace(")", "")
    try:
        value = Decimal(cleaned)
        if scale:
            value *= Decimal(10) ** int(scale)
        if sign == "-":
            value = -abs(value)
        return int(value) if value == value.to_integral_value() else float(value)
    except (InvalidOperation, ValueError):
        return None


class TolerantFacts(HTMLParser):
    """Small fallback parser for real-world iXBRL HTML that is not strict XML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.contexts: dict[str, str] = {}
        self.facts: list[tuple[str, str, str | None, str | None, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        self.stack.append({"tag": tag, "attrs": values, "text": []})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        for frame in self.stack:
            frame["text"].append(data)

    def handle_endtag(self, _tag: str) -> None:
        if not self.stack:
            return
        frame = self.stack.pop()
        tag = local(frame["tag"])
        attrs = frame["attrs"]
        text = "".join(frame["text"]).strip()
        if tag == "context" and attrs.get("id"):
            dates = re.findall(r"20\d{2}-\d{2}-\d{2}", text)
            self.contexts[attrs["id"]] = max(dates) if dates else ""
        key = local(attrs.get("name", "") or frame["tag"])
        if key in WANTED:
            self.facts.append((key, text, attrs.get("scale"), attrs.get("sign"), attrs.get("contextref", "")))


def _best(facts: list[tuple[str, int | float, str]], target: str, value: int | float, date: str) -> None:
    current = next((row for row in facts if row[0] == target), None)
    if current is None or date >= current[2]:
        if current:
            facts.remove(current)
        facts.append((target, value, date))


def parse_xml(payload: bytes) -> tuple[list[tuple[str, int | float, str]], str]:
    root = ElementTree.fromstring(payload)
    contexts: dict[str, str] = {}
    for element in root.iter():
        if local(element.tag) == "context" and element.get("id"):
            dates = [
                (child.text or "").strip()
                for child in element.iter()
                if local(child.tag) in {"instant", "enddate"} and child.text
            ]
            contexts[element.get("id", "")] = max(dates) if dates else ""
    facts: list[tuple[str, int | float, str]] = []
    for element in root.iter():
        key = local(element.get("name", "") or element.tag)
        target = WANTED.get(key)
        if not target:
            continue
        value = number("".join(element.itertext()), element.get("scale"), element.get("sign"))
        if value is None:
            continue
        date = contexts.get(element.get("contextRef", "") or element.get("contextref", ""), "")
        _best(facts, target, value, date)
    return facts, "xml"


def parse_tolerant(payload: bytes) -> tuple[list[tuple[str, int | float, str]], str]:
    parser = TolerantFacts()
    parser.feed(payload.decode("utf-8", errors="replace"))
    parser.close()
    facts: list[tuple[str, int | float, str]] = []
    for key, text, scale, sign, context in parser.facts:
        value = number(text, scale, sign)
        if value is not None:
            _best(facts, WANTED[key], value, parser.contexts.get(context, ""))
    return facts, "tolerant-html"


def parse_document(name: str, payload: bytes) -> tuple[dict | None, str]:
    match = COMPANY_NUMBER.search(PurePosixPath(name).name)
    if not match:
        return None, "no-company-number"
    try:
        facts, parser = parse_xml(payload)
    except ElementTree.ParseError:
        facts, parser = parse_tolerant(payload)
    if not facts:
        return None, parser
    row = {
        "company_number": match.group(1).upper(),
        "source_file": PurePosixPath(name).name,
        **{target: value for target, value, _date in facts},
        "accounts_date": max((date for _target, _value, date in facts), default=""),
    }
    return row, parser


def validate_member(info: zipfile.ZipInfo, counters: dict) -> None:
    name = info.filename
    path = PurePosixPath(name)
    if not name or name.startswith(("/", "\\")) or "\\" in name or ".." in path.parts:
        raise RuntimeError(f"Unsafe ZIP member path: {name}")
    if info.flag_bits & 0x1:
        raise RuntimeError(f"Encrypted ZIP member is forbidden: {name}")
    mode = (info.external_attr >> 16) & 0o170000
    if mode == stat.S_IFLNK:
        raise RuntimeError(f"Symlink ZIP member is forbidden: {name}")
    if info.is_dir():
        return
    counters["members"] += 1
    counters["expanded_bytes"] += info.file_size
    if counters["members"] > MAX_MEMBERS:
        raise RuntimeError("Archive member ceiling exceeded")
    if counters["expanded_bytes"] > MAX_TOTAL_EXPANDED_BYTES:
        raise RuntimeError("Archive expanded-byte ceiling exceeded")
    if info.file_size > MAX_MEMBER_BYTES and path.suffix.lower() != ".zip":
        raise RuntimeError(f"Archive member exceeds the per-document ceiling: {name}")
    if path.suffix.lower() == ".zip" and info.file_size > MAX_NESTED_ZIP_BYTES:
        raise RuntimeError(f"Nested ZIP exceeds its byte ceiling: {name}")
    denominator = max(1, info.compress_size)
    if info.file_size / denominator > MAX_COMPRESSION_RATIO:
        raise RuntimeError(f"Archive compression ratio is implausible: {name}")


def iter_documents(archive: zipfile.ZipFile, counters: dict, depth: int = 0):
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise RuntimeError("Archive member ceiling exceeded")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise RuntimeError("Archive contains duplicate member names")
    for info in infos:
        validate_member(info, counters)
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    for info in infos:
        if info.is_dir():
            continue
        suffix = PurePosixPath(info.filename).suffix.lower()
        if suffix in {".html", ".xhtml", ".xml"}:
            with archive.open(info) as handle:
                payload = handle.read(MAX_MEMBER_BYTES + 1)
            if len(payload) > MAX_MEMBER_BYTES:
                raise RuntimeError(f"Document exceeded bounded read: {info.filename}")
            yield info.filename, payload
        elif suffix == ".zip":
            if depth >= MAX_NESTING:
                raise RuntimeError(f"Nested ZIP depth exceeded: {info.filename}")
            with archive.open(info) as handle:
                payload = handle.read(MAX_NESTED_ZIP_BYTES + 1)
            if len(payload) > MAX_NESTED_ZIP_BYTES:
                raise RuntimeError(f"Nested ZIP exceeded bounded read: {info.filename}")
            with zipfile.ZipFile(io.BytesIO(payload)) as nested:
                yield from iter_documents(nested, counters, depth + 1)


def extract(archive_path: Path, output: Path, report_path: Path) -> dict:
    archive_bytes = archive_path.stat().st_size
    if archive_bytes < 1024 or archive_bytes > MAX_ARCHIVE_BYTES:
        raise RuntimeError("Archive compressed size is outside the fixed bounds")
    source_sha = file_digest(archive_path)
    latest: dict[str, dict] = {}
    counters = {
        "members": 0,
        "expanded_bytes": 0,
        "eligible_documents": 0,
        "parsed_documents": 0,
        "tolerant_documents": 0,
        "parse_errors": 0,
        "documents_without_company_number": 0,
        "documents_without_wanted_facts": 0,
    }
    with zipfile.ZipFile(archive_path) as archive:
        for name, payload in iter_documents(archive, counters):
            counters["eligible_documents"] += 1
            try:
                row, parser = parse_document(name, payload)
            except Exception:
                counters["parse_errors"] += 1
                continue
            counters["parsed_documents"] += 1
            if parser == "tolerant-html":
                counters["tolerant_documents"] += 1
            if parser == "no-company-number":
                counters["documents_without_company_number"] += 1
            elif row is None:
                counters["documents_without_wanted_facts"] += 1
            elif (
                row["company_number"] not in latest
                or row.get("accounts_date", "") >= latest[row["company_number"]].get("accounts_date", "")
            ):
                latest[row["company_number"]] = row
    eligible = counters["eligible_documents"]
    if not eligible or not latest:
        raise RuntimeError("Archive produced no eligible account records")
    error_rate = counters["parse_errors"] / eligible
    if counters["parse_errors"] > 10 and error_rate > MAX_PARSE_ERROR_RATE:
        raise RuntimeError(f"Parse-error rate {error_rate:.6f} exceeded {MAX_PARSE_ERROR_RATE:.6f}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for company_number in sorted(latest):
            handle.write(json.dumps(latest[company_number], sort_keys=True, separators=(",", ":")) + "\n")
    report = {
        "schema": "companies-house-bounded-extraction-report-v1",
        "generation": GENERATION,
        "status": "PASS",
        "archive_filename": archive_path.name,
        "archive_bytes": archive_bytes,
        "archive_sha256": source_sha,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        **counters,
        "parse_error_rate": error_rate,
        "records": len(latest),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def validate_basic_snapshot(archive_path: Path, report_path: Path) -> dict:
    """Prove the basic-company ZIP is bounded and intact before the legacy compiler reads it."""
    archive_bytes = archive_path.stat().st_size
    if archive_bytes < 1024 or archive_bytes > MAX_ARCHIVE_BYTES:
        raise RuntimeError("Basic snapshot compressed size is outside the fixed bounds")
    source_sha = file_digest(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(infos) > MAX_BASIC_MEMBERS:
            raise RuntimeError("Basic snapshot member ceiling exceeded")
        if len(names) != len(set(names)):
            raise RuntimeError("Basic snapshot contains duplicate member names")
        expanded = 0
        csv_members = []
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            if not name or name.startswith(("/", "\\")) or "\\" in name or ".." in path.parts:
                raise RuntimeError(f"Unsafe basic snapshot member path: {name}")
            if info.flag_bits & 0x1:
                raise RuntimeError(f"Encrypted basic snapshot member is forbidden: {name}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise RuntimeError(f"Symlink basic snapshot member is forbidden: {name}")
            if info.is_dir():
                continue
            if path.suffix.lower() != ".csv":
                raise RuntimeError(f"Unexpected basic snapshot member type: {name}")
            expanded += info.file_size
            if expanded > MAX_BASIC_EXPANDED_BYTES:
                raise RuntimeError("Basic snapshot expanded-byte ceiling exceeded")
            if info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
                raise RuntimeError(f"Basic snapshot compression ratio is implausible: {name}")
            csv_members.append(name)
        if len(csv_members) != 1:
            raise RuntimeError("BasicCompanyDataAsOneFile must contain exactly one CSV")
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Basic snapshot ZIP integrity failure: {bad}")
    report = {
        "schema": "companies-house-bounded-basic-validation-v1",
        "generation": GENERATION,
        "status": "PASS",
        "archive_filename": archive_path.name,
        "archive_bytes": archive_bytes,
        "archive_sha256": source_sha,
        "members": len(infos),
        "csv_members": len(csv_members),
        "expanded_bytes": expanded,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("accounts", "basic"), default="accounts")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.kind == "basic":
            if args.output is not None:
                raise RuntimeError("Basic validation does not write a data output")
            report = validate_basic_snapshot(args.input, args.report)
            print(json.dumps({"status": "PASS", "csv_members": report["csv_members"]}))
        else:
            if args.output is None:
                raise RuntimeError("Accounts extraction requires --output")
            report = extract(args.input, args.output, args.report)
            print(json.dumps({"status": "PASS", "records": report["records"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
