"""Write a dataset in the layout data/external/LLMCER expects (what was done inline for wdc_s / patients_50k):
  datasets/<name>/<name>.csv  : id (0-based index) + the chosen fields (truncated as the runs truncate them)
  datasets/<name>/gt.txt      : one gold cluster per line, as indices (singletons omitted)
  datasets/<name>/id_map.json : list, index -> original record id (used by scripts/llmcer_score.py)
Usage: PYTHONPATH=. .venv/bin/python scripts/llmcer_prep.py --name wdc_four_domains --records ... --gold ... \
   --fields title,brand,price,description --truncate description=200 [--llmcer-repo data/external/LLMCER]
"""
import argparse, csv, json, os
from blueprint.scoring import load_records, load_gold

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--gold", required=True)
ap.add_argument("--fields", required=True); ap.add_argument("--truncate", default=""); ap.add_argument("--llmcer-repo", default="data/external/LLMCER")
a = ap.parse_args()
FIELDS = [f.strip() for f in a.fields.split(",") if f.strip()]
recs = load_records(a.records)
for spec in [x for x in a.truncate.split(",") if x.strip()]:
    fld, n = spec.split("="); n = int(n)
    for r in recs.values():
        if r.get(fld): r[fld] = r[fld][:n]
ids = list(recs)                      # file order, as load_records read it
index = {rid: i for i, rid in enumerate(ids)}
clusters, _ = load_gold(a.gold, recs)
out = os.path.join(a.llmcer_repo, "datasets", a.name); os.makedirs(out, exist_ok=True)
with open(os.path.join(out, f"{a.name}.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["id", *FIELDS])
    for i, rid in enumerate(ids): w.writerow([i, *(recs[rid].get(f, "") for f in FIELDS)])
with open(os.path.join(out, "gt.txt"), "w") as fh:
    n = 0
    for cl in clusters:
        members = [index[x] for x in cl if x in index]
        if len(members) >= 2: fh.write(" ".join(map(str, members)) + "\n"); n += 1
json.dump(ids, open(os.path.join(out, "id_map.json"), "w"))
print(f"{out}: {len(ids):,} records, {n:,} gold clusters with 2+ members, fields {FIELDS}")
