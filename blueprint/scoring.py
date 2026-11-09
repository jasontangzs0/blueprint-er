"""Shared scoring for REP-ER and every baseline: one partition in, one line of numbers out.
Mirrors scripts/reper.py::metrics so all methods are scored by the same code path.

Views reported
  all-pairs P/R/F1     pairwise, over ALL closure gold pairs (Songs/Citations primary)
  diff-title P/R/F1    pairs whose normalized first field is identical are unscored (WDC caveat)
  official test P/R/F1 the dataset's labelled test pairs, read from our clusters (WDC primary)
  ACC / FP-measure     LLM-CER's cluster metrics, when their repo is importable
"""
import csv
import sys
from collections import Counter, defaultdict


def load_records(path, id_col="id"):
    recs = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            recs[row[id_col]] = {k: (v or "").strip() for k, v in row.items() if k != id_col}
    return recs


def load_gold(path, rec_ids):
    """gold clusters file (one whitespace-separated cluster per line) -> (clusters, cid map).
    Records absent from the file are singletons with a unique cluster id."""
    clusters = [line.split() for line in open(path) if line.strip()]
    cid = {x: k for k, cl in enumerate(clusters) for x in cl}
    for r in rec_ids:
        cid.setdefault(r, f"s{r}")
    return clusters, cid


def load_test_pairs(path):
    if not path:
        return []
    return [(r["id_a"], r["id_b"], r["label"] == "1") for r in csv.DictReader(open(path))]


def closure(rec_ids, pairs):
    """Transitive closure of accepted pairs -> partition (singletons included), deterministic order."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for x, y in pairs:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx
    groups = defaultdict(list)
    for r in sorted(rec_ids, key=str):
        groups[find(r)].append(r)
    return list(groups.values())


def _c2(counter):
    return sum(n * (n - 1) // 2 for n in counter.values())


def score(partition, recs, cid, gold_clusters=None, test_pairs=(), title_field=None, llmcer_repo=None, subset=None):
    """partition: list of clusters (lists of ids). recs: id -> record dict. cid: id -> gold cluster id."""
    from blueprint.rubric import norm
    pred = {}
    for k, cl in enumerate(partition):
        for x in cl:
            pred[x] = k
    universe = set(subset) if subset else None
    ids = [x for x in recs if (x in universe)] if universe else list(recs)
    tp = _c2(Counter((pred[x], cid[x]) for x in ids))
    P_ = _c2(Counter(pred[x] for x in ids))
    G_ = _c2(Counter(cid[x] for x in ids))
    P = tp / P_ if P_ else 0.0
    R = tp / G_ if G_ else 0.0
    F = 2 * P * R / (P + R) if P + R else 0.0
    out = {"P": P, "R": R, "F1": F, "asserted": P_, "TP": tp, "FP": P_ - tp, "FN": G_ - tp, "clusters": len(partition)}
    line = f"P {P:.3f} R {R:.3f} F1 {F:.3f} | asserted {P_:,} TP {tp:,} FP {P_-tp:,} FN {G_-tp:,} | clusters {len(partition):,}"
    if title_field:
        tk = {x: norm(recs[x].get(title_field, "")) for x in ids}
        tp_same = _c2(Counter((pred[x], cid[x], tk[x]) for x in ids))
        pp_same = _c2(Counter((pred[x], tk[x]) for x in ids))
        g_same = _c2(Counter((cid[x], tk[x]) for x in ids))
        tpd, ppd, gd = tp - tp_same, P_ - pp_same, G_ - g_same
        Pd = tpd / ppd if ppd else 0.0
        Rd = tpd / gd if gd else 0.0
        Fd = 2 * Pd * Rd / (Pd + Rd) if Pd + Rd else 0.0
        out.update({"diff_P": Pd, "diff_R": Rd, "diff_F1": Fd})
        line += f" | diff-title P {Pd:.3f} R {Rd:.3f} F1 {Fd:.3f}"
    if llmcer_repo and gold_clusters is not None and not universe:
        try:
            if llmcer_repo not in sys.path:
                sys.path.insert(0, llmcer_repo)
            from llmcer.metrics import calculate_acc, calculate_fp_measure
            in_gold = {x for c in gold_clusters for x in c}
            gold_full = [list(c) for c in gold_clusters] + [[r] for r in recs if r not in in_gold]
            acc, fp = calculate_acc(gold_full, partition), calculate_fp_measure(gold_full, partition)
            out.update({"ACC": acc, "FPm": fp})
            line += f" | ACC {acc:.3f} FP {fp:.3f}"
        except Exception as e:  # noqa: BLE001
            line += f" | (llmcer metrics failed: {str(e)[:40]})"
    if test_pairs:
        tps = [(x, y, l) for x, y, l in test_pairs if not universe or (x in universe and y in universe)]
        tp2 = sum(1 for x, y, l in tps if l and pred.get(x) == pred.get(y))
        pp = sum(1 for x, y, l in tps if pred.get(x) == pred.get(y))
        gp = sum(1 for _, _, l in tps if l)
        p2 = tp2 / pp if pp else 0.0
        r2 = tp2 / gp if gp else 0.0
        f2 = 2 * p2 * r2 / (p2 + r2) if p2 + r2 else 0.0
        out.update({"test_P": p2, "test_R": r2, "test_F1": f2, "test_pairs": len(tps)})
        line += f" | official test ({len(tps)} pairs) P {p2:.3f} R {r2:.3f} F1 {f2:.3f}"
    out["line"] = line
    return out
