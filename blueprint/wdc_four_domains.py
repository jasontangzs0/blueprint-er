"""WDC-Four-Domains: one dedup dataset cut from the four hand-checked category sets of the
WDC Product Data Corpus v2 (Mannheim, 2019; CC0): computers, cameras, watches, shoes.

Sources (data/raw/wdc-lspc-v2/, the v2_nonnorm release: original text; the normalised release lower-cases
and strips punctuation in the training sets only): <cat>_gs.json.gz (the 1,100-pair checked test set per category,
300 matches each) and <cat>_train.zip (the xlarge training pairs, used only as a pool of extra
listings of the same products). Pool: 15,179 listings of 2,485 products; 4,399 checked pairs over
4,687 listings. Every checked-pair listing is kept, so the whole checked test set stays scorable.

Composition (deterministic): keep all gold listings; of the products that have a single gold
listing, leave `n_singletons` as singletons; fill the other products round-robin, smallest first,
with their training-pool listings, at most `cap` per product, until `n_records` is reached.
Gold = the corpus cluster id (shop-published GTIN/MPN), the same gold type as WDC Block.

Record shape mirrors data/benchmarks/wdc-block/official_s: id (the corpus offer id), source (the
category set the listing came from), title, brand, price, description. Values are cleaned of the
corpus' quote marks and language tags ("..."@en) and whitespace is collapsed; nothing else.
"""
import csv
import gzip
import json
import random
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

csv.field_size_limit(sys.maxsize)

CATEGORIES = ("computers", "cameras", "watches", "shoes")
FIELDS = ("title", "brand", "price", "description")
_TAG = re.compile(r'"\s*@[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*')
_WS = re.compile(r"\s+")


def clean_value(value) -> str:
    """'"Gigabyte"@en' -> 'Gigabyte'; ' "A"@en "B | shop"@en' -> 'A B | shop'; None/'None' -> ''."""
    if value is None:
        return ""
    text = str(value)
    if text in ("None", "nan", "NaN", "null"):
        return ""
    text = _TAG.sub('"', text).replace('"', " ")
    return _WS.sub(" ", text).strip()


def _offer(row: dict, side: str, cat: str) -> dict:
    rec = {"id": str(row[f"id_{side}"]), "cluster_id": str(row[f"cluster_id_{side}"]), "source": cat}
    for f in FIELDS:
        rec[f] = clean_value(row.get(f"{f}_{side}"))
    return rec


def _put(offers: Dict[str, dict], rec: dict) -> None:
    old = offers.get(rec["id"])
    if old is None:
        offers[rec["id"]] = rec
    elif old["cluster_id"] != rec["cluster_id"]:
        raise ValueError(f"offer {rec['id']} carries two cluster ids: {old['cluster_id']} vs {rec['cluster_id']}")


def _rows(handle) -> Iterable[dict]:
    for line in handle:
        if line.strip():
            yield json.loads(line)


def load_pool(raw_dir) -> Tuple[Dict[str, dict], Set[str], List[Tuple[str, str, int]]]:
    """-> (offers by id, ids of the checked-pair listings, checked pairs (id_a, id_b, label))."""
    raw = Path(raw_dir)
    offers: Dict[str, dict] = {}
    gold_ids: Set[str] = set()
    pairs: Dict[Tuple[str, str], int] = {}
    for cat in CATEGORIES:
        with gzip.open(raw / f"{cat}_gs.json.gz", "rt", encoding="utf-8") as fh:
            for r in _rows(fh):
                for side in ("left", "right"):
                    rec = _offer(r, side, cat)
                    _put(offers, rec)
                    gold_ids.add(rec["id"])
                a, b = str(r["id_left"]), str(r["id_right"])
                key = (a, b) if a < b else (b, a)
                label = int(r["label"])
                if pairs.get(key, label) != label:
                    raise ValueError(f"checked pair {key} labelled both ways")
                pairs[key] = label
        with zipfile.ZipFile(raw / f"{cat}_train.zip") as z:
            name = next(n for n in z.namelist() if n.endswith("_xlarge.json.gz"))
            with gzip.open(z.open(name), "rt", encoding="utf-8") as fh:
                for r in _rows(fh):
                    for side in ("left", "right"):
                        _put(offers, _offer(r, side, cat))
    return offers, gold_ids, [(a, b, l) for (a, b), l in sorted(pairs.items())]


def _id_key(oid: str):
    return (len(oid), oid)


def compose(offers: Dict[str, dict], gold_ids: Set[str], n_records: int = 10000,
            n_singletons: int = 1000, cap: int = 8, seed: int = 0) -> Dict[str, List[str]]:
    """-> chosen listings per cluster id. Keeps every gold listing; see the module docstring."""
    rng = random.Random(seed)
    by_cluster: Dict[str, List[str]] = defaultdict(list)
    for oid in sorted(offers, key=_id_key):
        by_cluster[offers[oid]["cluster_id"]].append(oid)
    gold_in = {c: [o for o in ids if o in gold_ids] for c, ids in by_cluster.items()}
    orphan = [c for c, g in gold_in.items() if not g]
    if orphan:
        raise ValueError(f"{len(orphan)} clusters carry no checked-pair listing")
    single = sorted(c for c, g in gold_in.items() if len(g) == 1)
    if n_singletons > len(single):
        raise ValueError(f"only {len(single)} products have a single gold listing; cannot keep {n_singletons} singletons")
    keep_single = set(rng.sample(single, n_singletons))
    chosen = {c: list(g) for c, g in gold_in.items()}
    total = sum(len(v) for v in chosen.values())
    if total > n_records:
        raise ValueError(f"the {total} gold listings alone exceed n_records={n_records}")
    spare: Dict[str, List[str]] = {}
    for c, ids in by_cluster.items():
        if c in keep_single:
            continue
        extra = [o for o in ids if o not in gold_ids]
        rng.shuffle(extra)
        spare[c] = extra
    while total < n_records:
        order = sorted((c for c in spare if spare[c] and len(chosen[c]) < cap), key=lambda c: (len(chosen[c]), c))
        if not order:
            break
        for c in order:
            if total >= n_records:
                break
            chosen[c].append(spare[c].pop())
            total += 1
    return chosen


def stats(offers: Dict[str, dict], chosen: Dict[str, List[str]], pairs) -> dict:
    kept = {o for ids in chosen.values() for o in ids}
    sizes = Counter(len(ids) for ids in chosen.values())
    dup = {c: ids for c, ids in chosen.items() if len(ids) >= 2}
    per_cat: Dict[str, Counter] = defaultdict(Counter)
    for c, ids in chosen.items():
        cat = offers[ids[0]]["source"]
        per_cat[cat]["records"] += len(ids)
        per_cat[cat]["products"] += 1
        if len(ids) >= 2:
            per_cat[cat]["dup_products"] += 1
            per_cat[cat]["records_in_dup"] += len(ids)
    pair_cat: Dict[str, Counter] = defaultdict(Counter)
    for a, b, l in pairs:
        cat = offers[a]["source"]
        pair_cat[cat]["pairs"] += 1
        pair_cat[cat]["matches"] += l
    true_pairs = sum(n * (n - 1) // 2 for n in (len(ids) for ids in dup.values()))
    return {
        "records": len(kept), "products": len(chosen), "dup_products": len(dup),
        "records_in_dup": sum(len(v) for v in dup.values()), "singletons": len(chosen) - len(dup),
        "extra_copies": sum(len(v) - 1 for v in dup.values()), "largest": max(sizes), "true_pairs": true_pairs,
        "size_histogram": dict(sorted(sizes.items())),
        "checked_pairs": len(pairs), "checked_matches": sum(l for _, _, l in pairs),
        "checked_pairs_resolvable": sum(a in kept and b in kept for a, b, _ in pairs),
        "per_category": {cat: dict(per_cat[cat]) | dict(pair_cat[cat]) for cat in CATEGORIES},
    }


def write(out_dir, offers: Dict[str, dict], chosen: Dict[str, List[str]], pairs, info: dict) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    kept = sorted((o for ids in chosen.values() for o in ids), key=lambda o: (offers[o]["source"], _id_key(o)))
    with (out / "records.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "source", *FIELDS])
        for o in kept:
            w.writerow([o, offers[o]["source"], *(offers[o][f] for f in FIELDS)])
    with (out / "gold_clusters.txt").open("w", encoding="utf-8") as fh:
        for c in sorted(chosen, key=_id_key):
            if len(chosen[c]) >= 2:
                fh.write(" ".join(sorted(chosen[c], key=_id_key)) + "\n")
    kept_set = set(kept)
    with (out / "test_pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id_a", "id_b", "label"])
        for a, b, l in pairs:
            if a in kept_set and b in kept_set:
                w.writerow([a, b, l])
    with (out / "build_info.json").open("w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=1)
