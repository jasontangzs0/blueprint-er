"""Build WDC-Four-Domains (see blueprint/wdc_four_domains.py for the design).

Usage: PYTHONPATH=. .venv/bin/python scripts/wdc_four_domains_build.py \
   --raw data/raw/wdc-lspc-v2 --out data/benchmarks/wdc-four-domains [--records 10000] [--singletons 1000] [--cap 8] [--seed 0]
Raw files: <cat>_gs.json.gz and <cat>_train.zip for computers, cameras, watches, shoes from
https://data.dws.informatik.uni-mannheim.de/largescaleproductcorpus/data/v2_nonnorm/{goldstandards,trainsets}/ (ids and cluster ids identical to the normalised release)
"""
import argparse, json, random
from blueprint.wdc_four_domains import CATEGORIES, load_pool, compose, stats, write

ap = argparse.ArgumentParser()
ap.add_argument("--raw", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--records", type=int, default=10000); ap.add_argument("--singletons", type=int, default=1000)
ap.add_argument("--cap", type=int, default=8); ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()

offers, gold_ids, pairs = load_pool(a.raw)
print(f"pool: {len(offers):,} listings, {len({o['cluster_id'] for o in offers.values()}):,} products, "
      f"{len(gold_ids):,} checked-pair listings, {len(pairs):,} checked pairs")
chosen = compose(offers, gold_ids, a.records, a.singletons, a.cap, a.seed)
info = stats(offers, chosen, pairs)
info["build"] = {"records": a.records, "singletons": a.singletons, "cap": a.cap, "seed": a.seed, "raw": a.raw,
                 "source": "WDC Product Data Corpus v2 gold standards + xlarge training sets (CC0)"}
write(a.out, offers, chosen, pairs, info)
print(f"wrote {a.out}: {info['records']:,} records; {info['products']:,} products; {info['dup_products']:,} with copies "
      f"holding {info['records_in_dup']:,} records; singletons {info['singletons']:,}; extra copies {info['extra_copies']:,} "
      f"({100*info['extra_copies']/info['records']:.1f}%); largest {info['largest']}; true pairs {info['true_pairs']:,}")
print(f"checked pairs {info['checked_pairs']:,} ({info['checked_matches']:,} matches), resolvable {info['checked_pairs_resolvable']:,}")
print("sizes:", info["size_histogram"])
for cat in CATEGORIES:
    print(f"  {cat:10s} " + " ".join(f"{k}={v:,}" for k, v in info["per_category"][cat].items()))
rng = random.Random(1)
for cat in CATEGORIES:
    ids = [o for ids in chosen.values() for o in ids if offers[o]["source"] == cat]
    print(f"-- {cat} title samples")
    for o in rng.sample(ids, 3):
        print(f"   {offers[o]['title'][:110]!r} | brand={offers[o]['brand']!r} price={offers[o]['price']!r}")
