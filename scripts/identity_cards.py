"""Intuition 1: type first, then an identity theory per type.

One design-model call: reads a random sample of records, writes (a) a short taxonomy of the KINDS of things in the
dataset, (b) a keyword/regex classifier type_of(record) -> kind, (c) an identity CARD per kind: what identifies an
entity of this kind, which differences are harmless, which attributes make a VARIANT (a different entity), and what
"same" means here. Saved as python (TYPES, type_of, CARDS) for the matching prompts to load.

python scripts/identity_cards.py --name wdc_s --records ... --fields title,brand,price,description --truncate description=120 --sample 400
"""
import argparse, json, os, random, re, sys, time

sys.path.insert(0, os.getcwd())
from blueprint.llm_client import ChatClient  # noqa: E402
from blueprint.scoring import load_records  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--fields", required=True)
ap.add_argument("--truncate", default=""); ap.add_argument("--sample", type=int, default=400); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--domain", default="", help="one line saying what a record is, e.g. 'product offers scraped from many web shops'")
ap.add_argument("--model", default="gpt-5.6-sol"); ap.add_argument("--reasoning", default="medium"); ap.add_argument("--force", action="store_true")
ap.add_argument("--privatize", default="", help="local model that rewrites the sample before it reaches the design model (privacy filter); output file gets the suffix _private")
ap.add_argument("--cands", default="", help="BM25 candidate TSV (id_a,id_b,rank) from scripts/bm25_pairs.py; enables near-duplicate pairs in the design call")
ap.add_argument("--near-pairs", type=int, default=100, help="number of closest-neighbour pairs (rank 1) to show, unlabelled; 0 = none")
a = ap.parse_args()
FIELDS = [f.strip() for f in a.fields.split(",") if f.strip()]
recs = load_records(a.records)
for spec in [x for x in a.truncate.split(",") if x.strip()]:
    fld_, n_ = spec.split("="); n_ = int(n_)
    for r in recs.values():
        if r.get(fld_): r[fld_] = r[fld_][:n_]
os.makedirs("data/reper/cards", exist_ok=True)
SUF = ("_private" if a.privatize else "") + ("_np" if (a.cands and a.near_pairs) else "")
out_py = f"data/reper/cards/{a.name}__cards{SUF}.py"; out_raw = f"data/reper/cards/{a.name}__cards{SUF}_raw.json"
if os.path.exists(out_py) and not a.force:
    print(f"exists: {out_py} (use --force to redo)"); sys.exit(0)

SYSTEM = f"""You are a domain expert designing an IDENTITY THEORY for entity resolution over one dataset.
Records have the fields: {', '.join(FIELDS)}. Two records are the SAME entity when they denote the same real-world thing at the level this dataset uses.

You may also be shown the collection's MOST SIMILAR RECORD PAIRS: unlabelled, but most are two descriptions of the same thing. Use them to learn which fields actually vary between probable duplicates in THIS data (those differences are HARMLESS) and which differences separate distinct things; do not assume from general knowledge that a field must agree if the pairs show it varying.

Do three things, all specific to THIS data (not generic advice):
1. TAXONOMY: list the KINDS of things in the dataset (short names). Use a single kind if the data is homogeneous; otherwise the kinds that matter because they are identified differently. Add 'other' for the rest.
2. CLASSIFIER: write a fast, deterministic python function type_of(r: dict) -> str using keywords/regexes over the fields, returning one of the kinds or 'other'. Standard library only.
3. CARDS: for every kind (including 'other'), write an identity card in plain text, at most 120 words, with four labelled parts:
   (a) IDENTIFIES: what identifies an entity of this kind (fields, codes, patterns; which are decisive alone, which need corroboration);
   (b) HARMLESS: differences between sources that do NOT change identity (language, word order, retailer wording, missing values, price, formatting...);
   (c) VARIANT: attributes whose difference makes a DIFFERENT entity (size, capacity, colour, pack count, edition, generation, model suffix, release, version...);
   (d) SAME MEANS: one sentence stating what 'same' means for this kind here.

Return ONE ```python code block defining: TYPES (list of str), type_of(r), CARDS (dict: every type and 'other' -> card text). No other code."""
rng = random.Random(a.seed); ids = rng.sample(list(recs), min(a.sample, len(recs)))
sample = [recs[i] for i in ids]
if a.privatize:
    from blueprint.privatize import Privatizer
    P = Privatizer(a.privatize, recs, FIELDS, cache=f"data/reper/cards/{a.name}__sample_private.jsonl")
    fake = P.records(sample); sample = [f for f in fake if f]
    rep = P.report(); json.dump({"model": a.privatize, **rep}, open(f"data/reper/cards/{a.name}__sample_private_report.json", "w"), indent=1)
    print(f"privacy filter ({a.privatize}): {rep}")
lines = [" | ".join(f"{f}={r[f]}" for f in FIELDS if r.get(f)) for r in sample]
pair_lines = []
if a.cands and a.near_pairs:
    import csv as _csv
    top = [(r["id_a"], r["id_b"]) for r in _csv.DictReader(open(a.cands), delimiter="\t") if r["rank"] == "1" and r["id_a"] in recs and r["id_b"] in recs]
    rng2 = random.Random(a.seed + 1); top = rng2.sample(top, min(a.near_pairs, len(top)))
    pairs = [({f: recs[x].get(f, "") for f in FIELDS}, {f: recs[y].get(f, "") for f in FIELDS}) for x, y in top]
    if a.privatize:
        fp = P.pairs(pairs); pairs = [q for q in fp if q]
        rep2 = P.report(); json.dump({"model": a.privatize, **rep2}, open(f"data/reper/cards/{a.name}__sample_private_report.json", "w"), indent=1)
        print(f"privacy filter incl. near pairs ({a.privatize}): {rep2}")
    json.dump(pairs, open(f"data/reper/cards/{a.name}__near_pairs{SUF}.json", "w"), ensure_ascii=False)
    line_of = lambda r: " | ".join(f"{f}={r[f]}" for f in FIELDS if r.get(f))
    for x, y in pairs: pair_lines += [line_of(x), line_of(y), "--"]
user = f"Dataset: {a.name}. {a.domain + '. ' if a.domain else ''}{len(recs):,} records in total; a random sample of {len(lines)} follows.\n\n" + "\n".join(lines)
if pair_lines: user += f"\n\n=== MOST SIMILAR RECORD PAIRS ({len(pair_lines)//3}; unlabelled; most are duplicates; note what differs within a pair) ===\n" + "\n".join(pair_lines)
t0 = time.time()
res = ChatClient(deployment=a.model).chat(SYSTEM, user, max_completion_tokens=30_000, reasoning_effort=a.reasoning)
json.dump(res, open(out_raw, "w"), ensure_ascii=False)
m = re.search(r"```python\n(.*?)```", res["text"], re.S)
if not m:
    print("no python block in the answer; raw saved to", out_raw); sys.exit(1)
code = m.group(1); ns = {}; exec(code, ns)  # noqa: S102
assert "TYPES" in ns and "type_of" in ns and "CARDS" in ns, "answer lacks TYPES/type_of/CARDS"
open(out_py, "w").write(code)
u = res["usage"]; cost = (u.get("prompt_tokens") or 0) / 1e6 * 5.5 + (u.get("completion_tokens") or 0) / 1e6 * 33.0
from collections import Counter
dist = Counter(ns["type_of"](r) for r in recs.values())
print(f"{a.name}: {len(ns['TYPES'])} kinds in {time.time()-t0:.0f}s, {u.get('prompt_tokens')} in / {u.get('completion_tokens')} out tokens, list ${cost:.2f} -> {out_py}")
print("type distribution over all records:", dict(dist.most_common(12)))
for t, card in ns["CARDS"].items():
    print(f"\n[{t}] {card}")
