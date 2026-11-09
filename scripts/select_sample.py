"""SELECT-prompt (ComEM-style) pairwise LLM matching, sampled for a COST ROW: for a random sample of
records, one call listing the record and its BM25 neighbours asks which neighbours are the same entity.
Projects calls, tokens and list cost to the whole collection; also reports pair-level P/R on the sample.
Usage: PYTHONPATH=. .venv/bin/python scripts/select_sample.py --name wdc_s --records ... --gold ... \
   --cands data/cands/wdc_s__bm25_word_k20.tsv --fields title,brand,price,description --truncate description=200 \
   --model gpt-5.6-luna --reasoning low --sample 150 [--workers 16]
"""
import argparse, json, os, random, re, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from blueprint.llm_client import ChatClient
from blueprint.scoring import load_records, load_gold

PRICE = {"gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5.6-luna": (0.20, 0.02, 1.20), "gpt-oss-120b": (0.15, 0.15, 0.60), "gpt-oss-20b": (0.075, 0.075, 0.30)}
ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--gold", required=True)
ap.add_argument("--cands", required=True); ap.add_argument("--fields", required=True); ap.add_argument("--truncate", default="")
ap.add_argument("--model", default="gpt-5.6-luna"); ap.add_argument("--reasoning", default="low"); ap.add_argument("--sample", type=int, default=150)
ap.add_argument("--workers", type=int, default=16); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--gold-file", default=""); ap.add_argument("--test-pairs", default=""); ap.add_argument("--tag", default="")
a = ap.parse_args()
FIELDS = [f.strip() for f in a.fields.split(",") if f.strip()]
recs = load_records(a.records)
for spec in [x for x in a.truncate.split(",") if x.strip()]:
    fld_, n_ = spec.split("="); n_ = int(n_)
    for r in recs.values():
        if r.get(fld_): r[fld_] = r[fld_][:n_]
gold, cid = load_gold(a.gold, recs)
nbr = defaultdict(list)
for l in open(a.cands).read().splitlines()[1:]:
    x, y = l.split("\t")[:2]; nbr[x].append(y); nbr[y].append(x)
anchors = sorted(nbr); random.Random(a.seed).shuffle(anchors); anchors = anchors[:a.sample] if a.sample else anchors
SYS = ("You are an entity resolution expert. You are given a target record and a numbered list of candidate records. "
       "Select every candidate that refers to the SAME real-world entity as the target. Different variants (size, colour, model number, edition) are different entities. "
       "Answer with a JSON object {\"matches\": [candidate numbers]}; use an empty list if none match.")
ser = lambda r: "; ".join(f"{f}: {recs[r].get(f, '')}" for f in FIELDS if recs[r].get(f, ""))
def prompt(x):
    cands = nbr[x]
    return f"Target: {ser(x)}\n\nCandidates:\n" + "\n".join(f"[{i}] {ser(c)}" for i, c in enumerate(cands, 1)), cands
llm = ChatClient(deployment=a.model)
usage = [0, 0, 0]; rows = []; T0 = time.time()
os.makedirs("data/baselines/select", exist_ok=True)
cache_path = f"data/baselines/select/{a.name}__{a.model}_{a.reasoning}{a.tag}_calls.jsonl"   # resumable per-anchor cache
cached = {}
if os.path.exists(cache_path):
    for l in open(cache_path):
        r = json.loads(l); cached[r["x"]] = r
import threading
lock = threading.Lock(); logf = open(cache_path, "a")
def one(x):
    p, cands = prompt(x)
    kw = {"reasoning_effort": a.reasoning} if a.reasoning else {}
    res = llm.chat(SYS, p, max_completion_tokens=2000, **kw)
    text, u = res.get("text") or res.get("content") or "", res.get("usage", {})
    try: sel = json.loads(re.search(r"\{.*\}", text, re.S).group(0)).get("matches", [])
    except Exception: sel = []
    sel = [cands[int(i) - 1] for i in sel if str(i).isdigit() and 1 <= int(i) <= len(cands)]
    with lock: logf.write(json.dumps({"x": x, "cands": cands, "sel": sel, "usage": u}) + "\n"); logf.flush()
    return x, cands, sel, u
fails = 0
todo = [x for x in anchors if x not in cached]
for x in anchors:
    if x in cached:
        r = cached[x]; u = r["usage"]; rows.append((r["x"], r["cands"], r["sel"]))
        usage[0] += u.get("prompt_tokens") or 0; usage[1] += u.get("cached_tokens") or 0; usage[2] += u.get("completion_tokens") or 0
with ThreadPoolExecutor(a.workers) as ex:
    futs = [ex.submit(one, x) for x in todo]
    for i, f in enumerate(as_completed(futs), 1):
        try: x, cands, sel, u = f.result()
        except Exception as e:   # content filter / transient errors: count and skip (the anchor keeps no matches)
            fails += 1
            if fails <= 5: print(f"  FAIL: {str(e)[:100]}", flush=True)
            continue
        usage[0] += u.get("prompt_tokens") or 0; usage[1] += u.get("cached_tokens") or 0; usage[2] += u.get("completion_tokens") or 0
        rows.append((x, cands, sel))
        if i % 2000 == 0: print(f"  {i}/{len(todo)} ({time.time()-T0:.0f}s)", flush=True)
if fails: print(f"  {fails} calls failed (skipped)", flush=True)
tp = sum(1 for x, c, s in rows for y in s if cid[x] == cid[y]); pp = sum(len(s) for _, _, s in rows); gp = sum(1 for x, c, _ in rows for y in c if cid[x] == cid[y])
pi, pc, po = PRICE[a.model]; n = len(rows); N = len(nbr)
cost_sample = usage[0] / 1e6 * pi + usage[2] / 1e6 * po
print(f"SELECT sample: {n} calls on {a.model} ({a.reasoning}), {usage[0]:,} in / {usage[2]:,} out tokens, list ${cost_sample:.2f}, {time.time()-T0:.0f}s")
print(f"  pair-level on sampled anchors: P {tp/max(1,pp):.3f} R {tp/max(1,gp):.3f} (asserted {pp}, true available {gp})")
print(f"  projection to all {N:,} records with neighbours: {N:,} calls, {usage[0]/n*N/1e6:.1f}M in / {usage[2]/n*N/1e6:.2f}M out tokens, list ${cost_sample/n*N:,.0f}")
os.makedirs("data/baselines/select", exist_ok=True)
if not a.sample:   # full run: closure of the selected pairs + shared scoring
    from blueprint.scoring import load_test_pairs, closure, score
    sel_pairs = [(x, y) for x, _, s in rows for y in s]
    partition = closure(recs, sel_pairs)
    out = score(partition, recs, cid, gold_clusters=gold, test_pairs=load_test_pairs(a.test_pairs), title_field=FIELDS[0], llmcer_repo="data/external/LLMCER")
    print(f"[SELECT {a.name} {a.model} {a.reasoning}] {out['line']}")
    json.dump(partition, open(f"data/baselines/select/{a.name}__{a.model}_{a.reasoning}{a.tag}_partition.json", "w"))
    json.dump({"name": a.name, "model": a.model, "reasoning": a.reasoning, "calls": n, "in_tokens": usage[0], "out_tokens": usage[2], "cost_list": cost_sample, **{k: v for k, v in out.items()}},
              open(f"data/baselines/select/{a.name}__{a.model}_{a.reasoning}{a.tag}_summary.json", "w"), indent=1)
json.dump({"name": a.name, "model": a.model, "reasoning": a.reasoning, "sample_calls": n, "in_tokens": usage[0], "out_tokens": usage[2], "cost_sample": cost_sample,
           "pair_P": tp / max(1, pp), "pair_R": tp / max(1, gp), "records_with_neighbours": N, "projected_cost_list": cost_sample / n * N, "rows": rows},
          open(f"data/baselines/select/{a.name}__{a.model}_{a.reasoning}{a.tag}.json", "w"), indent=1)
