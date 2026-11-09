"""BatchER-style batched pairwise prompt (zero-shot: no labelled demonstrations exist in our setting).
Candidate pairs (the shared BM25 edges) are grouped ~B per call, ordered so consecutive pairs share a record;
the model answers match / no match per pair (strict JSON); closure; shared scoring.
Usage: PYTHONPATH=. .venv/bin/python scripts/batched_run.py --name wdc_s --records ... --gold ... [--test-pairs ...] \
   --cands data/cands/wdc_s__bm25_word_k20.tsv --fields title,brand,price,description --truncate description=200 \
   --model gpt-5-nano --reasoning low [--batch 10] [--workers 32] [--tag ...]
"""
import argparse, hashlib, json, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from blueprint.llm_client import ChatClient
from blueprint.scoring import load_records, load_gold, load_test_pairs, closure, score

PRICE = {"gpt-5-nano": (0.05, 0.40), "gpt-5.6-luna": (0.20, 1.20), "gpt-oss-120b": (0.15, 0.15, 0.60), "gpt-oss-20b": (0.075, 0.075, 0.30)}
ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--gold", required=True)
ap.add_argument("--test-pairs", default=""); ap.add_argument("--cands", required=True); ap.add_argument("--fields", required=True)
ap.add_argument("--truncate", default=""); ap.add_argument("--model", default="gpt-5-nano"); ap.add_argument("--reasoning", default="low")
ap.add_argument("--batch", type=int, default=10); ap.add_argument("--workers", type=int, default=32); ap.add_argument("--tag", default="")
ap.add_argument("--llmcer-repo", default="data/external/LLMCER")
a = ap.parse_args()
T0 = time.time(); log = lambda m: print(f"[{time.time()-T0:.0f}s] {m}", flush=True)
FIELDS = [f.strip() for f in a.fields.split(",") if f.strip()]
recs = load_records(a.records)
for spec in [x for x in a.truncate.split(",") if x.strip()]:
    fld_, n_ = spec.split("="); n_ = int(n_)
    for r in recs.values():
        if r.get(fld_): r[fld_] = r[fld_][:n_]
gold, cid = load_gold(a.gold, recs); test_pairs = load_test_pairs(a.test_pairs)
pairs = sorted(tuple(l.split("\t")[:2]) for l in open(a.cands).read().splitlines()[1:])
batches = [pairs[i:i + a.batch] for i in range(0, len(pairs), a.batch)]
OUT = f"data/baselines/batched/{a.name}__{a.model}_{a.reasoning}{a.tag}"; os.makedirs(OUT, exist_ok=True)
log(f"{a.name}: {len(recs):,} records, {len(pairs):,} candidate pairs ({sum(cid[x]==cid[y] for x,y in pairs):,} true) -> {len(batches):,} calls of {a.batch} on {a.model} ({a.reasoning})")
SYS = ("You are an entity resolution expert. You are given numbered PAIRS of records. For each pair decide whether the two records refer to the SAME real-world entity. "
       "Surface variance (spelling, abbreviation, word order, punctuation, truncation, missing values) is fine; a qualifier, edition, model, size, quantity or version that appears on one side only or differs means different entities. "
       "Answer with JSON {\"answers\":[{\"pair\":<number>,\"match\":true|false}, ...]} covering every pair exactly once.")
SCHEMA = {"type": "json_schema", "name": "answers", "strict": True, "schema": {"type": "object", "additionalProperties": False, "required": ["answers"], "properties": {"answers": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["pair", "match"], "properties": {"pair": {"type": "integer"}, "match": {"type": "boolean"}}}}}}}
ser = lambda r: "; ".join(f"{f}: {recs[r].get(f, '')}" for f in FIELDS if recs[r].get(f, ""))
def prompt(b): return "\n\n".join(f"Pair {i}:\n  A: {ser(x)}\n  B: {ser(y)}" for i, (x, y) in enumerate(b, 1))
bkey = lambda b: hashlib.sha1("|".join(f"{x},{y}" for x, y in b).encode()).hexdigest()[:16]
llm = ChatClient(deployment=a.model); lock = threading.Lock(); path = f"{OUT}/calls.jsonl"
done = {}
if os.path.exists(path):
    for l in open(path): r = json.loads(l); done[r["key"]] = r
todo = [b for b in batches if bkey(b) not in done]; logf = open(path, "a")
def one(b):
    res = llm.chat(SYS, prompt(b), response_format=SCHEMA, max_completion_tokens=4000, reasoning_effort=a.reasoning or None)
    row = {"key": bkey(b), "text": res["text"], "usage": res["usage"]}
    with lock: logf.write(json.dumps(row) + "\n"); logf.flush()
    return row
fails = 0
with ThreadPoolExecutor(a.workers) as ex:
    futs = [ex.submit(one, b) for b in todo]
    for i, f in enumerate(as_completed(futs), 1):
        try: r = f.result(); done[r["key"]] = r
        except Exception as e:
            fails += 1
            if fails <= 5: log(f"  FAIL: {str(e)[:120]}")
        if i % 1000 == 0: log(f"  {i}/{len(todo)}")
usage = [0, 0]; yes = []; parse_fail = 0
for b in batches:
    r = done.get(bkey(b))
    if not r: continue
    usage[0] += r["usage"].get("prompt_tokens") or 0; usage[1] += r["usage"].get("completion_tokens") or 0
    try: ans = json.loads(r["text"])["answers"]
    except Exception: parse_fail += 1; continue
    for e in ans:
        try:
            if e.get("match") and 1 <= int(e["pair"]) <= len(b): yes.append(b[int(e["pair"]) - 1])
        except (TypeError, ValueError): pass
yes = sorted(set(yes)); tp = sum(cid[x] == cid[y] for x, y in yes); gp = sum(cid[x] == cid[y] for x, y in pairs)
_pr = PRICE[a.model]; pi, po = _pr[0], _pr[-1]; cost = usage[0] / 1e6 * pi + usage[1] / 1e6 * po   # tuples are (in, out) or (in, cached, out)
log(f"{len(done):,} calls ({fails} failed, {parse_fail} unparsable), {usage[0]:,} in / {usage[1]:,} out tokens, list ${cost:.2f}")
log(f"pair-level: {len(yes):,} matches, P {tp/max(1,len(yes)):.3f} R {tp/max(1,gp):.3f}")
out = score(closure(recs, yes), recs, cid, gold_clusters=gold, test_pairs=test_pairs, title_field=FIELDS[0], llmcer_repo=a.llmcer_repo)
log(f"[BATCHED {a.name} {a.model} {a.reasoning} B={a.batch}] {out['line']}")
json.dump({"name": a.name, "model": a.model, "reasoning": a.reasoning, "batch": a.batch, "calls": len(done), "in_tokens": usage[0], "out_tokens": usage[1], "cost_list": cost,
           "pair_P": tp / max(1, len(yes)), "pair_R": tp / max(1, gp), **{k: v for k, v in out.items()}}, open(f"{OUT}/summary.json", "w"), indent=1)
