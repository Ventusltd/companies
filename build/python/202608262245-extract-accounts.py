#!/usr/bin/env python3
"""Extract selected balance-sheet facts from Companies House XBRL/iXBRL."""
from __future__ import annotations
import argparse, io, json, re, zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from lxml import etree

WANTED = {
    "totalassets": "total_assets",
    "totalassetslesscurrentliabilities": "total_assets_less_current_liabilities",
    "netassetsliabilities": "net_assets",
    "turnoverrevenue": "turnover",
    "turnover": "turnover",
    "cashbankinhand": "cash",
    "cashandcashequivalents": "cash",
}
NUMBER = re.compile(r"(?:^|_)([A-Z]{2}\d{6}|\d{8})(?:_|\.)", re.I)

def local(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.split(":")[-1].split("}")[-1].lower())

def number(text: str | None, scale: str | None, sign: str | None):
    if not text: return None
    try:
        value = Decimal(re.sub(r"[^0-9.()-]", "", text).replace("(", "-").replace(")", ""))
        if scale: value *= Decimal(10) ** int(scale)
        if sign == "-": value = -abs(value)
        return float(value)
    except (InvalidOperation, ValueError):
        return None

def parse_document(name: str, payload: bytes):
    company_match = NUMBER.search(name)
    if not company_match: return None
    root = etree.fromstring(payload, etree.XMLParser(recover=True, huge_tree=True))
    contexts = {}
    for element in root.iter():
        if local(element.tag) == "context" and element.get("id"):
            dates = [x.text for x in element.iter() if local(x.tag) in {"instant", "enddate"} and x.text]
            contexts[element.get("id")] = max(dates) if dates else ""
    facts = {}
    for element in root.iter():
        key = local(element.get("name") or element.tag)
        target = WANTED.get(key)
        if not target: continue
        value = number("".join(element.itertext()), element.get("scale"), element.get("sign"))
        if value is None: continue
        date = contexts.get(element.get("contextRef", ""), "")
        current = facts.get(target)
        if current is None or date > current["date"]:
            facts[target] = {"value": value, "date": date}
    if not facts: return None
    return {"company_number": company_match.group(1).upper(), "source_file": name,
            **{key: item["value"] for key, item in facts.items()},
            "accounts_date": max((item["date"] for item in facts.values()), default="")}

def members(path: Path):
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            suffix = Path(info.filename).suffix.lower()
            if suffix in {".html", ".xhtml", ".xml"}:
                yield info.filename, archive.read(info)
            elif suffix == ".zip" and info.file_size < 100_000_000:
                with zipfile.ZipFile(io.BytesIO(archive.read(info))) as nested:
                    for child in nested.infolist():
                        if Path(child.filename).suffix.lower() in {".html", ".xhtml", ".xml"}:
                            yield child.filename, nested.read(child)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--input",required=True); parser.add_argument("--output",required=True)
    args=parser.parse_args(); latest={}
    for archive in sorted(Path(args.input).glob("*.zip")):
        if "account" not in archive.name.lower(): continue
        for name,payload in members(archive):
            try: row=parse_document(name,payload)
            except Exception: continue
            if row and (row["company_number"] not in latest or row.get("accounts_date","") >= latest[row["company_number"]].get("accounts_date","")):
                latest[row["company_number"]]=row
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w") as handle:
        for key in sorted(latest): handle.write(json.dumps(latest[key],separators=(",",":"))+"\n")
    print(json.dumps({"accounts_records":len(latest)}))

if __name__=="__main__": main()
