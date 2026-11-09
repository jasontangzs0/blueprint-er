"""REP-ER (v3, 2026-09-17). Design model writes the identity theory (kinds + cards, scripts/identity_cards.py) and,
each round, the next blocking keys; the matching model judges blocks. Round 0 = BM25 top-k self-join (no LLM).
Round 1 = anchored: one call per record (target + ranked candidates + the target's kind card) -> matches + a
representative; either-side merge. Rounds >= 2: keys from this round's decisions -> disjoint key blocks over the
representatives -> clustering call (with the block's kind cards). Stop by the budget guard.

Canonical usage (small tier):
  PYTHONPATH=. .venv/bin/python scripts/identity_cards.py --name <name> --records <records.csv> --fields <f1,...> \
      [--truncate description=120] --sample 400 --domain "<one line>"
  PYTHONPATH=. PYTHONHASHSEED=0 .venv/bin/python scripts/reper.py --name <name> --model gpt-5-nano --reasoning low \
      --json-schema --anchor --tag anchor_cards --cards data/reper/cards/<name>__cards.py \
      --records <records.csv> --gold <gold_clusters.txt> [--test-pairs <test_pairs.csv>] \
      --fields <f1,...> [--truncate description=200] --bm25-fields <...> --bm25-tokens word|char3 --k 10|20 --cap 60 \
      --max-rounds 3 --workers 32
Other flags: [--reasoning minimal|low|medium] [--ramp N] [--no-calls] [--design-model gpt-5.6-sol] [--no-budget-guard]
Outputs: data/reper/<name>__<model>[__<tag>]/
"""
import argparse, csv, hashlib, json, os, re, sys, threading, time
if os.environ.get("PYTHONHASHSEED") != "0":   # deterministic set/dict order -> exact replay
    os.execve(sys.executable, [sys.executable] + sys.argv, {**os.environ, "PYTHONHASHSEED": "0"})
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from blueprint.llm_client import ChatClient
from blueprint.jsonutil import _extract_json
from blueprint import rubric as RB
from blueprint.rubric import norm
from blueprint import reper_prompts as RP

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--records", required=True); ap.add_argument("--gold", required=True)
ap.add_argument("--id-col", default="id"); ap.add_argument("--fields", required=True)
ap.add_argument("--bm25-fields", default=""); ap.add_argument("--bm25-tokens", choices=["word", "char3"], default="word")
ap.add_argument("--k", type=int, default=10); ap.add_argument("--cap", type=int, default=200)
ap.add_argument("--model", default="gpt-5-nano"); ap.add_argument("--design-model", default="gpt-5.6-sol")
ap.add_argument("--reasoning", default="", help="reasoning effort for the cheap model (minimal|low|medium|high); empty = provider default")
ap.add_argument("--max-rounds", type=int, default=3); ap.add_argument("--workers", type=int, default=48)
ap.add_argument("--ramp", type=int, default=0, help="round 1 only, first N blocks, then exit")
ap.add_argument("--no-calls", action="store_true"); ap.add_argument("--test-pairs", default="")
ap.add_argument("--llmcer-repo", default="data/external/LLMCER")
ap.add_argument("--tag", default="", help="suffix for the output dir (config variants)")
ap.add_argument("--json-schema", action="store_true", help="strict structured output instead of json_object")
ap.add_argument("--blocks-only", action="store_true", help="build and score round-0 blocks, then exit (no LLM)")
ap.add_argument("--gate", choices=["mutual", "none"], default="mutual", help="create a round-0 block only for records with a mutual neighbour")
ap.add_argument("--gate-rank", type=int, default=0, help="mutual gate restricted to the top-M ranks of both lists (0 = full top-k)")
ap.add_argument("--vote", choices=["majority", "any"], default="majority", help="accept a merge across overlapping blocks by majority of verdicts, or if asserted anywhere")
ap.add_argument("--truncate", default="", help="field=chars[,field=chars] truncation applied to what the model sees, e.g. description=200")
ap.add_argument("--anchor", action="store_true", help="round 1 judges each block from its OWNER record's point of view (target + numbered neighbours, SELECT-style); a pair is merged if either owner selects the other; no vote. Rounds >= 2 unchanged.")
ap.add_argument("--cards", default="", help="identity cards file (TYPES/type_of/CARDS from scripts/identity_cards.py): the target's kind card is appended to the round-1 prompt, the block's dominant kinds to later-round prompts")
ap.add_argument("--privatize", default="", help="local model that rewrites every record in the key-design evidence before it reaches the design model (privacy filter)")
ap.add_argument("--key-anchor", action="store_true", help="later rounds restart from a clean slate: every raw record is judged again with the ANCHORED prompt, its candidates being the records that share a designed key value (ranked by shared keys, then BM25), instead of clustering calls over representatives")
ap.add_argument("--key-k", type=int, default=0, help="--key-anchor: candidates per record (0 = same as --k)")
ap.add_argument("--key-new-only", action="store_true", help="--key-anchor: drop candidates already co-blocked with the record in round 1")
ap.add_argument("--key-carry", choices=["union", "standalone"], default="union", help="--key-anchor: which partition the next round designs keys from")
ap.add_argument("--key-units", choices=["records", "reps"], default="records", help="--key-anchor: judge raw records (clean slate) or the current clusters described by their representatives (uniform loop)")
ap.add_argument("--key-max-share", type=int, default=50, help="entity/key rounds: a key value held by more than this many units is not used to propose candidates (selectivity cut; replay 2026-10-24: F1 within 0.2 of no cut at 50, lists 2-4x shorter)")
ap.add_argument("--key-accept-share", type=int, default=0, help="entity round: build the lists with --key-max-share as recorded, but ACCEPT a selected candidate only if the pair shares a key value held by <= this many units (0 = off). Exact replay of cached runs under the selectivity rule.")
ap.add_argument("--entity-rounds", type=int, default=1, help="--entity-round: how many entity rounds to run (replay 2026-10-24: a second entity round changed F1 by -1.0 to +0.7 in nine cells and never paid for itself)")
ap.add_argument("--entity-round", action="store_true", help="the method's later rounds (2026-10-24 naming): the ENTITY ROUND = the record round's anchored decision applied to the resolved entities' representatives, candidates from the designed keys (alias for --key-anchor --key-units reps)")
ap.add_argument("--no-budget-guard", action="store_true", help="disable the stopping rule: a round whose new blocks are not fewer than the previous round's is not run")
a = ap.parse_args()
if a.entity_round: a.key_anchor, a.key_units, a.max_rounds, a.key_k = True, "reps", 1 + a.entity_rounds, (a.key_k or a.cap - 1)   # lists cut at the record round's cap
FIELDS = [f.strip() for f in a.fields.split(",") if f.strip()]
BM25F = [f.strip() for f in a.bm25_fields.split(",") if f.strip()] or FIELDS
OUT = f"data/reper/{a.name}__{a.model}" + (f"__{a.tag}" if a.tag else ""); os.makedirs(OUT, exist_ok=True)
T0 = time.time()
log = lambda m: print(f"[{time.time()-T0:.0f}s] {m}", flush=True)
PRICE = {"gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5.6-luna": (0.20, 0.02, 1.20), "gpt-5.6-sol": (5.50, 0.55, 33.0), "gpt-5.6-terra": (2.0, 0.2, 12.0), "gpt-oss-120b": (0.15, 0.15, 0.60), "gpt-oss-20b": (0.075, 0.075, 0.30)}
spend = defaultdict(lambda: [0, 0, 0, 0])   # prompt, cached, completion, calls
def bill(dep, u):
    s = spend[dep]; s[0] += u.get("prompt_tokens") or 0; s[1] += u.get("cached_tokens") or 0; s[2] += u.get("completion_tokens") or 0; s[3] += 1
def costs():
    lst = bil = 0.0
    for d, (p, c, o, _) in spend.items():
        pi, pc, po = PRICE.get(d, (0.2, 0.02, 1.2)); lst += p / 1e6 * pi + o / 1e6 * po; bil += (p - c) / 1e6 * pi + c / 1e6 * pc + o / 1e6 * po
    return lst, bil

# ---------------- load ----------------
recs = {}
with open(a.records, encoding="utf-8", errors="replace") as f:
    for row in csv.DictReader(f):
        recs[row[a.id_col]] = {k: (v or "").strip() for k, v in row.items() if k != a.id_col}
for spec in [x for x in a.truncate.split(",") if x.strip()]:
    fld_, n_ = spec.split("="); n_ = int(n_)
    for r in recs.values():
        if r.get(fld_): r[fld_] = r[fld_][:n_]
gold_clusters = [line.split() for line in open(a.gold) if line.strip()]
cid = {x: k for k, cl in enumerate(gold_clusters) for x in cl}
for rid in recs: cid.setdefault(rid, f"s{rid}")
N = len(recs); G = sum(n * (n - 1) // 2 for n in Counter(cid.values()).values())
gold_full = [list(c) for c in gold_clusters] + [[r] for r in recs if r not in {x for c in gold_clusters for x in c}]
TITLE_KEY = {i: norm(r.get(FIELDS[0], "")) for i, r in recs.items()} if FIELDS else {}
test_pairs = []
if a.test_pairs:
    test_pairs = [(r["id_a"], r["id_b"], r["label"] == "1") for r in csv.DictReader(open(a.test_pairs))]
log(f"{a.name}: {N:,} records, fields {FIELDS}, bm25 on {BM25F} ({a.bm25_tokens}, k={a.k}), {len(gold_full):,} entities, {G:,} true pairs" + (f", {len(test_pairs):,} official test pairs" if test_pairs else ""))
try:
    sys.path.insert(0, a.llmcer_repo)
    from llmcer.metrics import calculate_acc, calculate_fp_measure
except Exception:
    calculate_acc = calculate_fp_measure = None

def metrics(partition, label, subset=None):
    pred = {}
    for k, cl in enumerate(partition):
        for x in cl: pred[x] = k
    universe = set(subset) if subset else None
    inr = (lambda x: x in universe) if universe else (lambda x: True)
    tp = sum(n * (n - 1) // 2 for n in Counter((pred[x], cid[x]) for x in recs if inr(x)).values())
    P_ = sum(n * (n - 1) // 2 for n in Counter(pred[x] for x in recs if inr(x)).values())
    G_ = sum(n * (n - 1) // 2 for n in Counter(cid[x] for x in recs if inr(x)).values()) if universe else G
    P = tp / P_ if P_ else 0; R = tp / G_ if G_ else 0; F = 2 * P * R / (P + R) if P + R else 0
    # official-convention view: pairs with IDENTICAL normalized titles are unscored (the WDC test
    # set never labels such a pair negative, while the table's cluster ids often do)
    if TITLE_KEY:
        tk = TITLE_KEY
        tp_same = sum(n * (n - 1) // 2 for n in Counter((pred[x], cid[x], tk[x]) for x in recs if inr(x)).values())
        pp_same = sum(n * (n - 1) // 2 for n in Counter((pred[x], tk[x]) for x in recs if inr(x)).values())
        g_same = sum(n * (n - 1) // 2 for n in Counter((cid[x], tk[x]) for x in recs if inr(x)).values())
        tpd, ppd, gd = tp - tp_same, P_ - pp_same, G_ - g_same
        Pd = tpd / ppd if ppd else 0; Rd = tpd / gd if gd else 0
        extra = f" | diff-title P {Pd:.3f} R {Rd:.3f} F1 {2*Pd*Rd/(Pd+Rd) if Pd+Rd else 0:.3f}"
    else: extra = ""
    extra += " (covered records only)" if universe else ""
    if calculate_acc and not universe:
        try: extra = f" | ACC {calculate_acc(gold_full, partition):.3f} FP {calculate_fp_measure(gold_full, partition):.3f}"
        except Exception as e: extra = f" | (llmcer metrics failed: {str(e)[:40]})"
    if test_pairs:
        tps = [(x, y, l) for x, y, l in test_pairs if not universe or (x in universe and y in universe)]
        tp2 = sum(1 for x, y, l in tps if l and pred.get(x) == pred.get(y)); pp = sum(1 for x, y, l in tps if pred.get(x) == pred.get(y)); gp = sum(1 for _, _, l in tps if l)
        p2 = tp2 / pp if pp else 0; r2 = tp2 / gp if gp else 0; extra += f" | official test ({len(tps)} pairs) P {p2:.3f} R {r2:.3f} F1 {2*p2*r2/(p2+r2) if p2+r2 else 0:.3f}"
    log(f"  [{label}] P {P:.3f} R {R:.3f} F1 {F:.3f} | asserted {P_:,} TP {tp:,} FP {P_-tp:,} FN {G_-tp:,} | clusters {len(partition):,}{extra}")
    return {"P": P, "R": R, "F1": F, "asserted": P_, "TP": tp, "clusters": len(partition)}

# ---------------- round-0 BM25 blocks ----------------
def grams3(s):
    s = re.sub(r"[^a-z0-9 ]+", " ", norm(s)); out = []
    for w in s.split():
        w = f" {w} "; out.extend(w[i:i + 3] for i in range(len(w) - 2))
    return out
def bm25_blocks():
    """BM25 top-k self-join. Block = a record plus its neighbours in BOTH directions (records it
    retrieved and records that retrieved it), ordered by rank, capped at --cap. A block is created
    only for records with at least one MUTUAL neighbour (present in each other's top-k), which
    drops records nothing resembles. Blocks overlap by design; decisions are voted (see assemble)."""
    import bm25s
    ids = sorted(recs, key=str)
    texts = [" ".join(recs[i].get(f, "") for f in BM25F) for i in ids]
    toks = [grams3(t) for t in texts] if a.bm25_tokens == "char3" else [norm(t).split() for t in texts]
    toks = [t if t else ["__empty__"] for t in toks]
    idx = bm25s.BM25(); idx.index(toks, show_progress=False)
    global BM25_IDX, BM25_IDS, BM25_TOKS; BM25_IDX, BM25_IDS, BM25_TOKS = idx, ids, toks
    res, sc = idx.retrieve(toks, k=min(a.k + 1, len(ids)), n_threads=max(1, os.cpu_count() or 1), show_progress=False)
    top = {}
    for qi in range(len(ids)):
        top[qi] = [int(res[qi, r]) for r in range(res.shape[1]) if int(res[qi, r]) != qi and sc[qi, r] > 0][:a.k]
    topset = {u: set(v) for u, v in top.items()}
    inbound = defaultdict(list)
    for u, vs in top.items():
        for v in vs: inbound[v].append(u)
    blocks, seen, gated = [], set(), 0
    for u in range(len(ids)):
        m = a.gate_rank or a.k
        mutual = [v for v in top[u][:m] if u in top[v][:m]]
        if a.gate == "mutual" and not mutual: gated += 1; continue
        order = top[u] + [w for w in inbound[u] if w not in topset[u]]
        if a.anchor:   # owner first, neighbours in rank order; one call per owner
            mem = [u] + order[:a.cap - 1]
            if len(mem) >= 2: blocks.append([ids[x] for x in mem])
            continue
        b = frozenset([u] + order[:a.cap - 1])
        if len(b) >= 2 and b not in seen: seen.add(b); blocks.append(sorted((ids[x] for x in b), key=str))
    return blocks, gated, sum(len(v) for v in top.values())

def block_stats(blocks, label):
    bo = defaultdict(set)
    for i, b in enumerate(blocks):
        for u in b: bo[u].add(i)
    reach = sum(1 for cl in gold_clusters for i, x in enumerate(cl) for y in cl[i+1:] if bo[x] & bo[y])
    cand = sum(len(b) * (len(b) - 1) // 2 for b in blocks)
    log(f"  [{label}] blocks {len(blocks):,} (largest {max((len(b) for b in blocks), default=0)}), reach {reach:,}/{G:,} = {reach/G if G else 0:.3f}, candidate pairs {cand:,}, calls/record {len(blocks)/N:.2f}")
    return bo, reach

# ---------------- LLM plumbing ----------------
llm = ChatClient(deployment=a.model); lock = threading.Lock()
JSON_SCHEMA = {"type": "json_schema", "name": "clusters", "strict": True, "schema": {"type": "object", "additionalProperties": False, "required": ["clusters"], "properties": {"clusters": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["members", "rep"], "properties": {"members": {"type": "array", "items": {"type": "string"}}, "rep": {"type": "object", "additionalProperties": False, "required": FIELDS, "properties": {f: {"type": "string"} for f in FIELDS}}}}}}}}
ANCHOR_SCHEMA = {"type": "json_schema", "name": "anchor", "strict": True, "schema": {"type": "object", "additionalProperties": False, "required": ["matches", "rep"], "properties": {"matches": {"type": "array", "items": {"type": "integer"}}, "rep": {"type": "object", "additionalProperties": False, "required": FIELDS, "properties": {f: {"type": "string"} for f in FIELDS}}}}}
bkey = lambda c: hashlib.sha1("|".join(map(str, c)).encode()).hexdigest()[:16] + f"#{len(c)}"
def run_calls(items, out_path, make_prompt, system, cap_fn, schema=None):
    done = {}
    if os.path.exists(out_path):
        for line in open(out_path):
            r = json.loads(line); done[r["key"]] = r
    todo = [it for it in items if bkey(it) not in done]
    if a.no_calls and todo: log(f"  --no-calls: {len(todo):,} of {len(items):,} blocks have no logged call; skipped"); todo = []
    logf = open(out_path, "a")
    def one(it):
        kw = {"response_format": ((schema or JSON_SCHEMA) if a.json_schema else {"type": "json_object"}), "max_completion_tokens": cap_fn(it)}
        if a.reasoning: kw["reasoning_effort"] = a.reasoning
        res = llm.chat(system(it) if callable(system) else system, make_prompt(it), **kw)
        row = {"key": bkey(it), "text": res["text"], "usage": res["usage"], "latency_s": res["latency_s"]}
        with lock: logf.write(json.dumps(row, ensure_ascii=False) + "\n"); logf.flush()
        return row
    fails = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, it): it for it in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try: r = f.result(); done[r["key"]] = r
            except Exception as e:
                fails += 1
                if fails <= 5: log(f"  FAIL {bkey(futs[f])[:20]}: {str(e)[:120]}")
            if i % 500 == 0: log(f"  {i}/{len(todo)}")
    for it in items:
        r = done.get(bkey(it))
        if r: bill(a.model, r["usage"])
    if fails: log(f"  {fails} calls failed")
    return done

def parse(text, ids):
    """clusters with >=2 members only; unlisted ids are singletons. Returns (clusters, stats)."""
    obj = _extract_json(text); val = obj.get("clusters") if isinstance(obj, dict) else obj
    if not isinstance(val, list): raise ValueError("no clusters")
    known, placed, out = set(ids), set(), []
    st = Counter()
    for e in val:
        if not isinstance(e, dict): continue
        ms = []
        for m in e.get("members") or []:
            m = str(m)
            if m not in known: st["unknown"] += 1
            elif m in placed: st["dup"] += 1
            else: ms.append(m)
        if len(ms) >= 2:
            placed.update(ms); out.append({"members": ms, "rep": e.get("rep") if isinstance(e.get("rep"), dict) else None})
    return out, st

def parse_anchor(text, block):
    """{"matches":[numbers],"rep":{...}} for block = [owner] + candidates -> same shape as parse()."""
    obj = _extract_json(text)
    if not isinstance(obj, dict) or not isinstance(obj.get("matches"), list): raise ValueError("no matches")
    owner, cands = block[0], block[1:]
    st, sel = Counter(), []
    for m in obj["matches"]:
        try: m = int(m)
        except (TypeError, ValueError): st["unknown"] += 1; continue
        if not 1 <= m <= len(cands): st["unknown"] += 1
        elif cands[m - 1] in sel: st["dup"] += 1
        else: sel.append(cands[m - 1])
    if not sel: return [], st
    return [{"members": [owner] + sel, "rep": obj.get("rep") if isinstance(obj.get("rep"), dict) else None}], st

sol_cache = {}
def sol_call(system, user, path):
    if os.path.exists(path): return json.load(open(path))
    if a.no_calls: raise SystemExit(f"--no-calls but {path} missing")
    res = ChatClient(deployment=a.design_model).chat(system, user, max_completion_tokens=30_000)
    bill(a.design_model, res["usage"]); json.dump(res, open(path, "w"), ensure_ascii=False); return res
def schemes_from(res):
    code = re.search(r"```python\n(.*?)```", res["text"], re.S).group(1); ns = {}; exec(code, ns)
    return list(ns["SCHEMES"].values()), list(ns["SCHEMES"])

def components(units, fns):
    """units: uid -> dict with fields (+ 'members'); blocks = connected groups over shared keys, capped; oversized -> per-key sub-blocks."""
    blocks = defaultdict(list)
    for u, rec in units.items():
        ks = []
        for fn in fns:
            try: ks.extend(fn(rec) or [])
            except Exception: pass
        for k in sorted(set(k for k in ks if k)): blocks[k].append(u)
    parent, unit_keys = {}, defaultdict(set)
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for k, us in blocks.items():
        if len(us) < 2 or len(us) > 5000: continue   # a key shared by >5000 units is a stop-key
        for u in us: parent.setdefault(u, u); unit_keys[u].add(k)
        r0 = find(us[0])
        for u in us[1:]: parent[find(u)] = r0
    comp = defaultdict(list)
    for u in parent: comp[find(u)].append(u)
    out, seen, n_over = [], set(), 0
    def emit(ch):
        key = tuple(ch)
        if len(ch) >= 2 and key not in seen: seen.add(key); out.append(list(ch))
    for v in comp.values():
        v = sorted(v, key=str)
        if len(v) <= a.cap: emit(v); continue
        n_over += 1; vset = set(v); kb = defaultdict(list)
        for u in v:
            for k in unit_keys[u]: kb[k].append(u)
        for k, us in sorted(kb.items()):
            us = sorted(set(us) & vset, key=lambda x: (norm(units[x].get(FIELDS[0], "")), str(x)))
            for s in range(0, len(us), a.cap): emit(us[s:s + a.cap])
    return out, n_over

# ---------------- round 1 ----------------
blocks0, n_over0, n_edges = bm25_blocks()
log(f"round-0 BM25: {n_edges:,} neighbour edges; {n_over0:,} records without a mutual neighbour get no block (gate={a.gate})")
bo0, reach0 = block_stats(blocks0, "round-0 blocks")
json.dump(blocks0, open(f"{OUT}/blocks_r1.json", "w"))
if a.blocks_only: sys.exit(0)
SYS = RP.resolve_system(FIELDS)
CARDS, type_of = None, None
if a.cards:
    ns_cards = {}; exec(open(a.cards).read(), ns_cards)  # noqa: S102
    CARDS, type_of = ns_cards["CARDS"], ns_cards["type_of"]
    log(f"identity cards: {a.cards} ({len(CARDS)} kinds); record kinds: {dict(Counter(type_of(r) for r in recs.values()).most_common(6))}")
def kind_of(rid):
    try: return type_of(recs[rid]) if type_of else None
    except Exception: return "other"  # noqa: BLE001
def card_text(kind):
    return (CARDS.get(kind) or CARDS.get("other", "")) if CARDS else ""
def anchor_system_for(b):
    base = RP.anchor_system(FIELDS)
    if not CARDS: return base
    k = kind_of(b[0])
    return base + f"\n\nThe target is of kind: {k}. Identity theory for this kind (apply it; where it conflicts with the generic rules above, it takes precedence):\n{card_text(k)}"
def resolve_system_for(rec_ids):
    """later rounds: cards of the (up to 2) dominant kinds among the block's records."""
    if not CARDS: return SYS
    kinds = Counter(kind_of(x) for x in rec_ids)
    top = [k for k, _ in kinds.most_common(2)]
    note = "\n\nThe items are mostly of kind: " + ", ".join(top) + ". Identity theory per kind (apply it; where it conflicts with the generic rules above, it takes precedence):"
    for k in top: note += f"\n[{k}] {card_text(k)}"
    return SYS + note
items = blocks0[:a.ramp] if a.ramp else blocks0
log(f"round 1: {len(items):,} calls on {a.model}" + (f" (reasoning={a.reasoning})" if a.reasoning else "") + (" [anchored: owner vs numbered neighbours, either-side merge]" if a.anchor else ""))
if a.anchor:
    r1 = run_calls(items, f"{OUT}/round1.jsonl", lambda b: RP.serialize_anchor(b[0], b[1:], recs, FIELDS), anchor_system_for, lambda b: min(20_000, 3000 + 120 * len(b)), schema=ANCHOR_SCHEMA)
else:
    r1 = run_calls(items, f"{OUT}/round1.jsonl", lambda b: "Items:\n" + "\n".join(RP.serialize_record(i, recs[i], FIELDS) for i in b), lambda b: resolve_system_for(b), lambda b: min(60_000, 3000 + 120 * len(b)))
def assemble(blocks, parsed, universe, either_side=False):
    """blocks: list of id lists; parsed: block index -> list of clusters (members, rep). Every pair
    asserted in some block is accepted if its 'merged' verdicts outnumber its 'kept apart' verdicts
    across all blocks containing both (--vote majority), or if asserted anywhere (--vote any).
    Returns (parent-find function, rep_of)."""
    merged, madj = Counter(), defaultdict(set)
    rep_of = {}
    for bi, cl in parsed.items():
        for g in cl:
            ms = g["members"]
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    e = (ms[i], ms[j]) if str(ms[i]) < str(ms[j]) else (ms[j], ms[i])
                    merged[e] += 1; madj[e[0]].add(e[1]); madj[e[1]].add(e[0])
            if g["rep"]:
                for x in ms:
                    if x not in rep_of or rep_of[x][0] < len(ms): rep_of[x] = (len(ms), g["rep"])
    kept = Counter()
    if a.vote == "majority" and not (a.anchor and (blocks is items or either_side)):
        for bi, cl in parsed.items():
            bset = set(blocks[bi]); lab = {}
            for ci, g in enumerate(cl):
                for x in g["members"]: lab[x] = ci
            for u in blocks[bi]:
                for v in madj.get(u, ()):
                    if v in bset and str(u) < str(v) and lab.get(u, ("s", u)) != lab.get(v, ("s", v)): kept[(u, v)] += 1
    par = {x: x for x in universe}
    def find(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    accepted = rejected = 0
    for e, n in merged.items():
        if a.vote == "any" or (a.anchor and (blocks is items or either_side)) or n > kept.get(e, 0): par[find(e[0])] = find(e[1]); accepted += 1
        else: rejected += 1
    log(f"  vote: {len(merged):,} asserted pairs, {accepted:,} accepted, {rejected:,} rejected by contrary verdicts")
    return find, rep_of

parsed1, fails, pstats = {}, 0, Counter()
for bi, b in enumerate(items):
    row = r1.get(bkey(b))
    if row is None: continue
    try: cl, st = parse_anchor(row["text"], b) if a.anchor else parse(row["text"], b)
    except (ValueError, AttributeError): fails += 1; continue
    pstats.update(st); parsed1[bi] = cl
rfind, rep_of = assemble(items, parsed1, list(recs))
groups = defaultdict(list)
for r in sorted(recs, key=str): groups[rfind(r)].append(r)
clusters = [{"members": ms, "rep": max((rep_of[x] for x in ms if x in rep_of), default=(0, None), key=lambda t: t[0])[1]} for ms in groups.values()]
log(f"round 1 done: {len(r1):,} calls, {fails} parse failures, {dict(pstats)} -> {len(clusters):,} clusters")
m = metrics([c["members"] for c in clusters], "after round 1", subset=({x for b in items for x in b} if a.ramp else None))
json.dump([c["members"] for c in clusters], open(f"{OUT}/partition_r1.json", "w"))
history = [{"round": 1, **m}]
lst, bil = costs(); log(f"spend so far: list ${lst:.2f} / billed ${bil:.2f}")
if a.ramp: sys.exit(0)

# ---------------- rounds 2.. ----------------
record_blocks = blocks0      # record-level blocks of the last round (for kept-apart evidence)
adjudicated = [bo0]          # per round: record -> set(block ids)
prev_calls = len(items)      # stopping rule: each round must need fewer calls than the one before
rnd = 1
while rnd < a.max_rounds:
    rnd += 1
    # design keys from the previous round's decisions
    ev = RB.evidence_from_clusters(recs, [c["members"] for c in clusters], record_blocks, FIELDS)
    fld = lambda i: {f: recs[i].get(f, "") for f in FIELDS}
    pos_pairs = [(fld(x), fld(y), kind) for x, y, kind in ev["pos"]]; neg_pairs = [(fld(x), fld(y)) for x, y in ev["neg"]]; rand_recs = [fld(i) for i in ev["rand"]]
    if a.privatize and not os.path.exists(f"{OUT}/keys_r{rnd}.json"):
        from blueprint.privatize import Privatizer
        PV = Privatizer(a.privatize, recs, FIELDS, cache=f"{OUT}/privatize.jsonl")
        fp = PV.pairs([(x, y) for x, y, _ in pos_pairs]); pos_pairs = [(f[0], f[1], k) for f, (_, _, k) in zip(fp, pos_pairs) if f]
        fn = PV.pairs(neg_pairs); neg_pairs = [f for f in fn if f]
        fr = PV.records(rand_recs); rand_recs = [f for f in fr if f]
        prep = PV.report(); json.dump({"round": rnd, "model": a.privatize, **prep}, open(f"{OUT}/privatize_r{rnd}_report.json", "w"), indent=1)
        json.dump({"pos": pos_pairs, "neg": neg_pairs, "rand": rand_recs}, open(f"{OUT}/keys_r{rnd}_evidence_private.json", "w"), ensure_ascii=False)
        log(f"  privacy filter ({a.privatize}) on round-{rnd} key-design evidence: {prep}")
    ku = ["=== CONFIRMED DUPLICATE PAIRS (previous resolution pass; keys must co-block each pair; note WHAT differs) ===", ""]
    for x, y, kind in pos_pairs: ku += [f"[differs in: {kind}]", json.dumps(x, ensure_ascii=False), json.dumps(y, ensure_ascii=False), "--"]
    ku += ["", "=== CONFIRMED DISTINCT PAIRS (kept apart by the previous pass; they will share keys and that is fine — do NOT design against them) ===", ""]
    for x, y in neg_pairs: ku += [json.dumps(x, ensure_ascii=False), json.dumps(y, ensure_ascii=False), "--"]
    ku += ["", "=== RANDOM SAMPLE RECORDS ===", ""] + [json.dumps(r, ensure_ascii=False) for r in rand_recs] + ["", "Design the blocking key schemes now."]
    S, names = schemes_from(sol_call(RB.keydesign_system(FIELDS), "\n".join(ku), f"{OUT}/keys_r{rnd}.json"))
    log(f"round-{rnd} keys ({a.design_model}): {names} | evidence strata {ev['strata']}")
    if a.key_anchor and a.key_units == "reps":
        # ---- uniform loop: the current clusters, described by their representatives, are the units; candidates = units sharing a
        # designed key value; the same anchored call as round 1 decides (target representative vs candidate representatives, card)
        units = {}
        for k_, c in enumerate(clusters):
            m0 = recs[c["members"][0]]; rp = c["rep"] or {}
            units[f"u{k_}"] = {**{f: str(rp.get(f) or m0.get(f, "")) for f in FIELDS}, "members": c["members"]}
        urecs = {u: {f: v[f] for f in FIELDS} for u, v in units.items()}
        kb = defaultdict(list)
        for u, rec in urecs.items():
            ks = set()
            for fn in S:
                try: ks.update(k for k in (fn(rec) or []) if k)
                except Exception: pass
            for k in ks: kb[k].append(u)
        kb = {k: v for k, v in kb.items() if 2 <= len(v) <= a.key_max_share}   # selectivity cut: a value held by more units proposes no candidates
        shared = defaultdict(Counter)
        for k, us in kb.items():
            for u in us:
                for v in us:
                    if u != v: shared[u][v] += 1
        kk = a.key_k or a.k; pos_of = {rid: i for i, rid in enumerate(BM25_IDS)}
        first = {u: v["members"][0] for u, v in units.items()}
        if a.key_accept_share:   # per-unit key values, to judge acceptance by the rarest shared value
            held = Counter(k for k, us in kb.items() for _ in us)
            ukeys = defaultdict(set)
            for k, us in kb.items():
                for u in us: ukeys[u].add(k)
            strength = lambda u, v: min((held[k] for k in ukeys[u] & ukeys[v]), default=10**9)
        key_blocks = []
        for u in sorted(units, key=lambda x: int(x[1:])):
            cands = shared.get(u)
            if not cands: continue
            sc = BM25_IDX.get_scores(BM25_TOKS[pos_of[first[u]]]) if len(cands) > kk else None
            ranked = sorted(cands, key=lambda v: (-cands[v], -(float(sc[pos_of[first[v]]]) if sc is not None else 0.0), int(v[1:])))[:kk]
            key_blocks.append([u] + ranked)
        rec_blocks = [[m for u in ub for m in units[u]["members"]] for ub in key_blocks]
        log(f"  units {len(units):,} ({sum(1 for v in units.values() if len(v['members']) > 1):,} with copies); key candidates: {len(kb):,} key values held by <= {a.key_max_share} units, {sum(len(c) for c in shared.values())//2:,} unit pairs before the rank cut")
        bo_k, reach_k = block_stats(rec_blocks, f"round-{rnd} entity-round lists (k={kk})")
        json.dump({"keys": names, "units": {u: v["members"] for u, v in units.items()}, "blocks": key_blocks}, open(f"{OUT}/blocks_r{rnd}_keyreps.json", "w"))
        if not key_blocks: log("no key candidates -> stop"); break
        if rnd > 2 and not a.no_budget_guard and len(key_blocks) >= prev_calls:
            log(f"budget guard: round {rnd} would need {len(key_blocks):,} calls, not fewer than the previous round's {prev_calls:,} -> stop"); break
        def unit_system(b):
            base = RP.anchor_system(FIELDS)
            if not CARDS: return base
            try: k_ = type_of(urecs[b[0]]) if type_of else None
            except Exception: k_ = "other"
            return base + f"\n\nThe target is of kind: {k_}. Identity theory for this kind (apply it; where it conflicts with the generic rules above, it takes precedence):\n{card_text(k_)}"
        log(f"round {rnd} (entity round): {len(key_blocks):,} calls on {a.model}")
        rr = run_calls(key_blocks, f"{OUT}/round{rnd}_keyreps.jsonl", lambda b: RP.serialize_anchor(b[0], b[1:], urecs, FIELDS), unit_system, lambda b: min(20_000, 3000 + 120 * len(b)), schema=ANCHOR_SCHEMA)
        parsed_k, fails, pstats, dropped_sel = {}, 0, Counter(), 0
        for bi, b in enumerate(key_blocks):
            row = rr.get(bkey(b))
            if row is None: continue
            try: cl, st = parse_anchor(row["text"], b)
            except (ValueError, AttributeError): fails += 1; continue
            if a.key_accept_share and cl:   # acceptance-time selectivity: keep a selected candidate only on a selective shared key
                kept = [x for x in cl[0]["members"][1:] if strength(b[0], x) <= a.key_accept_share]
                dropped_sel += len(cl[0]["members"]) - 1 - len(kept)
                cl = [{"members": [b[0]] + kept, "rep": cl[0]["rep"]}] if kept else []
            pstats.update(st); parsed_k[bi] = cl
        if a.key_accept_share: log(f"  acceptance rule (shared key value held by <= {a.key_accept_share} units): {dropped_sel:,} selections dropped")
        ufind, urep = assemble(key_blocks, parsed_k, list(units), either_side=True)
        merged = defaultdict(list)
        for u in units: merged[ufind(u)].append(u)
        new_clusters = []
        for us in merged.values():
            ms = [m for u in us for m in units[u]["members"]]
            rep = max((urep[u] for u in us if u in urep), default=(0, None), key=lambda t: t[0])[1] or next((clusters[int(u[1:])]["rep"] for u in us if clusters[int(u[1:])]["rep"]), None)
            new_clusters.append({"members": ms, "rep": rep})
        changed = len(new_clusters) != len(clusters); clusters = new_clusters
        log(f"round {rnd} (entity round) done: {len(rr):,} calls, {fails} parse failures, {dict(pstats)} -> {len(clusters):,} clusters")
        m = metrics([c["members"] for c in clusters], f"after round {rnd}, entity round")
        json.dump([c["members"] for c in clusters], open(f"{OUT}/partition_r{rnd}.json", "w"))
        history.append({"round": rnd, "mode": "entity round", **m})
        # kept-apart evidence for the next key design at unit granularity (one record per unit): the record-level lists
        # expand to ~1,000 records and the pairwise scan in evidence_from_clusters would take hours
        record_blocks = [[units[u]["members"][0] for u in ub] for ub in key_blocks]; adjudicated.append(bo_k); prev_calls = len(key_blocks)
        lst, bil = costs(); log(f"spend so far: list ${lst:.2f} / billed ${bil:.2f}")
        if not changed: log("partition unchanged -> fixed point"); break
        continue
    if a.key_anchor:
        # ---- clean-slate round: every raw record is a target again; its candidates are the records sharing a designed key value
        kb = defaultdict(list)
        for rid, rec in recs.items():
            ks = set()
            for fn in S:
                try: ks.update(k for k in (fn({f: rec.get(f, "") for f in FIELDS}) or []) if k)
                except Exception: pass
            for k in ks: kb[k].append(rid)
        kb = {k: v for k, v in kb.items() if 2 <= len(v) <= a.key_max_share}   # selectivity cut (see --key-max-share)
        shared = defaultdict(Counter)
        for k, us in kb.items():
            for u in us:
                for v in us:
                    if u != v: shared[u][v] += 1
        kk = a.key_k or a.k; pos_of = {rid: i for i, rid in enumerate(BM25_IDS)}
        key_blocks, dropped_seen = [], 0
        for u in sorted(recs, key=str):
            cands = shared.get(u)
            if not cands: continue
            if a.key_new_only:
                n0 = len(cands); cands = Counter({v: n for v, n in cands.items() if not (bo0.get(u, set()) & bo0.get(v, set()))}); dropped_seen += n0 - len(cands)
                if not cands: continue
            sc = BM25_IDX.get_scores(BM25_TOKS[pos_of[u]]) if len(cands) > kk else None
            ranked = sorted(cands, key=lambda v: (-cands[v], -(float(sc[pos_of[v]]) if sc is not None else 0.0), str(v)))[:kk]
            key_blocks.append([u] + ranked)
        log(f"  key candidates: {len(kb):,} key values in use, {sum(len(c) for c in shared.values())//2:,} candidate pairs before the cut" + (f", {dropped_seen:,} already judged in round 1 dropped" if a.key_new_only else ""))
        bo_k, reach_k = block_stats(key_blocks, f"round-{rnd} key-anchored lists (k={kk})")
        json.dump({"keys": names, "blocks": key_blocks}, open(f"{OUT}/blocks_r{rnd}_keyanchor.json", "w"))
        if not key_blocks: log("no key candidates -> stop"); break
        if rnd > 2 and not a.no_budget_guard and len(key_blocks) >= prev_calls:
            log(f"budget guard: round {rnd} would need {len(key_blocks):,} calls, not fewer than the previous key-anchored round's {prev_calls:,} -> stop"); break
        log(f"round {rnd} (key-anchored over raw records, clean slate): {len(key_blocks):,} calls on {a.model}")
        rr = run_calls(key_blocks, f"{OUT}/round{rnd}_keyanchor.jsonl", lambda b: RP.serialize_anchor(b[0], b[1:], recs, FIELDS), anchor_system_for, lambda b: min(20_000, 3000 + 120 * len(b)), schema=ANCHOR_SCHEMA)
        parsed_k, fails, pstats = {}, 0, Counter()
        for bi, b in enumerate(key_blocks):
            row = rr.get(bkey(b))
            if row is None: continue
            try: cl, st = parse_anchor(row["text"], b)
            except (ValueError, AttributeError): fails += 1; continue
            pstats.update(st); parsed_k[bi] = cl
        kfind, krep = assemble(key_blocks, parsed_k, list(recs), either_side=True)
        kgroups = defaultdict(list)
        for r in sorted(recs, key=str): kgroups[kfind(r)].append(r)
        key_clusters = [{"members": ms, "rep": max((krep[x] for x in ms if x in krep), default=(0, None), key=lambda t: t[0])[1]} for ms in kgroups.values()]
        log(f"round {rnd} (key-anchored) done: {len(rr):,} calls, {fails} parse failures, {dict(pstats)} -> {len(key_clusters):,} clusters")
        m_alone = metrics([c["members"] for c in key_clusters], f"after round {rnd}, key-anchored alone")
        par = {x: x for x in recs}
        def ufind(x):
            while par[x] != x: par[x] = par[par[x]]; x = par[x]
            return x
        for cs in (clusters, key_clusters):
            for c in cs:
                for x in c["members"][1:]: par[ufind(x)] = ufind(c["members"][0])
        ug = defaultdict(list)
        for r in sorted(recs, key=str): ug[ufind(r)].append(r)
        union_clusters = [{"members": ms, "rep": next((c["rep"] for c in key_clusters if c["rep"] and c["members"][0] in ms), None)} for ms in ug.values()]
        m_union = metrics([c["members"] for c in union_clusters], f"after round {rnd}, round 1 + key-anchored closed together")
        json.dump([c["members"] for c in key_clusters], open(f"{OUT}/partition_r{rnd}_keyanchor.json", "w"))
        json.dump([c["members"] for c in union_clusters], open(f"{OUT}/partition_r{rnd}_union.json", "w"))
        history.append({"round": rnd, "mode": "key-anchored alone", **m_alone}); history.append({"round": rnd, "mode": "round 1 + key-anchored", **m_union})
        clusters = union_clusters if a.key_carry == "union" else key_clusters
        record_blocks = key_blocks; adjudicated.append(bo_k); prev_calls = len(key_blocks)
        lst, bil = costs(); log(f"spend so far: list ${lst:.2f} / billed ${bil:.2f}")
        continue
    # units = current clusters, described by representative (or first member)
    units = {}
    for k, c in enumerate(clusters):
        m0 = recs[c["members"][0]]; rp = c["rep"] or {}
        units[f"u{k}"] = {**{f: str(rp.get(f) or m0.get(f, "")) for f in FIELDS}, "members": c["members"]}
    ublocks, n_over = components(units, S)
    # keep only blocks not already adjudicated (some member pair never shared an earlier block)
    def already(ub):
        ms = [m for u in ub for m in units[u]["members"]]
        for bo in adjudicated:
            common = set.intersection(*(bo.get(m, set()) for m in ms)) if ms else set()
            if common: return True
        return False
    new_blocks = [ub for ub in ublocks if not already(ub)]
    rec_blocks = [[m for u in ub for m in units[u]["members"]] for ub in new_blocks]
    bo_r, reach_r = block_stats(rec_blocks, f"round-{rnd} blocks (new only; {len(ublocks):,} formed, {n_over} oversized)")
    json.dump({"units": {u: v["members"] for u, v in units.items()}, "blocks": new_blocks}, open(f"{OUT}/blocks_r{rnd}.json", "w"))
    if not new_blocks: log("no new blocks -> fixed point"); break
    if not a.no_budget_guard and len(new_blocks) >= prev_calls:
        log(f"budget guard: round {rnd} would need {len(new_blocks):,} calls, not fewer than the previous round's {prev_calls:,} -> stop"); break
    prev_calls = len(new_blocks)
    uid_of = lambda ub: {f"u{i}": u for i, u in enumerate(ub, 1)}
    def prompt_r(ub): return "Items:\n" + "\n".join(RP.serialize_unit(f"u{i}", units[u], recs, FIELDS) for i, u in enumerate(ub, 1))
    log(f"round {rnd}: {len(new_blocks):,} calls on {a.model}")
    rr = run_calls(new_blocks, f"{OUT}/round{rnd}.jsonl", prompt_r, lambda ub: resolve_system_for([m for u in ub for m in units[u]["members"]]), lambda ub: min(60_000, 3000 + 250 * len(ub)))
    parsed_r, fails, pstats = {}, 0, Counter()
    for bi, ub in enumerate(new_blocks):
        row = rr.get(bkey(ub))
        if row is None: continue
        labels = [f"u{i}" for i in range(1, len(ub) + 1)]; lab2u = dict(zip(labels, ub))
        try: cl, st = parse(row["text"], labels)
        except (ValueError, AttributeError): fails += 1; continue
        pstats.update(st)
        parsed_r[bi] = [{"members": [lab2u[x] for x in g["members"]], "rep": g["rep"]} for g in cl]
    ufind, urep = assemble(new_blocks, parsed_r, list(units))
    merged = defaultdict(list)
    for u in units: merged[ufind(u)].append(u)
    new_clusters = []
    for us in merged.values():
        ms = [m for u in us for m in units[u]["members"]]
        rep = max((urep[u] for u in us if u in urep), default=(0, None), key=lambda t: t[0])[1] or max((clusters[int(u[1:])]["rep"] for u in us if clusters[int(u[1:])]["rep"]), default=None, key=lambda r: 1)
        new_clusters.append({"members": ms, "rep": rep})
    changed = len(new_clusters) != len(clusters)
    clusters = new_clusters
    log(f"round {rnd} done: {len(rr):,} calls, {fails} parse failures, {dict(pstats)} -> {len(clusters):,} clusters")
    m = metrics([c["members"] for c in clusters], f"after round {rnd}")
    json.dump([c["members"] for c in clusters], open(f"{OUT}/partition_r{rnd}.json", "w"))
    history.append({"round": rnd, **m})
    record_blocks = rec_blocks; adjudicated.append(bo_r)
    lst, bil = costs(); log(f"spend so far: list ${lst:.2f} / billed ${bil:.2f}")
    if not changed: log("partition unchanged -> fixed point"); break

lst, bil = costs()
summary = {"name": a.name, "model": a.model, "reasoning": a.reasoning, "anchor": a.anchor, "cards": a.cards, "privatize": a.privatize, "k": a.k, "records": N, "true_pairs": G, "reach0": reach0 / G if G else 0,
           "history": history, "spend": {d: {"prompt": v[0], "cached": v[1], "completion": v[2], "calls": v[3]} for d, v in spend.items()},
           "cost_list": lst, "cost_billed": bil, "calls_per_record": sum(v[3] for d, v in spend.items() if d == a.model) / N}
json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=1)
log("spend: " + ", ".join(f"{d}: {v[3]:,} calls, {v[0]:,} in ({v[1]/max(1,v[0]):.0%} cached) / {v[2]:,} out" for d, v in spend.items()) + f" -> list ${lst:.2f} / billed ${bil:.2f} | resolve calls/record {summary['calls_per_record']:.2f}")
