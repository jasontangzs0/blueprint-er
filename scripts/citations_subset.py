"""Entity-level subset of Citations with COMPLETE gold: sample entities (incl. singletons)
uniformly, keep all their records. Writes a unified CSV (id, source, title, authors,
journal, year) + gold clusters (one line per multi-record entity, ids space-separated).
Usage: PYTHONPATH=. .venv/bin/python scripts/citations_subset.py [n_entities] [seed]
"""
import csv, os, random, sys
from collections import defaultdict, Counter
from blueprint.citations import load_citations

N_ENT = int(sys.argv[1]) if len(sys.argv) > 1 else 45_000
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 11
recs = load_citations("data/benchmarks/citations/citations/citeseer.csv",
                      "data/benchmarks/citations/citations/dblp.csv",
                      "data/benchmarks/citations/citations/matches_citeseer_dblp.csv")
by_ent = defaultdict(list)
for r in recs:
    by_ent[r["cluster_id"]].append(r)
sizes = Counter(len(v) for v in by_ent.values())
print(f"full: {len(recs):,} records, {len(by_ent):,} entities; size dist: "
      f"{ {k: sizes[k] for k in sorted(sizes)[:6]} } ... max {max(sizes)}")
rng = random.Random(SEED)
ents = rng.sample(list(by_ent), N_ENT)
sub = [r for e in ents for r in by_ent[e]]
out = f"data/benchmarks/citations/subset_{N_ENT//1000}k"
os.makedirs(out, exist_ok=True)
with open(f"{out}/records.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["id", "source", "title", "authors", "journal", "year"])
    for r in sub:
        w.writerow([r["id"], r["source_domain"], r["title"] or "", r["brand"] or "", r["description"] or "", r["year"] or ""])
with open(f"{out}/gold_clusters.txt", "w") as f:
    for e in ents:
        if len(by_ent[e]) >= 2:
            f.write(" ".join(r["id"] for r in by_ent[e]) + "\n")
pairs = sum(len(by_ent[e]) * (len(by_ent[e]) - 1) // 2 for e in ents)
multi = sum(1 for e in ents if len(by_ent[e]) >= 2)
src = Counter(r["source_domain"] for r in sub)
print(f"subset: {len(sub):,} records ({dict(src)}), {N_ENT:,} entities ({multi:,} multi-record), "
      f"{pairs:,} true pairs -> {out}/")
