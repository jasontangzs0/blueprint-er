"""Dataset-agnostic adjudication rubric: profile the data, let a strong model write the
dataset-specific matching rubric once, insert it into a generic adjudication template.

Nothing here knows the domain. Attributes are discovered from record keys; hazards,
identity/variant attributes, numeric-evidence thresholds and worked examples are all
derived by the rubric designer from (a) attribute statistics, (b) the previous round's
own merge / keep-apart decisions, (c) random records.
"""
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Sequence, Tuple


def norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _num(v: Any):
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _grams(s: str):
    s = norm(s)
    return set(s[i:i + 3] for i in range(max(1, len(s) - 2)))


def sim3(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / ((len(ga) * len(gb)) ** 0.5 or 1)


# ----------------------------------------------------------------------------- evidence
def evidence_from_clusters(recs: Dict[Any, Dict[str, Any]], clusters: Sequence[Sequence[Any]],
                           blocks: Sequence[Sequence[Any]], fields: Sequence[str],
                           seed: int = 29, n_pos: int = 40, n_neg: int = 40, n_rand: int = 200):
    """Evidence pack from the previous round: one most-divergent duplicate pair per
    cluster (stratified by which field differs), one most-similar kept-apart pair per
    block, random records, and attribute statistics."""
    rng = random.Random(seed)
    text = lambda i: " ".join(str(recs[i].get(f) or "") for f in fields)
    cl_of = {}
    for k, c in enumerate(clusters):
        for m in c:
            cl_of[m] = k
    # positives, stratified by the set of fields that differ
    strata: Dict[str, list] = defaultdict(list)
    for c in clusters:
        if len(c) < 2:
            continue
        best = None
        for x in range(len(c)):
            for y in range(x + 1, len(c)):
                diff = tuple(f for f in fields if norm(recs[c[x]].get(f)) != norm(recs[c[y]].get(f)))
                if not diff:
                    continue
                sv = sim3(text(c[x]), text(c[y]))
                if best is None or sv < best[0]:
                    best = (sv, c[x], c[y], diff)
        if best:
            strata["+".join(best[3])].append(best[:3])
    pos = []
    per = max(8, n_pos // max(1, len(strata)))
    for kind, lst in sorted(strata.items(), key=lambda kv: -len(kv[1])):
        lst.sort(key=lambda t: t[0])
        head, rest = lst[:per * 2 // 3], lst[per * 2 // 3:]
        pos += [(a, b, kind) for _, a, b in head] + [(a, b, kind) for _, a, b in rng.sample(rest, min(per - len(head), len(rest)))]
    # negatives: one per block (most similar kept-apart pair), half most-similar, half random
    per_block = []
    for blk in blocks:
        best = None
        for x in range(len(blk)):
            for y in range(x + 1, len(blk)):
                if cl_of.get(blk[x]) != cl_of.get(blk[y]):
                    sv = sim3(text(blk[x]), text(blk[y]))
                    if best is None or sv > best[0]:
                        best = (sv, blk[x], blk[y])
        if best:
            per_block.append(best)
    per_block.sort(key=lambda t: -t[0])
    half = n_neg // 2
    neg = [(a, b) for _, a, b in per_block[:half]] + [(a, b) for _, a, b in rng.sample(per_block[half:], min(half, max(0, len(per_block) - half)))]
    rand = rng.sample(list(recs), min(n_rand, len(recs)))
    stats = profile(recs, clusters, blocks, fields)
    return {"pos": pos, "neg": neg, "rand": rand, "stats": stats, "strata": {k: len(v) for k, v in strata.items()}}


def profile(recs, clusters, blocks, fields) -> Dict[str, Any]:
    """Per-attribute statistics: cardinality, fill rate, numeric-ness, most frequent
    values (common-value hazard candidates), agreement rate among accepted duplicates
    vs among kept-apart same-block pairs, numeric spread among duplicates."""
    cl_of = {m: k for k, c in enumerate(clusters) for m in c}
    dup_pairs, nondup_pairs = [], []
    rng = random.Random(7)
    for c in clusters:
        if len(c) >= 2:
            dup_pairs.append((c[0], c[1]) if len(c) == 2 else tuple(rng.sample(list(c), 2)))
    for blk in blocks:
        others = [(blk[x], blk[y]) for x in range(len(blk)) for y in range(x + 1, len(blk)) if cl_of.get(blk[x]) != cl_of.get(blk[y])]
        if others:
            nondup_pairs.append(rng.choice(others))
    out = {}
    N = len(recs)
    for f in fields:
        vals = [recs[i].get(f) for i in recs]
        nonempty = [v for v in vals if v not in (None, "")]
        nums = [_num(v) for v in nonempty]
        numeric = len(nonempty) > 0 and sum(v is not None for v in nums) / len(nonempty) >= 0.9
        st: Dict[str, Any] = {"fill_rate": round(len(nonempty) / max(1, N), 3),
                              "distinct_values": len(set(norm(v) for v in nonempty)), "numeric": numeric}
        if not numeric:
            cnt = Counter(norm(v) for v in nonempty)
            st["top_values"] = [(v, n) for v, n in cnt.most_common(8) if n >= 3]
            agree = lambda pairs: round(sum(norm(recs[a].get(f)) == norm(recs[b].get(f)) for a, b in pairs) / max(1, len(pairs)), 3)
            if dup_pairs: st["agreement_among_duplicates"] = agree(dup_pairs)
            if nondup_pairs: st["agreement_among_kept_apart"] = agree(nondup_pairs)
        else:
            def rel(pairs):
                r = []
                for a, b in pairs:
                    x, y = _num(recs[a].get(f)), _num(recs[b].get(f))
                    if x and y:
                        r.append(abs(x - y) / max(x, y))
                return r
            rd, rn = rel(dup_pairs), rel(nondup_pairs)
            q = lambda r, p: round(sorted(r)[min(len(r) - 1, int(p * len(r)))], 3) if r else None
            if rd: st["relative_diff_among_duplicates"] = {"median": q(rd, 0.5), "p75": q(rd, 0.75), "p90": q(rd, 0.9)}
            if rn: st["relative_diff_among_kept_apart"] = {"median": q(rn, 0.5), "p25": q(rn, 0.25)}
        out[f] = st
    return out


# ----------------------------------------------------------------------------- rubric design
RUBRIC_SYSTEM = """You are an expert in entity resolution. You will write the ADJUDICATION RUBRIC for one specific dataset: the dataset-specific guidance a matcher needs to decide whether two records denote the same real-world entity. You are given the record attributes, statistics about each attribute, random sample records, pairs a previous resolution pass confirmed as the SAME entity (note what differs within each pair), and pairs it kept APART despite looking similar.

Derive everything from the evidence; do not assume a domain. Produce a JSON object with exactly these keys:
- "domain_summary": one or two sentences describing what a record is and what "same entity" means here.
- "identity_attributes": attributes that must co-refer (as strings that may vary in form) for a match; for each, the kinds of surface variance that still mean the same value.
- "variant_attributes": attributes that legitimately differ between records of the same entity (so disagreement there is NOT evidence against a match).
- "distinguishing_patterns": patterns inside otherwise-similar records that indicate DIFFERENT entities (e.g. qualifiers, editions, parts, sub-versions) — with concrete examples from the evidence.
- "common_value_hazards": attributes whose frequent values are weak evidence when they agree, with the frequent values you observed and how to treat them.
- "numeric_evidence": for each numeric attribute, the observed spread among true duplicates and how to use agreement/disagreement (agreement supports a match; a large gap should raise the bar rather than auto-reject unless the data says otherwise).
- "merge_when": 3-6 rules, each grounded in an observed pair.
- "keep_apart_when": 3-6 rules, each grounded in an observed pair.
- "examples": 6-10 worked pairs copied from the evidence, each with "a", "b", "verdict" ("same"|"different") and one-line "why".
Return ONLY the JSON object."""


def build_rubric_prompt(ev: Dict[str, Any], recs: Dict[Any, Dict[str, Any]], fields: Sequence[str]) -> Tuple[str, str]:
    fld = lambda i: {f: recs[i].get(f, "") for f in fields}
    u = [f"=== ATTRIBUTES === {list(fields)}", "", "=== ATTRIBUTE STATISTICS (computed from the corpus and the previous pass) ===",
         json.dumps(ev["stats"], ensure_ascii=False, indent=1), "",
         f"=== CONFIRMED SAME-ENTITY PAIRS from the previous pass (grouped by which attributes differ; available per group: {ev['strata']}) ===", ""]
    for a, b, kind in ev["pos"]:
        u += [f"[differs in: {kind}]", json.dumps(fld(a), ensure_ascii=False), json.dumps(fld(b), ensure_ascii=False), "--"]
    u += ["", "=== PAIRS KEPT APART by the previous pass although similar (different entities) ===", ""]
    for a, b in ev["neg"]:
        u += [json.dumps(fld(a), ensure_ascii=False), json.dumps(fld(b), ensure_ascii=False), "--"]
    u += ["", "=== RANDOM SAMPLE RECORDS ===", ""] + [json.dumps(fld(i), ensure_ascii=False) for i in ev["rand"]]
    u += ["", "Write the adjudication rubric JSON now."]
    return RUBRIC_SYSTEM, "\n".join(u)


def render_rubric(r: Dict[str, Any]) -> str:
    def lines(x):
        if isinstance(x, dict):
            return [f"- {k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}" for k, v in x.items()]
        if isinstance(x, list):
            return [f"- {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}" for v in x]
        return [str(x)]
    out = [f"DOMAIN: {r.get('domain_summary', '')}", "", "IDENTITY ATTRIBUTES (must co-refer; tolerated surface variance):"]
    out += lines(r.get("identity_attributes", {}))
    out += ["", "VARIANT ATTRIBUTES (may legitimately differ within one entity):"] + lines(r.get("variant_attributes", {}))
    out += ["", "DISTINGUISHING PATTERNS (indicate DIFFERENT entities):"] + lines(r.get("distinguishing_patterns", {}))
    out += ["", "COMMON-VALUE HAZARDS (agreement on these is weak evidence):"] + lines(r.get("common_value_hazards", {}))
    out += ["", "NUMERIC EVIDENCE:"] + lines(r.get("numeric_evidence", {}))
    out += ["", "MERGE WHEN:"] + lines(r.get("merge_when", [])) + ["", "KEEP APART WHEN:"] + lines(r.get("keep_apart_when", []))
    out += ["", "WORKED EXAMPLES:"]
    for e in r.get("examples", [])[:10]:
        out.append(f"- A: {json.dumps(e.get('a'), ensure_ascii=False)}\n  B: {json.dumps(e.get('b'), ensure_ascii=False)}\n  -> {e.get('verdict')}: {e.get('why')}")
    return "\n".join(out)


# ----------------------------------------------------------------------------- adjudication
ADJUDICATION_TEMPLATE = """You are an entity resolution expert.

You are given a small group of ENTITY REPRESENTATIVES that a blocker brought together as candidates. Each item [u1], [u2], ... is the canonical representative of an already-resolved cluster, followed by up to 3 of its underlying raw records. Decide which items denote the SAME real-world entity.

Procedure for every pair of items you consider merging:
1. Do the IDENTITY attributes co-refer? Surface variance in form is fine (spelling, accents, word order, abbreviation, credits), but a genuinely different value means different entities — agreement on other attributes cannot override this.
2. Is there a DISTINGUISHING pattern (a qualifier, edition, part, sub-version) present on one side only? If so, keep apart.
3. Weigh NUMERIC evidence asymmetrically: close agreement supports a merge; a large gap raises the bar (require additional agreeing evidence) rather than auto-rejecting.
4. Agreement on a COMMON value is weak evidence; agreement on a rare value is strong.
A wrong merge cannot be undone and contaminates many records at once. When genuinely unsure, keep items apart.

DATASET RUBRIC (derived from this dataset):
{RUBRIC}

For EACH cluster also produce a canonical representative record consolidating its members (fullest correct values, standardized form) and a confidence: "high" (identity attributes clearly co-refer and no distinguishing pattern), "medium" (co-reference plausible but one signal is weak or missing), "low" (speculative). Singleton clusters need no confidence.

Return JSON: {{"clusters":[{{"members":["u1", ...],"rep":{{{REP_FIELDS}}},"confidence":"high|medium|low"}}]}}
Every input item id must appear in exactly one cluster."""


def adjudication_system(rubric_text: str, fields: Sequence[str]) -> str:
    rep_fields = ",".join(f'"{f}":"..."' for f in fields)
    return ADJUDICATION_TEMPLATE.replace("{RUBRIC}", rubric_text).replace("{REP_FIELDS}", rep_fields)


def cluster_confidence(entry: Dict[str, Any]) -> str:
    c = str(entry.get("confidence", "") or "").lower().strip()
    return c if c in ("high", "medium", "low") else "unspecified"


# ----------------------------------------------------------------------------- unsupervised (round-0) evidence
def evidence_unsupervised(recs: Dict[Any, Dict[str, Any]], fields: Sequence[str], seed: int = 29,
                          n_rand: int = 200, n_near: int = 150, sample: int = 20000):
    """Before any LLM decision exists: random records + near-miss pairs mined with a
    key-independent signal (char-3-gram TF-IDF nearest neighbours over the whole record
    text, restricted to a sample). Pairs are UNLABELED."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    rng = random.Random(seed)
    ids = rng.sample(list(recs), min(sample, len(recs)))
    texts = [" ".join(str(recs[i].get(f) or "") for f in fields) for i in ids]
    X = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3), min_df=2).fit_transform(texts)
    nn = NearestNeighbors(n_neighbors=3, metric="cosine").fit(X)
    dist, idx = nn.kneighbors(X)
    cands = []
    for i in range(len(ids)):
        for r in (1, 2):
            j = int(idx[i, r]); s = 1.0 - float(dist[i, r])
            if j > i and s >= 0.45:
                cands.append((s, ids[i], ids[j]))
    cands.sort(key=lambda t: -t[0])
    near = cands[:n_near * 2 // 3] + rng.sample(cands[n_near * 2 // 3:], min(n_near // 3, max(0, len(cands) - n_near * 2 // 3)))
    stats = profile(recs, [], [], fields)
    return {"near": [(a, b) for _, a, b in near], "rand": rng.sample(list(recs), min(n_rand, len(recs))), "stats": stats}


def build_rubric_prompt_unsup(ev: Dict[str, Any], recs: Dict[Any, Dict[str, Any]], fields: Sequence[str]) -> Tuple[str, str]:
    """Rubric design with no labeled decisions yet: near-miss pairs are unlabeled."""
    system = RUBRIC_SYSTEM.replace(
        "pairs a previous resolution pass confirmed as the SAME entity (note what differs within each pair), and pairs it kept APART despite looking similar.",
        "and NEAR-MISS pairs mined by textual similarity — UNLABELED: some are the same entity, some are different; infer from the evidence which differences are benign surface variance and which are identity-bearing.")
    fld = lambda i: {f: recs[i].get(f, "") for f in fields}
    u = [f"=== ATTRIBUTES === {list(fields)}", "", "=== ATTRIBUTE STATISTICS ===", json.dumps(ev["stats"], ensure_ascii=False, indent=1), "",
         "=== NEAR-MISS PAIRS (textually similar; UNLABELED — some same entity, some not) ===", ""]
    for a, b in ev["near"]:
        u += [json.dumps(fld(a), ensure_ascii=False), json.dumps(fld(b), ensure_ascii=False), "--"]
    u += ["", "=== RANDOM SAMPLE RECORDS ===", ""] + [json.dumps(fld(i), ensure_ascii=False) for i in ev["rand"]]
    u += ["", "Write the adjudication rubric JSON now."]
    return system, "\n".join(u)


# ----------------------------------------------------------------------------- generic round-1 (resolve + represent)
RESOLVE_TEMPLATE = """You are an entity resolution expert.

You are given ALL records from one blocking block. Group records that denote the SAME real-world entity.

Procedure: for records to be grouped, their IDENTITY attributes must co-refer (surface variance in form is fine: spelling, accents, abbreviation, word order, punctuation, truncation, formatting), no DISTINGUISHING pattern may separate them, and disagreement on VARIANT attributes is not evidence against grouping. Agreement on a common value is weak evidence; on a rare value, strong. Be careful: a wrong merge cannot be undone later; an under-merge can be repaired in a later round. When genuinely unsure, keep records apart.

DATASET RUBRIC (derived from this dataset):
{RUBRIC}

For EACH cluster also produce a canonical representative record consolidating its members: the fullest correct value for every attribute, in standardized form (normalize casing, punctuation and spacing; drop obvious junk annotations).

Return JSON: {{"clusters":[{{"members":[<record ids>],"rep":{{{REP_FIELDS}}}}}]}}
Every input record id must appear in exactly one cluster."""


def resolve_system(rubric_text: str, fields: Sequence[str]) -> str:
    rep_fields = ",".join(f'"{f}":"..."' for f in fields)
    return RESOLVE_TEMPLATE.replace("{RUBRIC}", rubric_text).replace("{REP_FIELDS}", rep_fields)


def serialize_record(rid: Any, rec: Dict[str, Any], fields: Sequence[str]) -> str:
    parts = [f"[{rid}]"] + [f"{f}={rec[f]}" for f in fields if rec.get(f) not in (None, "")]
    return " | ".join(parts)


# ----------------------------------------------------------------------------- generic key design
KEYDESIGN_SYSTEM = """You are an expert in entity resolution designing BLOCKING KEY functions for a dataset of records with the attributes {FIELDS}.

A blocking key function maps one record to a LIST of short key strings. Two records are compared later if they share at least one key.

THE ONLY OBJECTIVE IS RECALL: every pair of records that denotes the same real-world entity should share at least one key. A separate matching step later examines every co-blocked pair and rejects non-duplicates — so you must NEVER try to keep similar-but-distinct records apart, and never add attributes to a key in order to separate records. The only constraint besides recall is block size: keep the largest block under ~500 records and total candidate pairs within a few hundred thousand.

Derive the surface variance your keys must tolerate from the evidence below (do not assume a domain). Rules for the keys:
- Keys must be GENERAL RULES (normalization, tokenization, character/phonetic signatures, splitting compound values, alias handling). Do NOT hard-code any literal value taken from the examples.
- Provide 3 to 4 schemes that use DIFFERENT signals (e.g. exact normalized attribute combinations; token/anchor based; character-level fuzzy signature; tolerant handling of missing or compound attributes), simplest first. A pair only needs to be caught by ONE scheme.

Return ONLY one fenced python code block defining:

SCHEMES = {{"scheme_name": function, ...}}

Each function takes a dict r with string attributes {FIELDS} (use r.get(name, "")) and returns a list of key strings (usually 1-3). Deterministic, fast, standard library only (re, unicodedata, hashlib allowed). Each scheme self-contained; one comment line per scheme. No code outside the single code block except comments."""


def keydesign_system(fields: Sequence[str]) -> str:
    return KEYDESIGN_SYSTEM.replace("{FIELDS}", json.dumps(list(fields)))
