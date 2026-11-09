"""Entity-level subset of Songs (MSD) with COMPLETE gold: closure of matches_msd_msd.csv defines entities
(singletons included); entities are sampled uniformly until the record budget is met, keeping every record of a
sampled entity. Writes records.csv (id,title,release,artist_name,duration,year) + gold_clusters.txt.
Usage: PYTHONPATH=. .venv/bin/python scripts/songs_subset.py [n_records=50000] [seed=11]
"""
import csv, os, random, sys
from collections import defaultdict, Counter
N_REC = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 11
D = "data/benchmarks/songs/songs"
parent = {}
def find(x):
    while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
    return x
for row in csv.DictReader(open(f"{D}/matches_msd_msd.csv")):
    a, b = row["id1"], row["id2"]; parent.setdefault(a, a); parent.setdefault(b, b); parent[find(a)] = find(b)
rows = {r["id"]: r for r in csv.DictReader(open(f"{D}/msd.csv", encoding="utf-8", errors="replace"))}
by_ent = defaultdict(list)
for rid in rows: by_ent[find(rid) if rid in parent else rid].append(rid)
sizes = Counter(len(v) for v in by_ent.values())
print(f"full: {len(rows):,} records, {len(by_ent):,} entities, {sum(n*(n-1)//2 for n in sizes.elements()):,} true pairs; sizes {dict(sorted(sizes.items())[:6])} ... max {max(sizes)}")
ents = list(by_ent); random.Random(SEED).shuffle(ents)
sub, chosen = [], []
for e in ents:
    if len(sub) >= N_REC: break
    chosen.append(e); sub.extend(by_ent[e])
out = f"data/benchmarks/songs/subset_{N_REC//1000}k"; os.makedirs(out, exist_ok=True)
with open(f"{out}/records.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["id", "title", "release", "artist_name", "duration", "year"])
    for rid in sorted(sub, key=int):
        r = rows[rid]; w.writerow([rid, r["title"], r["release"], r["artist_name"], r["duration"], r["year"] if r["year"] not in ("0", "") else ""])
with open(f"{out}/gold_clusters.txt", "w") as f:
    for e in chosen:
        if len(by_ent[e]) >= 2: f.write(" ".join(by_ent[e]) + "\n")
pairs = sum(len(by_ent[e]) * (len(by_ent[e]) - 1) // 2 for e in chosen); multi = sum(1 for e in chosen if len(by_ent[e]) >= 2)
print(f"subset: {len(sub):,} records, {len(chosen):,} entities ({multi:,} multi-record), {pairs:,} true pairs -> {out}/")
