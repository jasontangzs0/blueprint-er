"""REP-ER prompts: one generic resolve prompt (every round), one generic key-design prompt.
No dataset-specific text anywhere; attribute names are substituted from the schema."""
from typing import Any, Dict, Sequence

RESOLVE_SYSTEM = """You are an entity resolution expert.

You are given ALL items of one candidate block. Group the items that denote the SAME real-world entity.

Rules: for items to be grouped, their identity-bearing attributes must refer to the same thing; surface variance in form is fine (spelling, accents, abbreviation, word order, punctuation, truncation, formatting, translation of generic words, missing values). Do NOT group items when a qualifier, edition, part, model, size, quantity, version or sub-type appears on one side only or differs. Agreement on a common value is weak evidence; agreement on a rare value is strong. Weigh numeric attributes (price, size, duration, count) asymmetrically: close agreement supports a merge, a large gap raises the bar and needs additional agreeing evidence. If one item states a model, part or product code that the other lacks or contradicts, keep them apart unless the rest of the record makes the identity certain. A wrong merge cannot be undone later; a missed merge can be repaired in a later round. When genuinely unsure, keep items apart.

For EACH group of two or more items, also write one canonical representative record consolidating its members: the fullest correct value of every attribute, in standardized form (normalize casing, punctuation and spacing; drop obvious junk).

Return ONLY JSON of the form {"clusters":[{"members":[<item ids>],"rep":{REP_FIELDS}}]}.
List ONLY groups with two or more members; every item id you do not list is a singleton. Use each item id at most once."""


def resolve_system(fields: Sequence[str]) -> str:
    rep = ",".join(f'"{f}":"..."' for f in fields)
    return RESOLVE_SYSTEM.replace("{REP_FIELDS}", rep)


def serialize_record(rid: Any, rec: Dict[str, Any], fields: Sequence[str]) -> str:
    parts = [f"[{rid}]"] + [f"{f}={rec[f]}" for f in fields if rec.get(f) not in (None, "")]
    return " | ".join(parts)


def serialize_unit(label: str, unit: Dict[str, Any], recs: Dict[Any, Dict[str, Any]], fields: Sequence[str], n_raw: int = 3) -> str:
    """Round >= 2 item: representative + up to n_raw raw members."""
    head = f"[{label}] " + " | ".join(f"{f}={unit[f]}" for f in fields if unit.get(f)) + f" | cluster_of={len(unit['members'])}"
    raws = ["      raw: " + " | ".join(f"{f}={recs[m][f]}" for f in fields if recs[m].get(f)) for m in sorted(unit["members"], key=str)[:n_raw]]
    return "\n".join([head] + raws)


# ---------------------------------------------------------------- anchored round-1 variant
ANCHOR_SYSTEM = """You are an entity resolution expert.

You are given one TARGET item and a numbered list of CANDIDATE items from its candidate block. Select every candidate that denotes the SAME real-world entity as the target.

Rules: for a candidate to be selected, its identity-bearing attributes must refer to the same thing as the target's; surface variance in form is fine (spelling, accents, abbreviation, word order, punctuation, truncation, formatting, translation of generic words, missing values). Do NOT select a candidate when a qualifier, edition, part, model, size, quantity, version or sub-type appears on one side only or differs. Agreement on a common value is weak evidence; agreement on a rare value is strong. Weigh numeric attributes (price, size, duration, count) asymmetrically: close agreement supports a match, a large gap raises the bar and needs additional agreeing evidence. If one item states a model, part or product code that the other lacks or contradicts, do not select unless the rest of the record makes the identity certain. A wrong match cannot be undone later; a missed match can be repaired in a later round. When genuinely unsure, do not select.

If you select at least one candidate, also write one canonical representative record consolidating the target and the selected candidates: the fullest correct value of every attribute, in standardized form (normalize casing, punctuation and spacing; drop obvious junk). If you select none, copy the target's values into the representative.

Return ONLY JSON of the form {"matches":[<candidate numbers>],"rep":{REP_FIELDS}}. Use each candidate number at most once; an empty list means no candidate matches."""


def anchor_system(fields: Sequence[str]) -> str:
    rep = ",".join(f'"{f}":"..."' for f in fields)
    return ANCHOR_SYSTEM.replace("{REP_FIELDS}", rep)


def serialize_anchor(owner: Any, cands: Sequence[Any], recs: Dict[Any, Dict[str, Any]], fields: Sequence[str]) -> str:
    """Round-1 anchored item: the block's owner record as the target, its neighbours numbered."""
    line = lambda r: " | ".join(f"{f}={recs[r][f]}" for f in fields if recs[r].get(f) not in (None, ""))
    return "\n".join(["Target: " + line(owner), "", "Candidates:"] + [f"[{i}] " + line(c) for i, c in enumerate(cands, 1)])
