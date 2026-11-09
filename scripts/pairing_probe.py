"""Pairing probe: is a cheap model's gap to a strong model difficulty-shaped (routable) or flat (a bias)?

Takes the round-1 blocks of a finished anchored run, picks the blocks that directly judge official test pairs,
runs ONE model/prompt on them (cached, resumable), and compares direct verdicts on those pairs band-by-band
(title similarity) against cached runs on the same blocks. Prompts:
  anchor : the production anchored prompt (matches + rep)
  tri    : per-candidate yes / no / unsure (+ rep) -- an explicit abstention channel
For 'tri', also evaluates the hybrid policy: yes -> select, unsure -> the strong model's cached verdict, no -> reject.

python scripts/pairing_probe.py --name wdc_s --records ... --gold ... --test-pairs ... --fields title,brand,price,description \
  --run data/reper/wdc_s__gpt-5.6-luna__anchor --cached "nano low=data/reper/wdc_s__gpt-5-nano__anchor,Luna low=data/reper/wdc_s__gpt-5.6-luna__anchor" \
  --strong "Luna low" --model gpt-5-nano --reasoning medium --prompt anchor --sample pos --neg-blocks 300
"""
import argparse, hashlib, json, os, random, re, sys, threading, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.getcwd())
import blueprint.reper_prompts as RP  # noqa: E402
from blueprint.llm_client import ChatClient  # noqa: E402
from blueprint.scoring import load_records, load_test_pairs  # noqa: E402

PRICE = {"gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5.6-luna": (0.20, 0.02, 1.20), "gpt-5.6-sol": (5.50, 0.55, 33.0), "gpt-oss-120b": (0.15, 0.15, 0.60), "gpt-oss-20b": (0.075, 0.075, 0.30)}
ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--gold", default="")
ap.add_argument("--test-pairs", required=True); ap.add_argument("--fields", required=True); ap.add_argument("--truncate", default="")
ap.add_argument("--run", required=True, help="run dir providing blocks_r1.json")
ap.add_argument("--cached", default="", help='"label=dir,label=dir" cached anchored runs on the same blocks')
ap.add_argument("--strong", default="", help="label (from --cached) whose verdicts resolve 'unsure' in the hybrid policy")
ap.add_argument("--model", default="gpt-5-nano"); ap.add_argument("--reasoning", default="low"); ap.add_argument("--prompt", choices=["anchor", "tri"], default="anchor")
ap.add_argument("--sample", choices=["pos", "strong-miss"], default="pos", help="pos: every block judging a test positive; strong-miss: blocks where --strong missed a judged positive or wrongly selected a judged negative")
ap.add_argument("--neg-blocks", type=int, default=300, help="random extra blocks that judge only test negatives"); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--workers", type=int, default=16); ap.add_argument("--tag", default=""); ap.add_argument("--no-calls", action="store_true")
ap.add_argument("--evidence", action="store_true", help="intuition 2: append a rarity-annotated evidence line per candidate (shared values with corpus counts; conflicts)")
ap.add_argument("--rare", type=int, default=50, help="a shared token is spelled out when it occurs in <= this many records")
ap.add_argument("--cards", default="", help="intuition 1: python file with TYPES/type_of/CARDS; the target's type card is added to the rules")
ap.add_argument("--max-pos-blocks", type=int, default=0, help="subsample the positive-judging blocks (0 = all)")
ap.add_argument("--shared-only", action="store_true", help="evidence line lists shared values and their rarity only (no conflict listing)")
a = ap.parse_args()
FIELDS = [f.strip() for f in a.fields.split(",") if f.strip()]
T0 = time.time(); log = lambda m: print(f"[{time.time()-T0:.0f}s] {m}", flush=True)
recs = load_records(a.records)
for spec in [x for x in a.truncate.split(",") if x.strip()]:
    fld_, n_ = spec.split("="); n_ = int(n_)
    for r in recs.values():
        if r.get(fld_): r[fld_] = r[fld_][:n_]
test_pairs = load_test_pairs(a.test_pairs)
blocks = json.load(open(f"{a.run}/blocks_r1.json"))
bkey = lambda c: hashlib.sha1("|".join(map(str, c)).encode()).hexdigest()[:16] + f"#{len(c)}"
TOK = re.compile(r"[a-z0-9]+"); toks = lambda s: set(TOK.findall((s or "").lower()))
jacc = lambda x, y: len(x & y) / len(x | y) if x | y else 0.0
BINS = [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]
binof = lambda j: next(b for b in BINS if b[0] <= j < b[1])

# ---- which blocks judge which test pairs ----
lab = {}
for x, y, l in test_pairs:
    lab[(x, y)] = l; lab[(y, x)] = l
judges = defaultdict(list)   # block index -> [(owner, cand, label)]
for i, b in enumerate(blocks):
    for c in b[1:]:
        if (b[0], c) in lab: judges[i].append((b[0], c, lab[(b[0], c)]))


def extract(text):
    try: return json.loads(text)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", text or "", re.S)
        try: return json.loads(m.group(0)) if m else None
        except Exception: return None  # noqa: BLE001


def verdicts_of(row, block, prompt):
    """-> {cand_id: 'yes'|'no'|'unsure'} for every candidate ('no' when unmentioned); None if no/unparsable answer."""
    if row is None: return None
    obj = extract(row["text"]); cands = block[1:]
    if not isinstance(obj, dict): return None
    out = {c: "no" for c in cands}
    if prompt == "anchor":
        if not isinstance(obj.get("matches"), list): return None
        for m in obj["matches"]:
            try: m = int(m)
            except (TypeError, ValueError): continue
            if 1 <= m <= len(cands): out[cands[m - 1]] = "yes"
    else:
        if not isinstance(obj.get("verdicts"), list): return None
        for it in obj["verdicts"]:
            try: n = int(it.get("n")); v = str(it.get("v")).lower()
            except Exception: continue  # noqa: BLE001
            if 1 <= n <= len(cands) and v in ("yes", "no", "unsure"): out[cands[n - 1]] = v
    return out


def load_cached(d):
    rows = {}
    for line in open(f"{d}/round1.jsonl"):
        if line.strip():
            r = json.loads(line); rows[r["key"]] = r
    return rows


cached = {}
for spec in [x for x in a.cached.split(",") if x.strip()]:
    label, d = spec.split("="); cached[label.strip()] = load_cached(d.strip())
strong = cached.get(a.strong) if a.strong else None

# ---- sample ----
rng = random.Random(a.seed)
pos_blocks = [i for i, js in judges.items() if any(l for _, _, l in js)]
neg_only = [i for i, js in judges.items() if js and not any(l for _, _, l in js)]
if a.max_pos_blocks and len(pos_blocks) > a.max_pos_blocks: pos_blocks = sorted(rng.sample(pos_blocks, a.max_pos_blocks))
if a.sample == "pos":
    S = set(pos_blocks)
else:
    assert strong is not None, "--sample strong-miss needs --strong"
    S = set()
    for i in pos_blocks + neg_only:
        v = verdicts_of(strong.get(bkey(blocks[i])), blocks[i], "anchor") or {}
        if any((l and v.get(c) != "yes") or ((not l) and v.get(c) == "yes") for _, c, l in judges[i]): S.add(i)
S |= set(rng.sample(neg_only, min(a.neg_blocks, len(neg_only))))
S = sorted(S)
n_pairs = sum(len(judges[i]) for i in S); n_pos = sum(1 for i in S for _, _, l in judges[i] if l)
log(f"{a.name}: sample {len(S):,} blocks ({len(pos_blocks):,} judge a test positive; {a.neg_blocks} extra negative-only), {n_pairs:,} judged test-pair sides, {n_pos:,} positive sides; mean block size {sum(len(blocks[i])-1 for i in S)/max(1,len(S)):.1f}")

# ---- intuition 2: corpus rarity statistics + evidence line ----
def norm(v): return " ".join(TOK.findall((v or "").lower()))
def numeric(v):
    try: return float(str(v).replace(",", "."))
    except (TypeError, ValueError): return None
NUM = re.compile(r"\d")
if a.evidence:
    df_val, df_tok = Counter(), Counter()
    for r in recs.values():
        seen = set()
        for f in FIELDS:
            v = norm(r.get(f, ""))
            if v and f != "description": df_val[(f, v)] += 1
            seen |= set(v.split())
        for t in seen: df_tok[t] += 1
def evidence(t, c):
    rt, rc_ = recs[t], recs[c]; shared, diff = [], []
    for f in FIELDS:
        if f == "description": continue
        vt, vc = norm(rt.get(f, "")), norm(rc_.get(f, ""))
        if vt and vt == vc: shared.append(f"{f} identical (in {df_val[(f, vt)]:,} records)")
        elif vt and vc:
            nt, nc = numeric(rt.get(f)), numeric(rc_.get(f))
            if nt is not None and nc is not None:
                if abs(nt - nc) <= 0.01 * max(abs(nt), abs(nc), 1e-9): shared.append(f"{f} nearly identical ({rt.get(f)} vs {rc_.get(f)})")
                else: diff.append(f"{f} {rt.get(f)} vs {rc_.get(f)}")
    tt = set().union(*[set(norm(rt.get(f, "")).split()) for f in FIELDS]); tc = set().union(*[set(norm(rc_.get(f, "")).split()) for f in FIELDS])
    rare = sorted((df_tok[x], x) for x in tt & tc if df_tok[x] <= a.rare and len(x) >= 3 and not (x.isdigit() and len(x) < 4))
    if rare: shared.append("rare shared values: " + ", ".join(f'"{x}" (in {d:,} records)' for d, x in rare[:4]))
    numt = {x for x in norm(rt.get(FIELDS[0], "")).split() if NUM.search(x)}; numc = {x for x in norm(rc_.get(FIELDS[0], "")).split() if NUM.search(x)}
    if numt != numc and (numt or numc): diff.append("numbers in " + FIELDS[0] + ": " + ("/".join(sorted(numt - numc)[:3]) or "-") + " vs " + ("/".join(sorted(numc - numt)[:3]) or "-"))
    if not shared: shared.append("no identical field, no rare shared value")
    if a.shared_only: diff = []
    return "    evidence: " + "; ".join(shared) + ((" | differs: " + "; ".join(diff)) if diff else "")
EVIDENCE_NOTE = "\n\nEach candidate is followed by an 'evidence' line computed over the whole dataset: the values it shares with the target and how many records contain each (a value shared by few records is strong evidence of identity, a common one is weak), and the fields or numbers that differ (a differing qualifier or number usually marks a variant)."
EVIDENCE_NOTE_SHARED = "\n\nEach candidate is followed by an 'evidence' line computed over the whole dataset: the values it shares with the target and how many records contain each. A value shared by only a few records is strong evidence that the two denote the same entity; a value shared by many records is weak evidence. The line does not list differences; judge those from the records themselves."
# ---- intuition 1: type cards ----
CARDS, type_of = None, None
if a.cards:
    ns_ = {}; exec(open(a.cards).read(), ns_)  # noqa: S102
    CARDS, type_of = ns_["CARDS"], ns_["type_of"]
def card_note(owner):
    if not CARDS: return ""
    t = type_of(recs[owner]); card = CARDS.get(t) or CARDS.get("other", "")
    return f"\n\nThe target is of kind: {t}. Identity theory for this kind (apply it; where it conflicts with the generic rules above, it takes precedence):\n{card}"

# ---- prompts ----
TRI_SYSTEM = RP.ANCHOR_SYSTEM.split("If you select at least one candidate")[0].replace(
    "Select every candidate that denotes the SAME real-world entity as the target.",
    'Give a verdict for EVERY candidate: "yes" (same real-world entity as the target), "no" (a different entity), or "unsure" (the given fields do not let you decide; e.g. a rare code or most attributes agree but a qualifier is missing on one side, or the two descriptions could be the same product or a variant).').replace(
    "When genuinely unsure, do not select.", 'When genuinely unsure, answer "unsure" rather than "no".') + \
    'Also write one canonical representative record consolidating the target and the "yes" candidates (the fullest correct value of every attribute, standardized); if there are none, copy the target.\n\n' + \
    'Return ONLY JSON of the form {"verdicts":[{"n":<candidate number>,"v":"yes"|"no"|"unsure"}, ...],"rep":{REP_FIELDS}} with exactly one verdict per candidate number.'
tri_system = lambda fields: TRI_SYSTEM.replace("{REP_FIELDS}", ",".join(f'"{f}":"..."' for f in fields))
REP_SCHEMA = {"type": "object", "additionalProperties": False, "required": FIELDS, "properties": {f: {"type": "string"} for f in FIELDS}}
ANCHOR_SCHEMA = {"type": "json_schema", "name": "anchor", "strict": True, "schema": {"type": "object", "additionalProperties": False, "required": ["matches", "rep"], "properties": {"matches": {"type": "array", "items": {"type": "integer"}}, "rep": REP_SCHEMA}}}
TRI_SCHEMA = {"type": "json_schema", "name": "tri", "strict": True, "schema": {"type": "object", "additionalProperties": False, "required": ["verdicts", "rep"], "properties": {
    "verdicts": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["n", "v"], "properties": {"n": {"type": "integer"}, "v": {"type": "string", "enum": ["yes", "no", "unsure"]}}}}, "rep": REP_SCHEMA}}}
base_system = RP.anchor_system(FIELDS) if a.prompt == "anchor" else tri_system(FIELDS)
schema = ANCHOR_SCHEMA if a.prompt == "anchor" else TRI_SCHEMA
def system_text(b): return base_system + ((EVIDENCE_NOTE_SHARED if a.shared_only else EVIDENCE_NOTE) if a.evidence else "") + card_note(b[0])
def user_text(b):
    line = lambda r: " | ".join(f"{f}={recs[r][f]}" for f in FIELDS if recs[r].get(f) not in (None, ""))
    parts = ["Target: " + line(b[0]), "", "Candidates:"]
    for i, c in enumerate(b[1:], 1):
        parts.append(f"[{i}] " + line(c))
        if a.evidence: parts.append(evidence(b[0], c))
    return "\n".join(parts)
VARIANT = (("_evs" if a.shared_only else "_ev") if a.evidence else "") + ("_cards" if a.cards else "")

# ---- run ----
os.makedirs("data/reper/probe", exist_ok=True)
label_new = f"{a.model} {a.reasoning} {a.prompt}{VARIANT}{(' ' + a.tag) if a.tag else ''}"
cache = f"data/reper/probe/{a.name}__{a.model}_{a.reasoning}_{a.prompt}{VARIANT}{('_' + a.tag) if a.tag else ''}.jsonl"; done = {}
if os.path.exists(cache):
    for line in open(cache):
        r = json.loads(line); done[r["key"]] = r
todo = [blocks[i] for i in S if bkey(blocks[i]) not in done]
est = len(todo) * (2000 * PRICE[a.model][0] + 600 * PRICE[a.model][2]) / 1e6
log(f"  {len(done):,} cached, {len(todo):,} calls to make on {a.model} ({a.reasoning}, {a.prompt}); rough list cost ${est:.2f}")
if a.no_calls: todo = []
if todo:
    llm = ChatClient(deployment=a.model); lock = threading.Lock(); logf = open(cache, "a")
    def one(b):
        res = llm.chat(system_text(b), user_text(b), response_format=schema, max_completion_tokens=min(20_000, 3000 + 120 * len(b)), reasoning_effort=a.reasoning)
        row = {"key": bkey(b), "text": res["text"], "usage": res["usage"], "latency_s": res["latency_s"]}
        with lock: logf.write(json.dumps(row, ensure_ascii=False) + "\n"); logf.flush()
        return row
    fails = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, b): b for b in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try: r = f.result(); done[r["key"]] = r
            except Exception as e:  # noqa: BLE001
                fails += 1
                if fails <= 5: log(f"  FAIL {bkey(futs[f])[:20]}: {str(e)[:140]}")
            if i % 200 == 0: log(f"  {i}/{len(todo)}")
    if fails: log(f"  {fails} calls failed")
usage = [0, 0, 0]
for i in S:
    r = done.get(bkey(blocks[i]))
    if r: u = r["usage"]; usage[0] += u.get("prompt_tokens") or 0; usage[1] += u.get("completion_tokens") or 0; usage[2] += 1
pi, pc, po = PRICE[a.model]; cost = usage[0] / 1e6 * pi + usage[1] / 1e6 * po
log(f"  {label_new}: {usage[2]:,} answered blocks, {usage[0]:,} in / {usage[1]:,} out tokens, list ${cost:.2f}")

# ---- evaluate: direct verdicts on judged test-pair sides within S ----
models = {lbl: (rows, "anchor") for lbl, rows in cached.items()}; models[label_new] = (done, a.prompt)
V = {lbl: {} for lbl in models}   # (owner, cand) -> verdict
missing = Counter()
for i in S:
    b = blocks[i]
    for lbl, (rows, pr) in models.items():
        v = verdicts_of(rows.get(bkey(b)), b, pr)
        if v is None: missing[lbl] += 1; continue
        for o, c, l in judges[i]: V[lbl][(o, c)] = v[c]
if missing: log("  blocks without a usable answer: " + ", ".join(f"{k} {v}" for k, v in missing.items()))
# pair-level (either side): a pair counts as selected if any judging side in S says yes
pairs = {}
for i in S:
    for o, c, l in judges[i]:
        k = (o, c) if o < c else (c, o); pairs.setdefault(k, [l, []])[1].append((o, c))
def pair_verdict(lbl, sides, hybrid=False):
    vs = [V[lbl].get(s) for s in sides]
    if hybrid and strong is not None:
        vs = [(V[a.strong].get(s) if v == "unsure" else v) for v, s in zip(vs, sides)]
    if "yes" in vs: return "yes"
    if "unsure" in vs: return "unsure"
    return "no" if any(v == "no" for v in vs) else None
cols = list(models) + ([label_new + " +unsure->" + a.strong] if a.prompt == "tri" and strong is not None else [])
tab = {b: defaultdict(Counter) for b in BINS}
for (x, y), (l, sides) in pairs.items():
    b = binof(jacc(toks(recs[x].get(FIELDS[0], "")), toks(recs[y].get(FIELDS[0], ""))))
    for col in cols:
        lbl, hyb = (col.split(" +unsure->")[0], True) if "+unsure->" in col else (col, False)
        v = pair_verdict(lbl, sides, hyb)
        if v is None: continue
        t = tab[b][col]; t["pos" if l else "neg"] += 1; t[("pos" if l else "neg") + "_" + v] += 1
print(f"\n  direct verdicts on official test pairs judged inside the sample ({len(pairs):,} pairs: {sum(1 for l, _ in pairs.values() if l)} positive, {sum(1 for l, _ in pairs.values() if not l)} negative)")
print("  positives: share answered yes (= direct recall) by title-similarity bin; [unsure share in brackets for tri]")
print("    " + f"{'bin':8s}" + "".join(f"{c[:26]:>28s}" for c in cols))
for b in BINS:
    line = f"    {b[0]:.1f}-{b[1]:.1f} "
    for c in cols:
        t = tab[b][c]; n = t["pos"]
        line += f"{(t['pos_yes']/n if n else 0):6.2f}" + (f" [{t['pos_unsure']/n if n else 0:.2f}]" if "tri" in c and "+unsure" not in c else "       ") + f"  n={n:<4d}   "
    print(line)
print("  negatives: share answered yes (= false-positive rate) by bin; [unsure share for tri]")
for b in BINS:
    line = f"    {b[0]:.1f}-{b[1]:.1f} "
    for c in cols:
        t = tab[b][c]; n = t["neg"]
        line += f"{(t['neg_yes']/n if n else 0):6.3f}" + (f" [{t['neg_unsure']/n if n else 0:.2f}]" if "tri" in c and "+unsure" not in c else "       ") + f"  n={n:<4d}   "
    print(line)
tot = {c: Counter() for c in cols}
for b in BINS:
    for c in cols: tot[c].update(tab[b][c])
print("  overall:")
for c in cols:
    t = tot[c]; P = t["pos_yes"] / max(1, t["pos_yes"] + t["neg_yes"]); R = t["pos_yes"] / max(1, t["pos"])
    extra = f" | unsure: {t['pos_unsure']} pos, {t['neg_unsure']} neg" if "tri" in c and "+unsure" not in c else ""
    print(f"    {c:40s} direct recall {R:.3f}  precision among yes {P:.3f}  (yes on {t['pos_yes']} pos / {t['neg_yes']} neg){extra}")
if a.prompt == "tri":
    nb = sum(1 for i in S if any(v == "unsure" for v in (verdicts_of(done.get(bkey(blocks[i])), blocks[i], "tri") or {}).values()))
    print(f"  blocks with at least one 'unsure' (would be escalated): {nb:,} of {len(S):,} ({nb/max(1,len(S)):.0%})")
# block-level concentration: among blocks with a positive, where does the new model fail vs the strong model?
if strong is not None and label_new != a.strong:
    conf = Counter()
    for i in S:
        js = [(o, c) for o, c, l in judges[i] if l]
        if not js: continue
        new_ok = all(V[label_new].get(s) == "yes" for s in js) if all(s in V[label_new] for s in js) else None
        st_ok = all(V[a.strong].get(s) == "yes" for s in js) if all(s in V[a.strong] for s in js) else None
        if new_ok is None or st_ok is None: continue
        conf[("new right" if new_ok else "new wrong", "strong right" if st_ok else "strong wrong")] += 1
    print("  blocks holding a test positive, by outcome: " + ", ".join(f"{k[0]} / {k[1]}: {v}" for k, v in sorted(conf.items())))
json.dump({"sample_blocks": len(S), "cols": cols, "table": {f"{b[0]}-{b[1]}": {c: dict(tab[b][c]) for c in cols} for b in BINS}, "cost_list": cost, "usage": usage},
          open(cache.replace(".jsonl", f"__{a.sample}_summary.json"), "w"), indent=1)
