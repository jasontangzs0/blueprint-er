"""WDC-Four-Goods (working name): four more product worlds cut from the WDC Product Data Corpus v2 (English,
2019, CC0), in two versions over the SAME products with copies.

  plain : copies of a product chosen at random; singletons chosen at random (the WDC-Four-Domains recipe).
  hard  : copies chosen to disagree most (farthest-first on TF-IDF titles); singletons are the chosen products'
          nearest OTHER products by title (siblings: next model number, other colourway, other pack size),
          the corner-case idea of the WDC Products benchmark (Peeters, Der & Bizer, EDBT 2024).

Gold = the corpus cluster id (shop-published GTIN/MPN). Every included product is either in with several
listings or in with one, and no other listing of it is in the dataset, so the gold has no unlabelled copies
by construction. No human-checked test pairs exist for these categories.

Pass 1 (`scan_index`) streams the 3 GB corpus once and writes one TSV per category (cluster_id, offer_id,
title). Selection works on those files. Pass 2 (`fetch_offers`) streams the corpus again for the full
fields of the selected listings only. Record shape as WDC-Four-Domains: id, source (category), title, brand,
price, description, cleaned with the same `clean_value`.
"""
import csv
import gzip
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from blueprint.wdc_four_domains import FIELDS, clean_value, _id_key

csv.field_size_limit(sys.maxsize)

DEFAULT_CATEGORIES = ("Clothing", "Home_and_Garden", "Sports_and_Outdoors", "Automotive")   # Toys_and_Games dropped: corpus label is mostly noise


def scan_index(corpus_gz, categories: Iterable[str], out_dir, limit: int = 0) -> Dict[str, int]:
    """Pass 1: <out_dir>/index_<category>.tsv with cluster_id, offer_id, cleaned title, for the categories."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    handles = {c: (out / f"index_{c}.tsv").open("w", encoding="utf-8") for c in categories}
    counts: Counter = Counter()
    with gzip.open(corpus_gz, "rt", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            if not line.strip():
                continue
            r = json.loads(line)
            h = handles.get(r.get("category"))
            if h is None:
                continue
            title = clean_value(r.get("title")).replace("\t", " ")
            h.write(f"{r['cluster_id']}\t{r['id']}\t{title}\n")
            counts[r["category"]] += 1
    for h in handles.values():
        h.close()
    json.dump(counts, (out / "index_counts.json").open("w"))
    return dict(counts)


def load_index(path) -> Dict[str, List[Tuple[str, str]]]:
    """cluster_id -> [(offer_id, title)] in file order."""
    clusters: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            cid, oid, title = line.rstrip("\n").split("\t", 2)
            clusters[cid].append((oid, title))
    return clusters


def choose_products(clusters: Dict[str, List[Tuple[str, str]]], exclude: Set[str], record_budget: int,
                    cap: int, max_size: int, seed: int) -> Dict[str, int]:
    """Products with copies for ONE category -> {cluster_id: number of listings to include}.
    Uniform over clusters with 2..max_size titled listings, filled until record_budget listings."""
    rng = random.Random(seed)
    eligible = sorted(c for c, L in clusters.items()
                      if 2 <= len(L) <= max_size and c not in exclude and all(t for _, t in L))
    rng.shuffle(eligible)
    chosen: Dict[str, int] = {}
    total = 0
    for c in eligible:
        k = min(len(clusters[c]), cap)
        if total + k > record_budget:
            continue
        chosen[c] = k
        total += k
        if total >= record_budget:
            break
    if total < record_budget:                       # exact budget: one more product of just the right size
        for c in eligible:
            if c not in chosen and min(len(clusters[c]), cap) == record_budget - total:
                chosen[c] = record_budget - total
                break
    return chosen


def _vectorizer(titles: List[str]):
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(lowercase=True, token_pattern=r"[A-Za-z0-9]+", min_df=1, dtype=np.float32)
    return vec, vec.fit_transform(titles)


def plain_members(clusters, chosen: Dict[str, int], seed: int) -> Dict[str, List[str]]:
    rng = random.Random(seed)
    out = {}
    for c, k in chosen.items():
        L = list(clusters[c]); rng.shuffle(L)
        out[c] = [oid for oid, _ in L[:k]]
    return out


def hard_members(clusters, chosen: Dict[str, int], seed: int) -> Dict[str, List[str]]:
    """Same number of listings per product as plain, but the ones that disagree most (farthest-first)."""
    import numpy as np
    rng = random.Random(seed)
    out = {}
    for c, k in chosen.items():
        L = list(clusters[c])
        if k >= len(L):
            out[c] = [oid for oid, _ in L]
            continue
        _, X = _vectorizer([t for _, t in L])
        sims = (X @ X.T).toarray()
        picked = [rng.randrange(len(L))]
        while len(picked) < k:
            worst = sims[:, picked].max(axis=1)
            worst[picked] = 2.0
            picked.append(int(worst.argmin()))
        out[c] = [L[i][0] for i in picked]
    return out


def plain_singletons(clusters, chosen: Dict[str, int], exclude: Set[str], n: int, seed: int) -> Dict[str, str]:
    """n random other products, one random titled listing each -> {cluster_id: offer_id}."""
    rng = random.Random(seed)
    pool = sorted(c for c, L in clusters.items() if c not in chosen and c not in exclude and any(t for _, t in L))
    picks = rng.sample(pool, n)
    out = {}
    for c in picks:
        titled = [oid for oid, t in clusters[c] if t]
        out[c] = rng.choice(titled)
    return out


def hard_singletons(clusters, chosen: Dict[str, int], exclude: Set[str], n: int, seed: int,
                    per_product: int = 8, chunk: int = 32, max_sim: float = 0.9) -> Dict[str, str]:
    """n sibling products: the chosen products' nearest other products by TF-IDF title cosine, taken
    round-robin (each chosen product's nearest unused neighbour first) -> {cluster_id: offer_id}.
    A neighbour whose title is near-identical (cosine >= max_sim) to ANY listing of a chosen product is
    skipped: that is usually the same product under a second identifier, not a sibling."""
    import numpy as np
    rng = random.Random(seed)
    pool = sorted(c for c, L in clusters.items() if c not in chosen and c not in exclude and any(t for _, t in L))
    rep = {c: next(t for _, t in clusters[c] if t) for c in pool}
    vec, X = _vectorizer([rep[c] for c in pool])
    chosen_ids = sorted(chosen)
    Q = vec.transform([next(t for _, t in clusters[c] if t) for c in chosen_ids])
    copies = vec.transform([t for c in chosen_ids for _, t in clusters[c] if t])   # every listing of every chosen product
    neigh: Dict[str, List[str]] = {}
    for s in range(0, len(chosen_ids), chunk):
        S = (Q[s:s + chunk] @ X.T).toarray()
        for row, c in zip(S, chosen_ids[s:s + chunk]):
            top = np.argpartition(-row, per_product)[:per_product]
            top = top[np.argsort(-row[top])]
            cand = [pool[j] for j in top if row[j] > 0]
            if cand:
                near = (vec.transform([rep[x] for x in cand]) @ copies.T).toarray().max(axis=1)
                cand = [x for x, m in zip(cand, near) if m < max_sim]
            neigh[c] = cand
    out: Dict[str, str] = {}
    order = list(chosen_ids); rng.shuffle(order)
    for depth in range(per_product):
        for c in order:
            if len(out) >= n:
                break
            cand = neigh.get(c, [])
            if depth < len(cand) and cand[depth] not in out:
                out[cand[depth]] = next(oid for oid, t in clusters[cand[depth]] if t)   # the listing the filter judged
        if len(out) >= n:
            break
    if len(out) < n:  # not enough distinct siblings: top up at random so both versions have the same count
        out.update(plain_singletons(clusters, {**chosen, **{c: 1 for c in out}}, exclude, n - len(out), seed + 1))
    return out


def fetch_offers(corpus_gz, wanted: Set[str]) -> Dict[str, dict]:
    """Pass 2: full fields for the wanted offer ids -> {offer_id: {cluster_id, category, fields..., identifiers}}."""
    found: Dict[str, dict] = {}
    with gzip.open(corpus_gz, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            oid = str(r["id"])
            if oid not in wanted:
                continue
            rec = {"cluster_id": str(r["cluster_id"]), "category": r.get("category"), "identifiers": r.get("identifiers")}
            for f in FIELDS:
                rec[f] = clean_value(r.get(f))
            found[oid] = rec
            if len(found) == len(wanted):
                break
    return found


def write_version(out_dir, offers: Dict[str, dict], members: Dict[str, List[str]], singles: Dict[str, str],
                  source_of: Dict[str, str], info: dict) -> dict:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rows = [(oid, source_of[c]) for c, ids in members.items() for oid in ids] + [(oid, source_of[c]) for c, oid in singles.items()]
    rows.sort(key=lambda x: (x[1], _id_key(x[0])))
    with (out / "records.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["id", "source", *FIELDS])
        for oid, src in rows:
            w.writerow([oid, src, *(offers[oid][f] for f in FIELDS)])
    with (out / "gold_clusters.txt").open("w", encoding="utf-8") as fh:
        for c in sorted(members, key=_id_key):
            if len(members[c]) >= 2:
                fh.write(" ".join(sorted(members[c], key=_id_key)) + "\n")
    with (out / "identifiers.jsonl").open("w", encoding="utf-8") as fh:
        for oid, _ in rows:
            fh.write(json.dumps({"id": oid, "cluster_id": offers[oid]["cluster_id"], "identifiers": offers[oid]["identifiers"]}) + "\n")
    sizes = Counter(len(ids) for ids in members.values())
    stats = {"records": len(rows), "products": len(members) + len(singles), "dup_products": sum(1 for v in members.values() if len(v) >= 2),
             "records_in_dup": sum(len(v) for v in members.values()), "singletons": len(singles),
             "extra_copies": sum(len(v) - 1 for v in members.values()), "largest": max(sizes),
             "true_pairs": sum(n * (n - 1) // 2 for n in (len(v) for v in members.values())),
             "size_histogram": dict(sorted(sizes.items())),
             "per_category": {s: dict(Counter(src for _, src in rows))[s] for s in sorted({src for _, src in rows})},
             **info}
    json.dump(stats, (out / "build_info.json").open("w"), indent=1)
    return stats


# ---- hard positives: products whose copies are written in more than one language ---------------------------
def tag_languages(index_path, out_path, min_words: int = 4, min_prob: float = 0.9) -> int:
    """Detect the language of every titled listing of products with 2+ listings; write offer_id<TAB>lang
    ('' when undecided) to out_path. langdetect, seeded, so the tags are reproducible."""
    from langdetect import DetectorFactory, detect_langs
    DetectorFactory.seed = 0
    clusters = load_index(index_path)
    n = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for c, L in clusters.items():
            if len(L) < 2:
                continue
            for oid, title in L:
                lang = ""
                if title and len(title.split()) >= min_words:
                    try:
                        best = detect_langs(title)[0]
                        if best.prob >= min_prob:
                            lang = best.lang
                    except Exception:
                        lang = ""
                fh.write(f"{oid}\t{lang}\n"); n += 1
    return n


def load_language_tags(path) -> Dict[str, str]:
    tags = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            oid, lang = line.rstrip("\n").split("\t")
            if lang:
                tags[oid] = lang
    return tags


def multilingual_products(clusters, tags: Dict[str, str]) -> Set[str]:
    """Products with copies tagged in at least two languages, at least one of them not English."""
    out = set()
    for c, L in clusters.items():
        langs = {tags[oid] for oid, _ in L if oid in tags}
        if len(langs) >= 2 and langs - {"en"}:
            out.add(c)
    return out


def choose_products_mixed(clusters, exclude: Set[str], record_budget: int, cap: int, max_size: int, seed: int,
                          preferred: Set[str], preferred_share: float) -> Dict[str, int]:
    """Like choose_products, but fills up to `preferred_share` of the record budget from `preferred` products
    first (uniformly among them), then the rest uniformly from everything eligible."""
    rng = random.Random(seed)
    eligible = sorted(c for c, L in clusters.items()
                      if 2 <= len(L) <= max_size and c not in exclude and all(t for _, t in L))
    pref = [c for c in eligible if c in preferred]
    rng.shuffle(pref); rng.shuffle(eligible)
    chosen: Dict[str, int] = {}
    total = 0
    for c in pref:
        k = min(len(clusters[c]), cap)
        if total + k > record_budget * preferred_share:
            continue
        chosen[c] = k; total += k
    for c in eligible:
        if c in chosen:
            continue
        k = min(len(clusters[c]), cap)
        if total + k > record_budget:
            continue
        chosen[c] = k; total += k
        if total >= record_budget:
            break
    return chosen
