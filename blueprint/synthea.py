"""Build a controllable multi-partite ER benchmark from Synthea patients.

Synthea (MITRE) emits ONE clean canonical record per synthetic patient -- rich
PII but no duplicates, no multi-source structure, and no match labels. This
module turns that clean entity table into a blocking benchmark by adding the
three things Synthea does not provide:

  1. a parametric SOURCE model  -- each entity is placed in a subset of K
     synthetic custodians (`src1..srcK`);
  2. literature-grounded CORRUPTION -- each per-source copy is independently
     perturbed with the vendored GeCo corruptors (`blueprint.geco`), so the same
     entity is recorded differently by different sources (the matching
     challenge lives in the blocking fields, as it must);
  3. a free, exact GOLD STANDARD -- every record carries `cluster_id` = the
     originating patient, so true pairs / connectivity follow by grouping.

Output records use the same shape as the rest of the package
(`id`, `cluster_id`, `source_domain`, + attribute fields), so the blocking
families, retrieval blockers, multipartite approaches and metrics all apply
unchanged.

Corruption profiles are lifted from the Leipzig benchmarks (nothing invented):
  - ``moderate``: the North Carolina Voters / GeCo recipe -- 50% replicated in
    all sources uncorrupted, 25% corrupted in all sources, 25% corrupted in a
    subset; ~20% per-field corruption rate.
  - ``high``: the MusicBrainz / DAPO recipe -- 50% singletons, 50% duplicated
    across 2-5 sources, high corruption.

The ``within_source_dup_rate`` knob emits a second copy of an entity inside one
source -- deliberately violating the <=1-record-per-source assumption that the
multipartite A5 (constraint-satisfaction) approach relies on. It is the
"dirty-source" A5-breaker.
"""

import csv
import os
import random
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple, Union

import numpy as np

from blueprint import geco

PathLike = Union[str, Path]

# Attributes carried on every record; BLOCK_FIELDS are the discriminative
# identity fields a blocker should key on (STATE is dropped from blocking
# because the MA sample is single-state, so it carries no signal).
# SSN is deliberately excluded: it is a near-perfect unique identifier that would
# trivialize matching (the whole point is that no reliable shared patient key
# exists across providers -- the realistic patient-matching scenario, and the
# schema our NC-Voters corruption precedent uses).
ATTR_FIELDS: Tuple[str, ...] = (
    "first", "last", "birthdate", "gender", "address", "city", "state", "zip",
)
# Stable clinical-profile fields (active problem list / medications / allergies,
# joined with "; "). Appended so each record is a real patient record, not a bare
# identity card -- and, being the same person everywhere, they are matchable
# content (like a product's description) rather than per-visit noise.
CLINICAL_FIELDS: Tuple[str, ...] = ("problem_list", "medications", "allergies")
BLOCK_FIELDS: Tuple[str, ...] = (
    "first", "last", "birthdate", "address", "city", "zip",
    "problem_list", "medications", "allergies",
)


# --------------------------------------------------------------------------- #
# 1. Load Synthea patients.csv into clean canonical entities
# --------------------------------------------------------------------------- #

def _strip_digits(value: str) -> str:
    # Synthea appends uniqueness digits to names: "Gomez206" -> "Gomez".
    return re.sub(r"\d+", "", value or "").strip()


def load_patients(path: PathLike) -> List[Dict[str, Any]]:
    """Read Synthea ``patients.csv`` into canonical entity dicts."""
    patients: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            patients.append(
                {
                    "uuid": row["Id"],
                    "first": _strip_digits(row.get("FIRST", "")),
                    "last": _strip_digits(row.get("LAST", "")),
                    "maiden": _strip_digits(row.get("MAIDEN", "")),
                    "birthdate": (row.get("BIRTHDATE") or "").strip(),
                    "gender": (row.get("GENDER") or "").strip(),
                    "address": (row.get("ADDRESS") or "").strip(),
                    "city": (row.get("CITY") or "").strip(),
                    "state": (row.get("STATE") or "").strip(),
                    "zip": (row.get("ZIP") or "").strip(),
                }
            )
    return patients


def _entity_attrs(patient: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: patient.get(field, "") for field in ATTR_FIELDS}


# SNOMED display strings carry trailing qualifiers, e.g. "Anemia (disorder)".
_QUALIFIER_RE = re.compile(r"\s*\((disorder|finding|situation|procedure)\)\s*$", re.IGNORECASE)


def _strip_qualifier(text: str) -> str:
    return _QUALIFIER_RE.sub("", text or "").strip()


def _active_descriptions(path: PathLike, max_items: int = 6) -> Dict[str, List[str]]:
    """Per-patient distinct descriptions of ACTIVE rows (empty STOP) = the stable
    facts that follow a person across providers (chronic problems / ongoing meds /
    allergies), not one-off per-visit events."""
    out: Dict[str, List[str]] = defaultdict(list)
    seen: Dict[str, set] = defaultdict(set)
    with Path(path).open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("STOP") or "").strip():            # ongoing entries only
                continue
            uuid = row.get("PATIENT", "")
            desc = _strip_qualifier(row.get("DESCRIPTION", ""))
            if desc and desc not in seen[uuid] and len(out[uuid]) < max_items:
                seen[uuid].add(desc)
                out[uuid].append(desc)
    return dict(out)


def load_clinical(raw_dir: PathLike = "data/raw/synthea") -> Dict[str, Dict[str, List[str]]]:
    """Per-patient stable clinical profile keyed by patient UUID."""
    raw = Path(raw_dir)
    return {
        "conditions": _active_descriptions(raw / "conditions.csv", max_items=6),
        "medications": _active_descriptions(raw / "medications.csv", max_items=6),
        "allergies": _active_descriptions(raw / "allergies.csv", max_items=4),
    }


def load_patients_with_clinical(raw_dir: PathLike = "data/raw/synthea") -> List[Dict[str, Any]]:
    """Load canonical patients and attach their stable clinical profile lists."""
    patients = load_patients(Path(raw_dir) / "patients.csv")
    clinical = load_clinical(raw_dir)
    for patient in patients:
        uuid = patient["uuid"]
        patient["_conditions"] = clinical["conditions"].get(uuid, [])
        patient["_medications"] = clinical["medications"].get(uuid, [])
        patient["_allergies"] = clinical["allergies"].get(uuid, [])
    return patients


# --------------------------------------------------------------------------- #
# 2. Corruption -- vendored GeCo corruptors + a few PII field transforms
# --------------------------------------------------------------------------- #

_C = geco.corruptor
_BF = geco.basefunctions
_LK = geco.LOOKUP_DIR

_EDIT = _C.CorruptValueEdit(
    position_function=_C.position_mod_uniform,
    char_set_funct=_BF.char_set_ascii,
    insert_prob=0.25, delete_prob=0.25, substitute_prob=0.25, transpose_prob=0.25,
)
_KEYBOARD = _C.CorruptValueKeyboard(
    position_function=_C.position_mod_normal, row_prob=0.5, col_prob=0.5,
)
_OCR = _C.CorruptValueOCR(
    position_function=_C.position_mod_normal,
    lookup_file_name=os.path.join(_LK, "ocr-variations.csv"),
    has_header_line=False, unicode_encoding="utf-8",
)
_PHONETIC = _C.CorruptValuePhonetic(
    lookup_file_name=os.path.join(_LK, "phonetic-variations.csv"),
    has_header_line=False, unicode_encoding="utf-8",
)

_STREET_ABBR = {
    "Street": "St", "Avenue": "Ave", "Road": "Rd", "Drive": "Dr", "Lane": "Ln",
    "Boulevard": "Blvd", "Court": "Ct", "Place": "Pl", "Trail": "Trl",
    "Parkway": "Pkwy", "Circle": "Cir", "Terrace": "Ter", "Highway": "Hwy",
}
_UNIT_RE = re.compile(r"\s+(unit|suite|ste|apt|apartment|#)\s*\S+\s*$", re.IGNORECASE)


def _drop_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def _geco(corruptor, value: str) -> str:
    if not value or len(value) < 2:
        return value
    try:
        return corruptor.corrupt_value(value)
    except Exception:
        return value


def _corrupt_name(value: str) -> str:
    if not value:
        return value
    op = random.choice(["accent", "edit", "keyboard", "ocr", "phonetic"])
    if op == "accent":
        return _drop_accents(value)
    return _geco({"edit": _EDIT, "keyboard": _KEYBOARD, "ocr": _OCR, "phonetic": _PHONETIC}[op], value)


def _corrupt_address(value: str) -> str:
    if not value:
        return value
    op = random.choice(["abbrev", "drop_unit", "typo"])
    if op == "abbrev":
        out = value
        for full, ab in _STREET_ABBR.items():
            out = re.sub(rf"\b{full}\b", ab, out)
        return out
    if op == "drop_unit":
        return _UNIT_RE.sub("", value).strip() or value
    return _geco(random.choice([_KEYBOARD, _EDIT]), value)


def _corrupt_date(value: str) -> str:
    parts = value.split("-")
    if len(parts) != 3:
        return _geco(_KEYBOARD, value)
    y, m, d = parts
    op = random.choice(["us_slash", "eu_slash", "compact", "dash", "nopad", "swap"])
    if op == "us_slash":
        return f"{m}/{d}/{y}"
    if op == "eu_slash":
        return f"{d}/{m}/{y}"
    if op == "compact":
        return f"{y}{m}{d}"
    if op == "dash":
        return f"{m}-{d}-{y}"
    if op == "nopad":
        return f"{int(m)}/{int(d)}/{y}"
    return f"{y}-{d}-{m}"  # day/month transposition


def _corrupt_zip(value: str) -> str:
    if not value:
        return value
    op = random.choice(["typo", "truncate", "drop_zero"])
    if op == "typo":
        return _geco(_KEYBOARD, value)
    if op == "truncate" and len(value) > 3:
        return value[:-1]
    return value.lstrip("0") or value


def corrupt_attrs(attrs: Mapping[str, Any], rate: float, intensity: int = 1) -> Dict[str, Any]:
    """Independently corrupt each blocking field with probability ``rate``.

    ``intensity`` repeats the pass (the ``high`` profile stacks corruptions).
    Numeric fields (birthdate/zip) are routed through the keyboard corruptor +
    format transforms rather than GeCo's edit corruptor, which no-ops on
    pure-digit strings.
    """
    out = dict(attrs)
    for _ in range(max(1, intensity)):
        if random.random() < rate:
            out["first"] = _corrupt_name(out.get("first", ""))
        if random.random() < rate:
            out["last"] = _corrupt_name(out.get("last", ""))
        if random.random() < rate:
            out["birthdate"] = _corrupt_date(out.get("birthdate", ""))
        if random.random() < rate:
            out["address"] = _corrupt_address(out.get("address", ""))
        if random.random() < rate:
            out["city"] = _corrupt_name(out.get("city", ""))
        if random.random() < rate:
            out["zip"] = _corrupt_zip(out.get("zip", ""))
        if random.random() < rate * 0.15:           # gender rarely wrong
            out["gender"] = "" if random.random() < 0.5 else ("F" if out.get("gender") == "M" else "M")
        if random.random() < rate * 0.10:           # occasional dropped field
            out[random.choice(("zip", "address"))] = ""
    return out


# --------------------------------------------------------------------------- #
# 3. Parametric source model + dataset assembly
# --------------------------------------------------------------------------- #

# Source-span distribution measured directly from the Leipzig MusicBrainz-20K
# benchmark (records-per-entity == distinct-sources-per-entity there, i.e. NO
# within-source duplicates): 50% singletons, then halving 25/12.5/6.25, with the
# 5-source bucket absorbing the truncated tail.
MUSICBRAINZ_SPAN_DIST: Dict[int, float] = {1: 0.50, 2: 0.25, 3: 0.125, 4: 0.0625, 5: 0.0625}

# A profile is a per-field corruption rate, an intensity, and a list of buckets
# (fraction_of_entities, membership_spec, corrupt?) that together sum to 1.
# membership_spec: "all" | ("subset", lo) | ("subset", lo, hi) | ("dist", {size: prob}).
# corrupt is True/False, or "multi" = corrupt iff the entity spans >1 source.
PROFILES: Dict[str, dict] = {
    "musicbrainz": {                                # matches Leipzig MusicBrainz-20K structure
        # rate/clinical_keep tuned so true-duplicate token-Jaccard matches MB's
        # measured ~0.80 mean (MB's "high corruption" still leaves ~80% overlap).
        "corruption_rate": 0.15,
        "intensity": 1,
        "clinical_keep": 0.85,
        "buckets": [
            # one source-span distribution for every entity; singletons (the 50%
            # "originals") stay clean, multi-source entities are corrupted; no
            # within-source duplicates (use within_source_dup_rate>0 to add them).
            (1.00, ("dist", MUSICBRAINZ_SPAN_DIST), "multi"),
        ],
    },
    "moderate": {                                   # NC-Voters / GeCo recipe
        "corruption_rate": 0.20,
        "intensity": 1,
        "clinical_keep": 0.75,                      # each source records ~75% of items
        "buckets": [
            (0.50, "all", False),                   # clean copies in all sources
            (0.25, "all", True),                    # corrupted, in all sources
            (0.25, ("subset", 2), True),            # corrupted, in 2..K sources
        ],
    },
    "high": {                                       # heavy-corruption variant
        "corruption_rate": 0.60,
        "intensity": 2,
        "clinical_keep": 0.50,                      # sparser, noisier per-source profiles
        "buckets": [
            (0.50, ("subset", 1, 1), True),         # singletons (no duplicates)
            (0.50, ("subset", 2, 5), True),         # duplicated across 2-5 sources
        ],
    },
}


def _clinical_view(patient: Mapping[str, Any], corrupt: bool, keep_prob: float) -> Dict[str, str]:
    """One source's view of the patient's stable clinical profile.

    Clean copies see the full list (identical across sources -> still matchable);
    corrupted copies see an independently subsampled, reordered list -- modelling
    that each provider only recorded the conditions/meds/allergies it observed.
    The descriptions themselves are standardized codes, so they are NOT typo'd:
    the same condition is spelled the same everywhere (that shared, reliable
    content is exactly what makes the profile a matching signal).
    """
    out: Dict[str, str] = {}
    for field, key in (("problem_list", "_conditions"),
                       ("medications", "_medications"),
                       ("allergies", "_allergies")):
        items = list(patient.get(key, []))
        if corrupt and items:
            kept = [item for item in items if random.random() < keep_prob]
            random.shuffle(kept)
            items = kept
        out[field] = "; ".join(items)
    return out


def _resolve_membership(spec, sources: Sequence[str]) -> List[str]:
    k = len(sources)
    if spec == "all":
        return list(sources)
    if spec[0] == "dist":                           # explicit size -> probability
        sizes = list(spec[1])
        size = random.choices(sizes, weights=[spec[1][s] for s in sizes], k=1)[0]
        size = max(1, min(size, k))
        return random.sample(list(sources), size)
    lo = spec[1]                                     # ("subset", lo[, hi])
    hi = spec[2] if len(spec) > 2 else k
    lo = max(1, min(lo, k))
    hi = max(lo, min(hi, k))
    size = random.randint(lo, hi)
    return random.sample(list(sources), size)


def _pick_bucket(buckets):
    u = random.random()
    acc = 0.0
    for bucket in buckets:
        acc += bucket[0]
        if u <= acc:
            return bucket
    return buckets[-1]


def build_dataset(
    patients: Sequence[Mapping[str, Any]],
    *,
    k_sources: int = 5,
    profile: str = "moderate",
    within_source_dup_rate: float = 0.0,
    seed: int = 0,
) -> List[Dict[str, Any]]:
    """Materialize corrupted, multi-source records from canonical patients."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {sorted(PROFILES)}")
    random.seed(seed)
    np.random.seed(seed)
    cfg = PROFILES[profile]
    rate, intensity, buckets = cfg["corruption_rate"], cfg["intensity"], cfg["buckets"]
    clinical_keep = cfg.get("clinical_keep", 0.75)
    sources = [f"src{j}" for j in range(1, k_sources + 1)]

    records: List[Dict[str, Any]] = []
    rid = 0
    for cluster_id, patient in enumerate(patients):
        _, membership, corrupt = _pick_bucket(buckets)
        chosen = _resolve_membership(membership, sources)
        corrupt_flag = (len(chosen) > 1) if corrupt == "multi" else bool(corrupt)
        attrs = _entity_attrs(patient)
        for source in chosen:
            rec_attrs = corrupt_attrs(attrs, rate, intensity) if corrupt_flag else dict(attrs)
            clinical = _clinical_view(patient, corrupt_flag, clinical_keep)
            records.append({"id": rid, "cluster_id": cluster_id, "source_domain": source,
                            **rec_attrs, **clinical})
            rid += 1
            if within_source_dup_rate and random.random() < within_source_dup_rate:
                dup = corrupt_attrs(attrs, max(rate, 0.3), max(intensity, 1))
                dup_clin = _clinical_view(patient, True, min(clinical_keep, 0.6))
                records.append({"id": rid, "cluster_id": cluster_id, "source_domain": source,
                                **dup, **dup_clin})
                rid += 1
    return records


# --------------------------------------------------------------------------- #
# 4. Helpers: gold pairs + entity-disjoint splits
# --------------------------------------------------------------------------- #

def true_pairs(records: Sequence[Mapping[str, Any]]) -> Set[Tuple[Any, Any]]:
    by_cluster: Dict[Any, List[Any]] = {}
    for r in records:
        by_cluster.setdefault(r["cluster_id"], []).append(r["id"])
    pairs: Set[Tuple[Any, Any]] = set()
    for ids in by_cluster.values():
        ids = sorted(ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.add((ids[i], ids[j]))
    return pairs


def split_patients(
    patients: Sequence[Mapping[str, Any]],
    fracs: Tuple[float, float, float] = (0.6, 0.2, 0.2),
    seed: int = 0,
) -> Dict[str, List[Mapping[str, Any]]]:
    """Entity-disjoint train/valid/gs split over patients (per project protocol)."""
    order = list(patients)
    random.Random(seed).shuffle(order)
    n = len(order)
    n_train = int(fracs[0] * n)
    n_valid = int(fracs[1] * n)
    return {
        "train": order[:n_train],
        "valid": order[n_train:n_train + n_valid],
        "gs": order[n_train + n_valid:],
    }
