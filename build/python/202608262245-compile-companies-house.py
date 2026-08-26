#!/usr/bin/env python3
"""Compile public Companies House facts into bounded PipelineNews cartridges."""
from __future__ import annotations
import argparse, csv, hashlib, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path

LIMIT=10_000_000
RENEWABLE=("solar","wind","battery","bess","storage","renewable","energy","power","generation","project")
BTM={
    "BTM_MINING":range(500,1000),"BTM_FOOD_PROCESSING":range(1000,1300),
    "BTM_MANUFACTURING":range(1300,3400),"BTM_WATER_WASTE":range(3600,4000),
    "BTM_LOGISTICS":range(4900,5400),"BTM_DATA_CENTRE":range(6310,6320),
    "BTM_RETAIL_DISTRIBUTION":range(4500,4800),
}
def norm(value):
    value=re.sub(r"\b(limited|ltd|plc|holdings?|group|uk)\b"," ",str(value).lower())
    return re.sub(r"[^a-z0-9]+"," ",value).strip()
def field(row,*names):
    lowered={re.sub(r"[^a-z0-9]","",k.lower()):v for k,v in row.items()}
    for name in names:
        value=lowered.get(re.sub(r"[^a-z0-9]","",name.lower()))
        if value is not None:return value
    return ""
def sic_tags(values):
    tags=set()
    for value in values:
        match=re.match(r"(\d{4,5})",value or "")
        if not match:continue
        code=int(match.group(1)[:4])
        for tag,codes in BTM.items():
            if code in codes:tags.add(tag)
    return sorted(tags)
def repd_index(root):
    index={}
    for path in sorted(root.glob("*.json")):
        data=json.loads(path.read_text())
        for project in data.get("projects",[]):
            key=norm(project.get("operator",""))
            if key:index.setdefault(key,[]).append({"repd_ref":project["repd_ref"],"project":project["name"],"capacity_mw":project["capacity_mw"]})
    return index
def accounts(path):
    result={}
    if path.exists():
        for line in path.read_text().splitlines():
            row=json.loads(line); result[row["company_number"]]=row
    return result
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument("--raw",required=True);p.add_argument("--accounts",required=True);p.add_argument("--repd",required=True);p.add_argument("--output",required=True);p.add_argument("--stamp",required=True)
    a=p.parse_args(); raw=Path(a.raw); acc=accounts(Path(a.accounts)); repd=repd_index(Path(a.repd)); selected={}
    for archive in sorted(raw.glob("*.zip")):
        if "basiccompanydata" not in archive.name.lower():continue
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                if not member.lower().endswith(".csv"):continue
                with z.open(member) as stream:
                    rows=csv.DictReader((line.decode("utf-8-sig",errors="replace") for line in stream))
                    for row in rows:
                        number=field(row,"CompanyNumber").upper(); name=field(row,"CompanyName"); status=field(row,"CompanyStatus")
                        if not number or not name:continue
                        sics=[field(row,f"SICCode.SicText_{i}") for i in range(1,5)]; tags=sic_tags(sics)
                        facts=acc.get(number,{})
                        large=max(facts.get("total_assets",0) or 0,facts.get("net_assets",0) or 0)>=LIMIT
                        key=norm(name); matches=repd.get(key,[]); renewable=any(word in key.split() for word in RENEWABLE)
                        if not (large or tags or matches or renewable):continue
                        selected[number]={"company_name":name,"company_number":number,"company_status":status,"sic_codes":[x for x in sics if x],
                          "accounts_date":facts.get("accounts_date"),"total_assets":facts.get("total_assets"),"net_assets":facts.get("net_assets"),
                          "turnover":facts.get("turnover"),"cash":facts.get("cash"),"large_company":large,"btm_tags":tags,
                          "repd_exact_name_candidates":matches,"renewable_name_candidate":renewable}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True); rows=list(selected.values())
    groups={"large-companies":[x for x in rows if x["large_company"]],"repd-linked":[x for x in rows if x["repd_exact_name_candidates"]],"btm-opportunities":[x for x in rows if x["btm_tags"]]}
    files={}
    for name,data in groups.items():
        path=out/f"{name}-v1.json";path.write_text(json.dumps({"schema":"companies-house-cartridge-v1","snapshot_id":a.stamp,"generated_at":datetime.now(timezone.utc).isoformat(),"records":data},separators=(",",":"))+"\n")
        files[name]={"path":str(path),"records":len(data),"sha256":digest(path)}
    manifest=out/"manifest-v1.json";manifest.write_text(json.dumps({"schema":"companies-house-manifest-v1","snapshot_id":a.stamp,"refresh_policy":"annual-overwrite","threshold_gbp":LIMIT,"files":files,"privacy":{"directors":False,"individual_psc":False,"residential_addresses":False}},indent=2)+"\n")
    if not rows:raise RuntimeError("Compilation produced no qualifying records")
    print(json.dumps({k:v["records"] for k,v in files.items()}))
if __name__=="__main__":main()
