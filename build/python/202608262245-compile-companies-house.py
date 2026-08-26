#!/usr/bin/env python3
"""Compile public Companies House facts into bounded PipelineNews cartridges."""
from __future__ import annotations
import argparse, csv, hashlib, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path

LIMIT=10_000_000
SPV_TERMS={"solar","wind","battery","bess","storage","renewable","energy","power","generation","farm","project","developments"}
GENERIC_PROJECT_TERMS=SPV_TERMS|{"the","and","park","site","phase","extension","offshore","onshore","limited","ltd"}
BTM_PREFIXES={
    "BTM_MINING":("05","06","07","08","09"),
    "BTM_FOOD_PROCESSING":("10","11"),
    "BTM_PAPER":("17",),
    "BTM_CHEMICAL_PHARMA":("20","21"),
    "BTM_RUBBER_PLASTICS":("22",),
    "BTM_GLASS_CEMENT_MINERALS":("23",),
    "BTM_METALS_ENGINEERING":("24","25","28","29","30"),
    "BTM_WATER_WASTE":("36","37","38","39"),
}
BTM_EXACT={
    "52103":"BTM_COLD_STORAGE",
    "63110":"BTM_DATA_CENTRE",
    "52230":"BTM_AIRPORT_INFRASTRUCTURE",
    "49100":"BTM_RAIL_INFRASTRUCTURE",
    "49200":"BTM_RAIL_INFRASTRUCTURE",
    "47110":"BTM_SUPERMARKET",
}
INDUSTRIAL_DIVISIONS={f"{value:02d}" for value in [*range(5,10),*range(10,34),35,36,37,38,39]}
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
        match=re.match(r"(\d{5})",value or "")
        if not match:continue
        code=match.group(1); division=code[:2]
        if division in INDUSTRIAL_DIVISIONS:tags.add("INDUSTRIAL_SIC_B_TO_E")
        if code in BTM_EXACT:tags.add(BTM_EXACT[code])
        for tag,prefixes in BTM_PREFIXES.items():
            if division in prefixes:tags.add(tag)
    return sorted(tags)
def repd_index(root):
    operators={}; projects={}; token_blocks={}
    for path in sorted(root.glob("*.json")):
        data=json.loads(path.read_text())
        for project in data.get("projects",[]):
            record={"repd_ref":project["repd_ref"],"project":project["name"],"operator":project.get("operator",""),"capacity_mw":project["capacity_mw"]}
            operator=norm(project.get("operator",""))
            if operator:operators.setdefault(operator,[]).append(record)
            project_name=norm(project.get("name",""))
            if project_name:
                projects.setdefault(project_name,[]).append(record)
                for token in set(project_name.split())-GENERIC_PROJECT_TERMS:
                    if len(token)>=5:token_blocks.setdefault(token,[]).append((project_name,record))
    return operators,projects,token_blocks

def repd_candidates(company_name,index):
    operators,projects,token_blocks=index; key=norm(company_name); found={}
    for item in operators.get(key,[]):found[(item["repd_ref"],"EXACT_OPERATOR_NAME")]={**item,"match_type":"EXACT_OPERATOR_NAME"}
    for item in projects.get(key,[]):found[(item["repd_ref"],"EXACT_PROJECT_NAME")]={**item,"match_type":"EXACT_PROJECT_NAME"}
    company_tokens=set(key.split()); blocked=[]
    for token in company_tokens-GENERIC_PROJECT_TERMS:blocked.extend(token_blocks.get(token,[]))
    for project_key,item in blocked:
        distinctive=set(project_key.split())-GENERIC_PROJECT_TERMS
        if distinctive and distinctive.issubset(company_tokens):
            found[(item["repd_ref"],"PROJECT_NAME_SPV_CANDIDATE")]={**item,"match_type":"PROJECT_NAME_SPV_CANDIDATE"}
    return list(found.values())
def accounts(path):
    result={}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():continue
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
                        key=norm(name); matches=repd_candidates(name,repd); legal_tokens=set(re.findall(r"[a-z0-9]+",name.lower()))
                        probable_spv=bool(legal_tokens&{"limited","ltd","plc","llp"}) and bool(legal_tokens&{"project","farm","solar","wind","battery","storage","bess","generation"})
                        energy_relevant_large=large and bool(tags)
                        if not (energy_relevant_large or matches or probable_spv):continue
                        selected[number]={"company_name":name,"company_number":number,"company_status":status,"sic_codes":[x for x in sics if x],
                          "accounts_date":facts.get("accounts_date"),"total_assets":facts.get("total_assets"),"net_assets":facts.get("net_assets"),
                          "turnover":facts.get("turnover"),"cash":facts.get("cash"),"assets_gte_10m":large,"energy_relevant_large_company":energy_relevant_large,"btm_tags":tags,
                          "repd_name_candidates":matches,"probable_project_spv":probable_spv}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True); rows=list(selected.values())
    groups={"industrial-assets-gte-10m":[x for x in rows if x["assets_gte_10m"] and "INDUSTRIAL_SIC_B_TO_E" in x["btm_tags"]],"energy-relevant-assets-gte-10m":[x for x in rows if x["energy_relevant_large_company"]],"repd-linked":[x for x in rows if x["repd_name_candidates"]],"project-spv-candidates":[x for x in rows if x["probable_project_spv"]],"btm-opportunities":[x for x in rows if x["energy_relevant_large_company"]]}
    files={}
    for name,data in groups.items():
        path=out/f"{name}-v1.json";path.write_text(json.dumps({"schema":"companies-house-cartridge-v1","snapshot_id":a.stamp,"generated_at":datetime.now(timezone.utc).isoformat(),"records":data},separators=(",",":"))+"\n")
        files[name]={"path":path.name,"records":len(data),"sha256":digest(path)}
    manifest=out/"manifest-v1.json";manifest.write_text(json.dumps({"schema":"companies-house-manifest-v1","snapshot_id":a.stamp,"refresh_policy":"annual-overwrite","threshold_gbp":LIMIT,"files":files,"privacy":{"directors":False,"individual_psc":False,"residential_addresses":False}},indent=2)+"\n")
    if not rows:raise RuntimeError("Compilation produced no qualifying records")
    print(json.dumps({k:v["records"] for k,v in files.items()}))
if __name__=="__main__":main()
