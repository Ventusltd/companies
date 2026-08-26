#!/usr/bin/env python3
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True);a=p.parse_args()
latest={}
for path in sorted(Path(a.input).rglob("*.ndjson")):
    for line in path.read_text().splitlines():
        if not line.strip(): continue
        row=json.loads(line); key=row["company_number"]
        if key not in latest or row.get("accounts_date","") >= latest[key].get("accounts_date",""): latest[key]=row
out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
with out.open("w") as handle:
    for key in sorted(latest): handle.write(json.dumps(latest[key],separators=(",",":"))+"\n")
if not latest: raise RuntimeError("No annual account facts were merged")
print(json.dumps({"latest_accounts":len(latest)}))

