#!/usr/bin/env python3
"""Compile public Companies House facts into bounded PipelineNews cartridges."""
from __future__ import annotations
import argparse, csv, hashlib, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

LIMIT=10_000_000
SPV_TERMS={"solar","wind","battery","bess","storage","renewable","energy","power","generation","farm","project","developments"}
RENEWABLE_TERMS={"solar","wind","battery","bess","storage","renewable","energy","power","generation"}
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
COMPANY_NUMBER=re.compile(r"^(?:[A-Z]{2}\d{6}|\d{8})$")
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
def news_index(path):
    indexed={}
    if not path or not path.exists():return indexed
    data=json.loads(path.read_text())
    for item in data.get("canonical_items",[]):
        if item.get("role")!="PRIMARY_MATCH" or item.get("eligible_for_news_signal") is not True:continue
        repd_ref=str(item.get("repd_ref", ""))
        if not repd_ref:continue
        indexed.setdefault(repd_ref,[]).append({key:item.get(key) for key in (
          "gg_article_id","event","headline","published","source","url","confidence","role")})
    for repd_ref in indexed:
        indexed[repd_ref].sort(key=lambda item:(item.get("published") or "",item.get("gg_article_id") or ""),reverse=True)
    return indexed
def atlas_url(project):
    if project.get("geometry_status")!="valid" or project.get("latitude") is None or project.get("longitude") is None:return None
    query=urlencode({"repd_ref":project["repd_ref"],"project":project["name"],"technology":project.get("technology",""),
      "capacity_mw":project["capacity_mw"],"latitude":project["latitude"],"longitude":project["longitude"],"zoom":"12"})
    return f"https://globalgrid2050.com/repd_grid_atlasv8/?{query}"
def repd_index(root,news):
    operators={}; projects={}; token_blocks={}
    for path in sorted(root.glob("*.json")):
        data=json.loads(path.read_text())
        for project in data.get("projects",[]):
            repd_ref=str(project["repd_ref"])
            signals=news.get(repd_ref,[])
            record={"repd_ref":repd_ref,"gg_project_id":project.get("gg_project_id",f"GG2050-REPD-{repd_ref}"),
              "project":project["name"],"operator":project.get("operator",""),"capacity_mw":project["capacity_mw"],
              "technology":project.get("technology"),"status":project.get("status"),"latitude":project.get("latitude"),
              "longitude":project.get("longitude"),"atlas_url":atlas_url(project),"canonical_news_count":len(signals),
              "latest_canonical_news":signals[:5]}
            operator=norm(project.get("operator",""))
            if operator:operators.setdefault(operator,[]).append(record)
            project_name=norm(project.get("name",""))
            if project_name:
                projects.setdefault(project_name,[]).append(record)
                for token in set(project_name.split())-GENERIC_PROJECT_TERMS:
                    if len(token)>=5:token_blocks.setdefault(token,[]).append((project_name,record))
    return operators,projects,token_blocks

def repd_candidates(company_name,index,match_name_source="LEGAL_NAME"):
    operators,projects,token_blocks=index; key=norm(company_name); found={}
    for item in operators.get(key,[]):found[(item["repd_ref"],"EXACT_OPERATOR_NAME")]={**item,"match_type":"EXACT_OPERATOR_NAME","match_name_source":match_name_source}
    for item in projects.get(key,[]):found[(item["repd_ref"],"EXACT_PROJECT_NAME")]={**item,"match_type":"EXACT_PROJECT_NAME","match_name_source":match_name_source}
    company_tokens=set(key.split()); blocked=[]
    for token in company_tokens-GENERIC_PROJECT_TERMS:blocked.extend(token_blocks.get(token,[]))
    for project_key,item in blocked:
        distinctive=set(project_key.split())-GENERIC_PROJECT_TERMS
        if distinctive and distinctive.issubset(company_tokens):
            found[(item["repd_ref"],"PROJECT_NAME_SPV_CANDIDATE")]={**item,"match_type":"PROJECT_NAME_SPV_CANDIDATE","match_name_source":match_name_source}
    return list(found.values())
def classification(matches,probable_spv,renewable_name):
    match_types={item["match_type"] for item in matches}
    if "EXACT_OPERATOR_NAME" in match_types:return "CONFIRMED_REPD_COMPANY"
    if matches or probable_spv:return "PROBABLE_PROJECT_SPV"
    if renewable_name:return "RENEWABLE_COMPANY"
    return "UNRESOLVED_CANDIDATE"
def accounts(path):
    result={}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():continue
            row=json.loads(line); result[row["company_number"]]=row
    return result
def previous_records(path):
    if not path:return {}
    data=json.loads(path.read_text())
    if data.get("schema")!="companies-house-retained-v1" or not isinstance(data.get("records"),list):
        raise RuntimeError("Previous retained-company state is malformed")
    result={}
    for row in data["records"]:
        number=row.get("company_number","")
        if not COMPANY_NUMBER.fullmatch(number) or number in result:
            raise RuntimeError("Previous retained-company state has invalid or duplicate company numbers")
        result[number]=row
    return result
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def repd_closure(root):
    entries=[f"{path.name}:{digest(path)}" for path in sorted(root.glob("*.json"))]
    return {"files":len(entries),"sha256":hashlib.sha256(("\n".join(entries)+"\n").encode()).hexdigest()}
def main():
    p=argparse.ArgumentParser();p.add_argument("--raw",required=True);p.add_argument("--accounts",required=True);p.add_argument("--repd",required=True);p.add_argument("--news");p.add_argument("--output",required=True);p.add_argument("--stamp",required=True)
    p.add_argument("--previous-records");p.add_argument("--refresh-policy",choices=("annual-bootstrap","quarterly-incremental"),default="annual-bootstrap")
    a=p.parse_args(); raw=Path(a.raw); accounts_path=Path(a.accounts); repd_root=Path(a.repd); news_path=Path(a.news) if a.news else None
    previous_path=Path(a.previous_records) if a.previous_records else None
    if a.refresh_policy=="quarterly-incremental" and previous_path is None:
        raise RuntimeError("Quarterly compilation requires --previous-records from a verified bootstrap")
    previous=previous_records(previous_path); acc=accounts(accounts_path); news=news_index(news_path); repd=repd_index(repd_root,news); selected={}; generated_at=datetime.now(timezone.utc)
    for archive in sorted(raw.glob("*.zip")):
        if "basiccompanydata" not in archive.name.lower():continue
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                if not member.lower().endswith(".csv"):continue
                with z.open(member) as stream:
                    rows=csv.DictReader((line.decode("utf-8-sig",errors="replace") for line in stream))
                    for row in rows:
                        number=field(row,"CompanyNumber").upper(); name=field(row,"CompanyName"); status=field(row,"CompanyStatus")
                        if not COMPANY_NUMBER.fullmatch(number) or not name:continue
                        sics=[field(row,f"SICCode.SicText_{i}") for i in range(1,5)]; tags=sic_tags(sics)
                        previous_names=[field(row,f"PreviousName_{i}.CompanyName") for i in range(1,11)]
                        previous_names=[value for value in previous_names if value]
                        old=previous.get(number,{})
                        facts=acc.get(number) or {key:old.get(key) for key in ("accounts_date","total_assets","net_assets","turnover","cash") if old.get(key) is not None}
                        large=max(facts.get("total_assets",0) or 0,facts.get("net_assets",0) or 0)>=LIMIT
                        key=norm(name); matches=repd_candidates(name,repd)
                        for previous_name in previous_names:
                            matches.extend(repd_candidates(previous_name,repd,"PREVIOUS_LEGAL_NAME"))
                        matches=list({(item["repd_ref"],item["match_type"],item["match_name_source"]):item for item in matches}.values())
                        legal_tokens=set(re.findall(r"[a-z0-9]+",name.lower()))
                        probable_spv=bool(legal_tokens&{"limited","ltd","plc","llp"}) and bool(legal_tokens&{"project","farm","solar","wind","battery","storage","bess","generation"})
                        renewable_name=bool(set(key.split())&RENEWABLE_TERMS)
                        energy_relevant_large=large and bool(tags)
                        btm_opportunity=large and any(tag.startswith("BTM_") for tag in tags)
                        if not (energy_relevant_large or matches or probable_spv):continue
                        evidence=["COMPANIES_HOUSE_BASIC_RECORD"]
                        if facts:evidence.append("COMPANIES_HOUSE_ACCOUNTS_FACTS")
                        if large:evidence.append("ASSETS_GTE_10M")
                        evidence.extend(sorted({item["match_type"] for item in matches}))
                        if any(item["match_name_source"]=="PREVIOUS_LEGAL_NAME" for item in matches):evidence.append("PREVIOUS_LEGAL_NAME_MATCH")
                        if probable_spv:evidence.append("RENEWABLE_PROJECT_LEGAL_NAME")
                        company_news={item["gg_article_id"]:item for match in matches for item in match["latest_canonical_news"]}
                        selected[number]={"company_name":name,"company_number":number,"company_status":status,"sic_codes":[x for x in sics if x],
                          "previous_names":previous_names,"registered_postcode":field(row,"RegAddress.PostCode"),
                          "accounts_date":facts.get("accounts_date"),"total_assets":facts.get("total_assets"),"net_assets":facts.get("net_assets"),
                          "turnover":facts.get("turnover"),"cash":facts.get("cash"),"financial_currency":"GBP","assets_gte_10m":large,"energy_relevant_large_company":energy_relevant_large,"btm_opportunity":btm_opportunity,"btm_tags":tags,
                          "repd_name_candidates":matches,"probable_project_spv":probable_spv,"classification":classification(matches,probable_spv,renewable_name),
                          "repd_news_count":len(company_news),"latest_repd_news":sorted(company_news.values(),key=lambda item:(item.get("published") or "",item["gg_article_id"]),reverse=True)[:5],
                          "evidence":evidence,"last_checked_date":generated_at.date().isoformat()}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True); rows=sorted(selected.values(),key=lambda row:row["company_number"])
    groups={"industrial-assets-gte-10m":[x for x in rows if x["assets_gte_10m"] and "INDUSTRIAL_SIC_B_TO_E" in x["btm_tags"]],"energy-relevant-assets-gte-10m":[x for x in rows if x["energy_relevant_large_company"]],"repd-linked":[x for x in rows if x["repd_name_candidates"]],"project-spv-candidates":[x for x in rows if x["classification"]=="PROBABLE_PROJECT_SPV"],"btm-opportunities":[x for x in rows if x["btm_opportunity"]]}
    files={}
    for name,data in groups.items():
        path=out/f"{name}-v1.json";path.write_text(json.dumps({"schema":"companies-house-cartridge-v1","snapshot_id":a.stamp,"generated_at":generated_at.isoformat(),"records":data},separators=(",",":"))+"\n")
        files[name]={"path":path.name,"records":len(data),"sha256":digest(path)}
    retained=out/"retained-companies-v1.json";retained.write_text(json.dumps({"schema":"companies-house-retained-v1","snapshot_id":a.stamp,"generated_at":generated_at.isoformat(),"records":rows},separators=(",",":"))+"\n")
    state={"path":retained.name,"records":len(rows),"sha256":digest(retained)}
    provenance={"accounts_sha256":digest(accounts_path),"previous_records_sha256":digest(previous_path) if previous_path else None,"repd":repd_closure(repd_root),"news_sha256":digest(news_path) if news_path else None,
      "identity_rule":"REPD name rules establish candidates; canonical PRIMARY_MATCH news only annotates an established REPD candidate"}
    manifest=out/"manifest-v1.json";manifest.write_text(json.dumps({"schema":"companies-house-manifest-v1","snapshot_id":a.stamp,"refresh_policy":a.refresh_policy,"threshold_gbp":LIMIT,"financial_currency":"GBP","inputs":provenance,"state":state,"files":files,"privacy":{"directors":False,"individual_psc":False,"residential_addresses":False}},indent=2)+"\n")
    if not rows:raise RuntimeError("Compilation produced no qualifying records")
    print(json.dumps({k:v["records"] for k,v in files.items()}))
if __name__=="__main__":main()
