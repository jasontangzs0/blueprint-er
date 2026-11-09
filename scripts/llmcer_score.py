"""Score an LLM-CER run: map its final_results.txt (clusters of row positions) back to our ids and
apply the shared scorer. Also parses calls/tokens from the run log and prices them.
Usage: PYTHONPATH=. .venv/bin/python scripts/llmcer_score.py --name wdc_s --records ... --gold ... \
   [--test-pairs ...] --fields title,brand,price,description --results data/external/LLMCER/final_results.txt \
   --id-map data/external/LLMCER/datasets/wdc_s/id_map.json --log data/baselines/llmcer_wdc_s.log --model gpt-5.6-luna
"""
import argparse, json, os, re, shutil, time
from blueprint.scoring import load_records, load_gold, load_test_pairs, score

PRICE = {"gpt-5-nano": (0.05, 0.40), "gpt-5.6-luna": (0.20, 1.20), "gpt-4o-mini": (0.15, 0.60), "gpt-oss-120b": (0.15, 0.60), "gpt-oss-20b": (0.075, 0.30)}
ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--gold", required=True)
ap.add_argument("--test-pairs", default=""); ap.add_argument("--fields", required=True); ap.add_argument("--results", required=True)
ap.add_argument("--id-map", required=True); ap.add_argument("--log", default=""); ap.add_argument("--model", default="gpt-5.6-luna")
ap.add_argument("--tag", default="luna_low"); ap.add_argument("--llmcer-repo", default="data/external/LLMCER")
ap.add_argument("--stats", default="", help="stats_<name>.json written by llmcer_shard.py merge (api_calls, in_tokens, out_tokens)")
a = ap.parse_args()
FIELDS = [f.strip() for f in a.fields.split(",") if f.strip()]
recs = load_records(a.records); gold, cid = load_gold(a.gold, recs); test_pairs = load_test_pairs(a.test_pairs)
ids = json.load(open(a.id_map))
clusters = [[ids[int(x)] for x in line.split()] for line in open(a.results) if line.strip()]
seen = {x for c in clusters for x in c}
partition = clusters + [[r] for r in recs if r not in seen]
out = score(partition, recs, cid, gold_clusters=gold, test_pairs=test_pairs, title_field=FIELDS[0], llmcer_repo=a.llmcer_repo)
stats = {}
if a.log and os.path.exists(a.log):
    txt = open(a.log, errors="replace").read()
    for key, pat in [("calls", r"Total API Calls:\s+(\d+)"), ("in_tokens", r"Input Tokens:\s+(\d+)"), ("out_tokens", r"Output Tokens:\s+(\d+)"), ("tokens", r"Total Tokens:\s+(\d+)"), ("blocks", r"Found (\d+) blocks"), ("mdg", r"Total MDG Interventions:\s+(\d+)")]:
        m = re.findall(pat, txt); stats[key] = int(m[-1]) if m else None
    m = re.findall(r"Total LLM Time:\s+([\d.]+) s\s+\(wall: ([\d.]+) s\)", txt); stats["wall_s"] = float(m[-1][1]) if m else None
    if stats.get("in_tokens") is not None and a.model in PRICE:
        pi, po = PRICE[a.model]; stats["cost_list"] = stats["in_tokens"] / 1e6 * pi + (stats.get("out_tokens") or 0) / 1e6 * po
if a.stats and os.path.exists(a.stats):
    st = json.load(open(a.stats)); stats.update({"calls": st.get("api_calls"), "in_tokens": st.get("in_tokens"), "out_tokens": st.get("out_tokens"), "tokens": st.get("tokens"), "mdg": st.get("mdg_fails"), "wall_s": st.get("wall")})
    if stats.get("in_tokens") is not None and a.model in PRICE:
        pi, po = PRICE[a.model]; stats["cost_list"] = stats["in_tokens"] / 1e6 * pi + (stats.get("out_tokens") or 0) / 1e6 * po
OUT = f"data/baselines/llmcer/{a.name}__{a.tag}"; os.makedirs(OUT, exist_ok=True)
shutil.copy(a.results, f"{OUT}/final_results.txt"); json.dump(partition, open(f"{OUT}/partition.json", "w"))
json.dump({"name": a.name, "tag": a.tag, "model": a.model, **stats, **out}, open(f"{OUT}/summary.json", "w"), indent=1)
print(f"[LLM-CER {a.name} {a.tag}] {out['line']}")
print("stats:", {k: v for k, v in stats.items()})
