"""Round-0 candidate pairs shared by every method: the BM25 top-k self-join, computed exactly as
scripts/reper.py does it (same ids order, tokens, index, k). Writes the UNDIRECTED neighbour
pairs (a<b, best rank across the two directions) and reports their reach against the gold pairs.
Also reports, for reference, the reach of the in-block pairs REP-ER's blocks expose.

Usage: PYTHONPATH=. .venv/bin/python scripts/bm25_pairs.py --name wdc_s \
   --records data/benchmarks/wdc-block/official_s/records.csv \
   --gold data/benchmarks/wdc-block/official_s/gold_clusters.txt \
   --bm25-fields title,brand,description --bm25-tokens word --k 20 [--cap 60] [--gate-rank 0]
Output: data/cands/<name>__bm25_<tokens>_k<k>.tsv  (id_a, id_b, rank)
"""
import argparse, os, re, time
from collections import Counter, defaultdict
from blueprint.rubric import norm
from blueprint.scoring import load_records, load_gold

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--gold", required=True)
ap.add_argument("--id-col", default="id"); ap.add_argument("--bm25-fields", required=True)
ap.add_argument("--bm25-tokens", choices=["word", "char3"], default="word"); ap.add_argument("--k", type=int, default=10)
ap.add_argument("--cap", type=int, default=60); ap.add_argument("--gate-rank", type=int, default=0)
ap.add_argument("--out", default="")
ap.add_argument("--truncate", default="", help="field=chars[,field=chars], applied BEFORE indexing, exactly as reper.py does")
a = ap.parse_args()
T0 = time.time(); log = lambda m: print(f"[{time.time()-T0:.0f}s] {m}", flush=True)

def grams3(s):
    s = re.sub(r"[^a-z0-9 ]+", " ", norm(s)); out = []
    for w in s.split():
        w = f" {w} "; out.extend(w[i:i + 3] for i in range(len(w) - 2))
    return out

recs = load_records(a.records, a.id_col)
for spec in [x for x in a.truncate.split(",") if x.strip()]:
    fld_, n_ = spec.split("="); n_ = int(n_)
    for r in recs.values():
        if r.get(fld_): r[fld_] = r[fld_][:n_]
gold_clusters, cid = load_gold(a.gold, recs)
G = sum(n * (n - 1) // 2 for n in Counter(cid.values()).values())
BM25F = [f.strip() for f in a.bm25_fields.split(",") if f.strip()]
import bm25s
ids = sorted(recs, key=str)
texts = [" ".join(recs[i].get(f, "") for f in BM25F) for i in ids]
toks = [grams3(t) for t in texts] if a.bm25_tokens == "char3" else [norm(t).split() for t in texts]
toks = [t if t else ["__empty__"] for t in toks]
idx = bm25s.BM25(); idx.index(toks, show_progress=False)
res, sc = idx.retrieve(toks, k=min(a.k + 1, len(ids)), n_threads=max(1, os.cpu_count() or 1), show_progress=False)
top = {}
for qi in range(len(ids)):
    top[qi] = [int(res[qi, r]) for r in range(res.shape[1]) if int(res[qi, r]) != qi and sc[qi, r] > 0][:a.k]
log(f"{a.name}: {len(ids):,} records, bm25 on {BM25F} ({a.bm25_tokens}, k={a.k}), {G:,} gold pairs, {sum(len(v) for v in top.values()):,} directed edges")

# undirected neighbour pairs with best rank
best = {}
for u, vs in top.items():
    for r, v in enumerate(vs, 1):
        key = (u, v) if ids[u] < ids[v] else (v, u)
        if key not in best or r < best[key]: best[key] = r
gold_pairs = {(x, y) if x < y else (y, x) for cl in gold_clusters for i, x in enumerate(cl) for y in cl[i + 1:]}
edge_pairs = {(ids[u], ids[v]) for (u, v) in best}
reach_e = len(gold_pairs & edge_pairs)
log(f"undirected neighbour pairs {len(edge_pairs):,} | reach {reach_e:,}/{G:,} = {reach_e/G if G else 0:.3f} | true pairs among them {reach_e/len(edge_pairs):.4f}")

# reference: in-block pairs as REP-ER's round-0 blocks expose them (mutual gate, cap)
topset = {u: set(v) for u, v in top.items()}
inbound = defaultdict(list)
for u, vs in top.items():
    for v in vs: inbound[v].append(u)
bo = defaultdict(set); nblocks = 0; cand = 0; seen = set()
for u in range(len(ids)):
    m = a.gate_rank or a.k
    if not [v for v in top[u][:m] if u in top[v][:m]]: continue
    order = top[u] + [w for w in inbound[u] if w not in topset[u]]
    b = frozenset([u] + order[:a.cap - 1])
    if len(b) < 2 or b in seen: continue
    seen.add(b); nblocks += 1; cand += len(b) * (len(b) - 1) // 2
    for x in b: bo[ids[x]].add(nblocks)
reach_b = sum(1 for x, y in gold_pairs if bo[x] & bo[y])
log(f"reference REP-ER blocks (gate mutual, cap {a.cap}): {nblocks:,} blocks, in-block pairs {cand:,} (with overlap), reach {reach_b:,}/{G:,} = {reach_b/G if G else 0:.3f}")

out = a.out or f"data/cands/{a.name}__bm25_{a.bm25_tokens}_k{a.k}.tsv"
with open(out, "w") as f:
    f.write("id_a\tid_b\trank\n")
    for (u, v), r in sorted(best.items(), key=lambda t: (ids[t[0][0]], ids[t[0][1]])):
        f.write(f"{ids[u]}\t{ids[v]}\t{r}\n")
log(f"wrote {out}")
