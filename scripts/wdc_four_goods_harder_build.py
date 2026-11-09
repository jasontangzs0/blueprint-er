"""Build the `harder` version of WDC-Four-Goods: same recipe as `hard` (sibling singletons), but the products
with copies are drawn first from products whose copies are written in more than one language (hard positives
that are genuine matches, unlike dissimilar-title pairs, half of which are identifier collisions), up to
`--multilingual-share` of the record budget, the rest uniformly.

Usage: PYTHONPATH=. .venv/bin/python scripts/wdc_four_goods_harder_build.py \
   --corpus data/raw/wdc-lspc-v2/offers_corpus_english_v2_nonnorm.json.gz --index data/processed/wdc-lspc-v2 \
   --out data/benchmarks/wdc-four-goods/harder [--multilingual-share 0.5] [--records 10000] [--singletons 220] \
   [--cap 12] [--max-size 100] [--seed 0] [--exclude data/benchmarks/wdc-four-domains/product_cluster_ids.json]
Needs lang_<category>.tsv in --index (from blueprint.wdc_four_goods.tag_languages).
"""
import argparse, json, os, time
from collections import Counter
from blueprint.wdc_four_goods import (DEFAULT_CATEGORIES, load_index, load_language_tags, multilingual_products,
                                    choose_products_mixed, hard_members, hard_singletons, fetch_offers, write_version)

ap = argparse.ArgumentParser()
ap.add_argument("--corpus", required=True); ap.add_argument("--index", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES)); ap.add_argument("--multilingual-share", type=float, default=0.5)
ap.add_argument("--records", type=int, default=10000); ap.add_argument("--singletons", type=int, default=220)
ap.add_argument("--cap", type=int, default=12); ap.add_argument("--max-size", type=int, default=100); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--exclude", default="data/benchmarks/wdc-four-domains/product_cluster_ids.json")
a = ap.parse_args()
T0 = time.time(); log = lambda m: print(f"[{time.time()-T0:.0f}s] {m}", flush=True)
cats = [c.strip() for c in a.categories.split(",") if c.strip()]
exclude = set(json.load(open(a.exclude))) if a.exclude and os.path.exists(a.exclude) else set()
budget = (a.records - a.singletons * len(cats)) // len(cats)
members, singles, source_of, ml_share = {}, {}, {}, {}
for i, c in enumerate(cats):
    clusters = load_index(os.path.join(a.index, f"index_{c}.tsv"))
    tags = load_language_tags(os.path.join(a.index, f"lang_{c}.tsv"))
    ml = multilingual_products(clusters, tags)
    chosen = choose_products_mixed(clusters, exclude, budget, a.cap, a.max_size, a.seed + i, ml, a.multilingual_share)
    n_ml = sum(1 for x in chosen if x in ml)
    ml_share[c] = {"multilingual_products_available": len(ml), "chosen": len(chosen), "chosen_multilingual": n_ml,
                   "records_multilingual": sum(k for x, k in chosen.items() if x in ml)}
    log(f"{c}: {len(ml):,} multilingual products available; chose {len(chosen)} products ({n_ml} multilingual, "
        f"{ml_share[c]['records_multilingual']} of {sum(chosen.values())} listings) + {a.singletons} sibling singletons")
    members.update(hard_members(clusters, chosen, a.seed + i))
    singles.update(hard_singletons(clusters, chosen, exclude, a.singletons, a.seed + i))
    for cl in list(chosen) + list(singles):
        source_of.setdefault(cl, c)
    del clusters
wanted = {o for ids in members.values() for o in ids} | set(singles.values())
log(f"pass 2: fetching {len(wanted):,} listings")
offers = fetch_offers(a.corpus, wanted); assert not (wanted - set(offers)), "pass 2 did not find every listing"
info = {"build": {"records": a.records, "singletons_per_category": a.singletons, "cap": a.cap, "max_size": a.max_size, "seed": a.seed,
                  "categories": cats, "excluded_products": len(exclude), "corpus": a.corpus, "multilingual_share": a.multilingual_share},
        "multilingual": ml_share, "version": "harder"}
s = write_version(a.out, offers, members, singles, source_of, info)
log(f"harder: {s['records']:,} records; {s['products']:,} products; {s['dup_products']:,} with copies holding {s['records_in_dup']:,}; "
    f"singletons {s['singletons']:,}; extra copies {s['extra_copies']:,}; largest {s['largest']}; true pairs {s['true_pairs']:,}; per category {s['per_category']}")
