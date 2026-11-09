"""Privacy filter for the design model's inputs.

Premise: the data may not leave the server; the design model (API-only) may still write the identity theory
and the blocking keys, but it must never see a real record. A LOCAL model rewrites every record that would
enter a design prompt with made-up values that keep the format and the kind of thing; for duplicate pairs it
rewrites both records consistently so that how they differ is preserved. A code check then refuses any
rewrite in which a rare real value survived (a token of the real record that occurs in <= k records of the
whole collection); such rows are retried with the offending tokens named, then dropped.

Usage:
    P = Privatizer(model="gpt-oss-120b", recs=recs, fields=FIELDS, cache="<run dir>/privatize.jsonl")
    fake = P.records([rec_dict, ...])           # list of dicts (None where dropped)
    fakes = P.pairs([(rec_a, rec_b), ...])       # list of (dict, dict) (None where dropped)
    P.report()                                   # exposure report dict
"""
import hashlib, json, os, random, re, string, threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from blueprint.llm_client import ChatClient

TOK = re.compile(r"[A-Za-z0-9]+")

RECORDS_SYSTEM = """You are a privacy filter running on a private server. You will be given data records. Rewrite each record with MADE-UP values so that nothing specific survives, while keeping everything that describes the SHAPE of the data.

Change: every name of a person, organisation, place, product, brand, title or work; every code, identifier, serial, part number, model number, email, phone, URL; every number, amount, date and year; every address.
Keep: the same fields; the same format and length pattern of every value (letters stay letters, digits stay digits, same punctuation, separators, capitalisation style and spacing; a code like WH-1000XM3B becomes a different code of the same shape); the same kind of thing (a watch listing stays a watch listing, a journal article stays a journal article, a song stays a song); ordinary descriptive words (colours, materials, units, generic nouns and adjectives, version words such as Live or Remix); empty values stay empty.
Never copy a specific value from the input into the output; every non-empty field must come back changed, and every number must change. Do not explain.

Return ONLY JSON of the form {"records":[{...}, ...]}: exactly one rewritten record per input record, in the same order, with the same field names."""

PAIRS_SYSTEM = """You are a privacy filter running on a private server. You will be given PAIRS of data records; each pair is two descriptions of the same real-world thing, or two things that were judged different, and what matters is HOW the two records differ. Rewrite each pair with MADE-UP values so that nothing specific survives, while preserving exactly the relationship between the two records of a pair.

Change: every name of a person, organisation, place, product, brand, title or work; every code, identifier, serial, part number, model number, email, phone, URL; every number, amount, date and year; every address.
Keep: the same fields; the same format and length pattern of every value (letters stay letters, digits stay digits, same punctuation, separators, capitalisation style and spacing); the same kind of thing; ordinary descriptive words (colours, materials, units, generic nouns, version words such as Live or Remix); empty values stay empty.
Consistency within a pair: the same real value must become the same made-up value in both records; a value that was spelled differently in the two records (word order, abbreviation, punctuation, an added suffix, a missing part, a different number) must be made up so that the two made-up values differ in exactly that way.
Never copy a specific value from the input into the output; every non-empty field must come back changed, and every number must change. Do not explain.

Return ONLY JSON of the form {"pairs":[{"a":{...},"b":{...}}, ...]}: exactly one rewritten pair per input pair, in the same order, with the same field names."""


def _schema_records(fields):
    rec = {"type": "object", "additionalProperties": False, "required": list(fields), "properties": {f: {"type": "string"} for f in fields}}
    return {"type": "json_schema", "name": "private_records", "strict": True,
            "schema": {"type": "object", "additionalProperties": False, "required": ["records"], "properties": {"records": {"type": "array", "items": rec}}}}


def _schema_pairs(fields):
    rec = {"type": "object", "additionalProperties": False, "required": list(fields), "properties": {f: {"type": "string"} for f in fields}}
    pair = {"type": "object", "additionalProperties": False, "required": ["a", "b"], "properties": {"a": rec, "b": rec}}
    return {"type": "json_schema", "name": "private_pairs", "strict": True,
            "schema": {"type": "object", "additionalProperties": False, "required": ["pairs"], "properties": {"pairs": {"type": "array", "items": pair}}}}


class Privatizer:
    def __init__(self, model, recs, fields, cache=None, k_rare=10, k_digit=200, batch=5, pair_batch=2, workers=8, reasoning="low", retries=3):
        self.model, self.fields, self.cache = model, list(fields), cache
        self.k, self.kd, self.batch, self.pair_batch, self.workers, self.reasoning, self.retries = k_rare, k_digit, batch, pair_batch, workers, reasoning, retries
        df = Counter()
        for r in recs.values():
            df.update({t.lower() for f in self.fields for t in TOK.findall(str(r.get(f, "")))})
        self.df = df
        self.llm = ChatClient(deployment=model)
        self.stats = Counter(); self.lock = threading.Lock()
        self.done = {}
        if cache and os.path.exists(cache):
            for line in open(cache):
                if line.strip():
                    d = json.loads(line); self.done[d["key"]] = d["out"]
        self.logf = open(cache, "a") if cache else None

    # ---- the safety check ----
    # A real value "must change" if it contains a digit (unless it is a very common number, df > k_digit) or if it is
    # a rare word (df <= k_rare). A rewrite leaks if any must-change token survives, or if any non-empty field came
    # back unchanged.
    def must_change(self, rec):
        toks = {t.lower() for f in self.fields for t in TOK.findall(str(rec.get(f, "")))}
        out = set()
        for t in toks:
            d = self.df.get(t, 0)
            if any(c.isdigit() for c in t):
                if d <= self.kd: out.add(t)
            elif len(t) >= 3 and d <= self.k: out.add(t)
        return out

    @staticmethod
    def _norm(v):
        return " ".join(TOK.findall(str(v or "").lower()))

    def leaked(self, real_recs, fake_recs):
        """-> sorted list of leaked tokens, plus 'FIELD:<name> unchanged' markers."""
        must = set().union(*[self.must_change(r) for r in real_recs]) if real_recs else set()
        out = {t.lower() for r in fake_recs for f in self.fields for t in TOK.findall(str(r.get(f, "")))}
        bad = sorted(must & out)
        for r, fr in zip(real_recs, fake_recs):
            for f in self.fields:
                if self._norm(r.get(f)) and self._norm(r.get(f)) == self._norm(fr.get(f)): bad.append(f"FIELD:{f} unchanged")
        return bad


    # ---- code fallback: replace what the model kept, shape for shape ----
    def _fake_token(self, t, mapping):
        if t.lower() in mapping: return mapping[t.lower()]
        rng = random.Random(hash((t.lower(), "salt")) & 0xffffffff)
        out = "".join((rng.choice(string.digits) if c.isdigit() else rng.choice(string.ascii_uppercase) if c.isupper() else rng.choice(string.ascii_lowercase)) if c.isalnum() else c for c in t)
        if out.lower() == t.lower(): out = out[:-1] + ("7" if out[-1].isdigit() else "x")
        mapping[t.lower()] = out; return out

    def _force(self, real, fake, mapping):
        """Replace, in code, every must-change token that survived and perturb every unchanged field."""
        fake = dict(fake); must = self.must_change(real)
        for f in self.fields:
            v = str(fake.get(f, "") or "")
            if not v: continue
            def rep(m):
                t = m.group(0)
                return self._fake_token(t, mapping) if t.lower() in must else t
            v2 = TOK.sub(rep, v)
            if self._norm(real.get(f)) and self._norm(v2) == self._norm(real.get(f)):
                toks = TOK.findall(v2)
                if toks:
                    longest = max(toks, key=len); v2 = v2.replace(longest, self._fake_token(longest, mapping), 1)
            fake[f] = v2
        return fake

    # ---- calls ----
    def _key(self, kind, items):
        return hashlib.sha1((kind + "|" + json.dumps(items, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()[:20]

    def _ask(self, system, user, schema, n_items, cap):
        res = self.llm.chat(system, user, response_format=schema, max_completion_tokens=cap, reasoning_effort=self.reasoning)
        with self.lock:
            u = res["usage"]; self.stats["calls"] += 1; self.stats["in_tokens"] += u.get("prompt_tokens") or 0; self.stats["out_tokens"] += u.get("completion_tokens") or 0
        return json.loads(res["text"])

    def _clean(self, d):
        return {f: str(d.get(f, "") or "") for f in self.fields}

    def _records_batch(self, items):
        key = self._key("rec", items)
        if key in self.done: return self.done[key]
        note = ""
        for attempt in range(self.retries + 1):
            user = f"{len(items)} records follow as JSON, one per line; after each, the specific values that MUST be replaced (every other number must change too, and every non-empty field must come back changed).{note}\n\n" + "\n".join(json.dumps(r, ensure_ascii=False) + "\n  must change: " + ", ".join(sorted(self.must_change(r))) for r in items)
            try:
                obj = self._ask(RECORDS_SYSTEM, user, _schema_records(self.fields), len(items), 4000 + 600 * len(items))
                outs = [self._clean(d) for d in obj.get("records", [])]
            except Exception as e:  # noqa: BLE001
                with self.lock: self.stats["call_failures"] += 1
                outs = []
            if len(outs) != len(items):
                with self.lock: self.stats["count_mismatch"] += 1
                note = f"\nReturn exactly {len(items)} records."; continue
            bad = [i for i, (r, f) in enumerate(zip(items, outs)) if self.leaked([r], [f])]
            if not bad:
                result = outs; break
            with self.lock: self.stats["leak_retries"] += 1
            leaked = sorted(set().union(*[set(self.leaked([items[i]], [outs[i]])) for i in bad]))
            note = f"\nYour previous answer kept these, which is not allowed: {', '.join(leaked[:30])}. Replace every listed value with a made-up value of the same shape, and change every non-empty field."
        else:
            result = []
            if len(outs) == len(items):
                mapping = {}
                for r, f in zip(items, outs):
                    if self.leaked([r], [f]):
                        f2 = self._force(r, f, mapping)
                        with self.lock: self.stats["forced_records"] += 1
                        result.append(f2 if not self.leaked([r], [f2]) else None)
                    else: result.append(f)
            elif len(items) > 1:
                result = [x for it in items for x in self._records_batch([it])]   # retry one at a time
            else: result = [None] * len(items)
            with self.lock: self.stats["dropped_records"] += sum(1 for x in result if x is None) if len(items) == 1 else 0
        with self.lock:
            self.done[key] = result
            if self.logf: self.logf.write(json.dumps({"key": key, "kind": "rec", "n": len(items), "out": result}, ensure_ascii=False) + "\n"); self.logf.flush()
        return result

    def _pairs_batch(self, items):
        key = self._key("pair", items)
        if key in self.done: return self.done[key]
        note = ""
        for attempt in range(self.retries + 1):
            user = f"{len(items)} pairs follow as JSON, one pair per line; after each, the specific values that MUST be replaced in both records (consistently; every other number must change too, and every non-empty field must come back changed).{note}\n\n" + "\n".join(json.dumps({"a": x, "b": y}, ensure_ascii=False) + "\n  must change: " + ", ".join(sorted(self.must_change(x) | self.must_change(y))) for x, y in items)
            try:
                obj = self._ask(PAIRS_SYSTEM, user, _schema_pairs(self.fields), len(items), 4000 + 1200 * len(items))
                outs = [(self._clean(p.get("a", {})), self._clean(p.get("b", {}))) for p in obj.get("pairs", [])]
            except Exception as e:  # noqa: BLE001
                with self.lock: self.stats["call_failures"] += 1
                outs = []
            if len(outs) != len(items):
                with self.lock: self.stats["count_mismatch"] += 1
                note = f"\nReturn exactly {len(items)} pairs."; continue
            bad = [i for i, ((x, y), (fx, fy)) in enumerate(zip(items, outs)) if self.leaked([x, y], [fx, fy])]
            if not bad:
                result = outs; break
            with self.lock: self.stats["leak_retries"] += 1
            leaked = sorted(set().union(*[set(self.leaked(list(items[i]), list(outs[i]))) for i in bad]))
            note = f"\nYour previous answer kept these, which is not allowed: {', '.join(leaked[:30])}. Replace every listed value with a made-up value of the same shape, consistently in both records of the pair, and change every non-empty field."
        else:
            result = []
            if len(outs) == len(items):
                for (x, y), (fx, fy) in zip(items, outs):
                    if self.leaked([x, y], [fx, fy]):
                        mapping = {}; fx2 = self._force(x, fx, mapping); fy2 = self._force(y, fy, mapping)   # one mapping per pair keeps it consistent
                        with self.lock: self.stats["forced_pairs"] += 1
                        result.append((fx2, fy2) if not self.leaked([x, y], [fx2, fy2]) else None)
                    else: result.append((fx, fy))
            elif len(items) > 1:
                result = [x for it in items for x in self._pairs_batch([it])]   # retry one at a time
            else: result = [None] * len(items)
            with self.lock: self.stats["dropped_pairs"] += sum(1 for x in result if x is None) if len(items) == 1 else 0
        with self.lock:
            self.done[key] = result
            if self.logf: self.logf.write(json.dumps({"key": key, "kind": "pair", "n": len(items), "out": result}, ensure_ascii=False) + "\n"); self.logf.flush()
        return result

    def _run(self, batches, fn):
        out = [None] * len(batches)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(fn, b): i for i, b in enumerate(batches)}
            for f in as_completed(futs): out[futs[f]] = f.result()
        return [x for b in out for x in b]

    def records(self, recs):
        """recs: list of field dicts -> list of rewritten dicts (None where dropped)."""
        items = [self._clean(r) for r in recs]
        batches = [items[i:i + self.batch] for i in range(0, len(items), self.batch)]
        res = self._run(batches, self._records_batch)
        self.stats["records_in"] += len(items); self.stats["records_out"] += sum(1 for x in res if x is not None)
        return res

    def pairs(self, pairs):
        """pairs: list of (dict, dict) -> list of (dict, dict) (None where dropped)."""
        items = [(self._clean(x), self._clean(y)) for x, y in pairs]
        batches = [items[i:i + self.pair_batch] for i in range(0, len(items), self.pair_batch)]
        res = self._run(batches, self._pairs_batch)
        self.stats["pairs_in"] += len(items); self.stats["pairs_out"] += sum(1 for x in res if x is not None)
        return res

    def report(self):
        return dict(self.stats)
