"""Build WDC-Four-Goods, plain and hard versions over the same products (see blueprint/wdc_four_goods.py).

Usage: PYTHONPATH=. .venv/bin/python scripts/wdc_four_goods_build.py \
   --corpus data/raw/wdc-lspc-v2/offers_corpus_english_v2.json.gz --index data/processed/wdc-lspc-v2 \
   --out data/benchmarks/wdc-four-goods [--categories Clothing,Home_and_Garden,Sports_and_Outdoors,Automotive] \
   [--records 10000] [--singletons 220] [--cap 12] [--max-size 100] [--seed 0] \
   [--exclude data/benchmarks/wdc-four-domains/product_cluster_ids.json] [--skip-scan] [--scan-limit N]
"""
import argparse, json, os, random, time
from blueprint.wdc_four_goods import (DEFAULT_CATEGORIES, scan_index, load_index, choose_products, plain_members,
                                    hard_members, plain_singletons, hard_singletons, fetch_offers, write_version)

ap = argparse.ArgumentParser()
ap.add_argument("--corpus", required=True); ap.add_argument("--index", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES)); ap.add_argument("--records", type=int, default=10000)
ap.add_argument("--singletons", type=int, default=220, help="singleton products per category")
ap.add_argument("--cap", type=int, default=12); ap.add_argument("--max-size", type=int, default=100); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--exclude", default="data/benchmarks/wdc-four-domains/product_cluster_ids.json")
ap.add_argument("--skip-scan", action="store_true"); ap.add_argument("--scan-limit", type=int, default=0)
a = ap.parse_args()
T0 = time.time(); log = lambda m: print(f"[{time.time()-T0:.0f}s] {m}", flush=True)
cats = [c.strip() for c in a.categories.split(",") if c.strip()]
exclude = set(json.load(open(a.exclude))) if a.exclude and os.path.exists(a.exclude) else set()

if not a.skip_scan:
    log(f"pass 1: indexing {cats} from {a.corpus}")
    log(f"indexed offers per category: {scan_index(a.corpus, cats, a.index, a.scan_limit)}")
budget = (a.records - a.singletons * len(cats)) // len(cats)
members_p, members_h, singles_p, singles_h, source_of = {}, {}, {}, {}, {}
for i, c in enumerate(cats):
    clusters = load_index(os.path.join(a.index, f"index_{c}.tsv"))
    n_dup = sum(1 for L in clusters.values() if len(L) >= 2)
    chosen = choose_products(clusters, exclude, budget, a.cap, a.max_size, a.seed + i)
    log(f"{c}: {len(clusters):,} products in the corpus, {n_dup:,} with 2+ listings; chose {len(chosen)} with "
        f"{sum(chosen.values())} listings (budget {budget}) + {a.singletons} singletons")
    members_p.update(plain_members(clusters, chosen, a.seed + i)); members_h.update(hard_members(clusters, chosen, a.seed + i))
    singles_p.update(plain_singletons(clusters, chosen, exclude, a.singletons, a.seed + i))
    singles_h.update(hard_singletons(clusters, chosen, exclude, a.singletons, a.seed + i))
    for cl in list(chosen) + list(singles_p) + list(singles_h):
        source_of.setdefault(cl, c)
    del clusters
wanted = {o for ids in list(members_p.values()) + list(members_h.values()) for o in ids} | set(singles_p.values()) | set(singles_h.values())
log(f"pass 2: fetching {len(wanted):,} listings")
offers = fetch_offers(a.corpus, wanted)
missing = wanted - set(offers)
log(f"fetched {len(offers):,}; missing {len(missing)}")
assert not missing, "corpus pass 2 did not find every selected listing"
info = {"build": {"records": a.records, "singletons_per_category": a.singletons, "cap": a.cap, "max_size": a.max_size,
                  "seed": a.seed, "categories": cats, "excluded_products": len(exclude), "corpus": a.corpus}}
for name, mem, sing in (("plain", members_p, singles_p), ("hard", members_h, singles_h)):
    s = write_version(os.path.join(a.out, name), offers, mem, sing, source_of, {**info, "version": name})
    log(f"{name}: {s['records']:,} records; {s['products']:,} products; {s['dup_products']:,} with copies holding "
        f"{s['records_in_dup']:,}; singletons {s['singletons']:,}; extra copies {s['extra_copies']:,}; largest {s['largest']}; "
        f"true pairs {s['true_pairs']:,}; per category {s['per_category']}")
same = set(members_p) == set(members_h) and all(len(members_p[c]) == len(members_h[c]) for c in members_p)
log(f"same products with copies and same per-product counts in both versions: {same}; "
    f"shared singleton products: {len(set(singles_p) & set(singles_h))}")
