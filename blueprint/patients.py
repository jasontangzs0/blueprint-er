"""Patient-linkage benchmark, version 2: Synthea patients plus a calibrated,
dated variation layer.

Synthea (unmodified) supplies one clean patient per entity with a life timeline:
birth date, a surname change at marriage for most women (the maiden name is kept),
the organisations each patient visited and when, and a stable clinical profile.
This module adds the three things the engine does not produce and that make real
patient linkage hard, each dial tied to a published rate (see ``RATES`` and
``docs/patient_benchmark.md``):

  1. dated life events        moves (Census mover hazard), nicknames, married
                              surnames on post-marriage records only;
  2. sources with their own   one record per organisation visited, registered at
     field sets and clerical  the first visit, carrying the name and address of
     error profiles           that date; SSN collected at some sources and blank or
                              a shared placeholder at measured rates; labs keep
                              initials, birth year and zip; pharmacies keep meds;
  3. hard negatives           siblings and twins at the same address, a parent with
                              the same name, planted namesakes sharing name and
                              birth date, placeholder SSNs shared across patients;
     and repeat registrations at the same source years later under a new MRN.

Every record carries ``cluster_id`` = the Synthea patient id (exact gold) and a
provenance entry naming every change applied, so later error analysis can say
which kind of variation a method failed on.

The 1,171-patient public sample lacks ``encounters.csv`` and ``organizations.csv``;
without them sources are synthesised (``sources_mode = "synthetic"``) and
registration dates are drawn at random. With a full export the sources are the
organisations actually visited (``sources_mode = "visits"``).

Output layout (``write_benchmark``) matches what ``scripts/reper.py`` and
``scripts/splink_generic.py`` read: ``records.csv`` + ``gold_clusters.txt``, plus
``records.jsonl``, ``provenance.jsonl`` and ``datasheet.json``.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from blueprint import names as N
from blueprint import synthea as S

PathLike = Union[str, Path]

# --------------------------------------------------------------------------- #
# Calibrated rates. Per-RECORD probabilities unless the key says otherwise.
# Per-pair discrepancy rates from the literature are halved where an error on
# either side produces the discrepancy. Anchors: Just et al. 2016 (398,939
# confirmed MPI duplicate pairs), Joffe 2014, Culbertson 2017, Deng 2023,
# Hagger-Johnson 2017, NCVR drift (arXiv 1712.09691), Census CPS, NCHS, Zech 2016.
# --------------------------------------------------------------------------- #
RATES: Dict[str, float] = {
    # middle name (pair rate 58% discrepancy; 83% of records lack one at UTHealth)
    "middle_blank": 0.18, "middle_initial": 0.06,
    # SSN, where the source collects it (pair rate 53%: mostly blank or placeholder).
    # Per-record defect ~0.31 in all: site-level missingness (mean ~0.22, range
    # 0.05-0.40 across sites) plus the clerical rates below.
    "ssn_site_missing_lo": 0.05, "ssn_site_missing_span": 0.35,
    "ssn_blank": 0.06, "ssn_placeholder": 0.07, "ssn_typo": 0.01,
    # first name (pair rate 22.6%: 53% 1-2 char slips, 31% blank, 7.8% swapped)
    # placeholder names ("Baby Girl <surname>") are ~1% of all records and concentrate in
    # registrations at birth (Joffe 2014); in a full export over half the in-window births are
    # registered at the birth hospital, so a 4% rate at those registrations lands near that share
    "first_typo": 0.08, "first_blank": 0.02, "newborn_placeholder": 0.04,
    "first_last_swap": 0.009, "first_middle_swap": 0.005,
    "nickname_patient": 0.04, "nickname_use": 0.50,
    # last name (pair rate 23.7%, incl. legitimate change)
    "last_typo": 0.05, "last_blank": 0.006, "accent_drop": 0.20, "married_hyphen": 0.10,
    # birth date (pair rate 6.2%: day 48%, year 40%, month 22%, swap 2.6%)
    "dob_day": 0.015, "dob_year": 0.0125, "dob_month": 0.007, "dob_swap": 0.0008, "dob_blank": 0.0002,
    # sex (pair rate 6%)
    "gender_blank": 0.005, "gender_flip": 0.025,
    # address / zip (postcode disagreement 53% in UK incl. moves; 2-5% missing)
    "address_missing": 0.03, "address_typo": 0.03, "zip_typo": 0.015, "zip_missing": 0.02,
    # dated life events (entity level)
    "move_hazard_per_year": 0.10, "move_start_age": 18,
    # hard negatives (entity level)
    "household_sibling": 0.06, "twin": 0.031, "parent_same_name": 0.005, "namesake": 0.01,
    # repeat registration at the same source (6-10% within-source duplicates)
    "rereg": 0.10,
    # share of patients born in the data window whose birth hospital holds a record dated
    # at birth (newborn placeholders, no SSN yet); in visits mode the birth encounter gives this
    "birth_registration": 0.15,
    # scale on each source type's probability of collecting SSN (0 = a no-SSN world)
    "ssn_collect_scale": 1.0,
    # share of patients with a middle name when names are redrawn (the sample export has none)
    "middle_name_share": 0.70,
    # --- source 2: information poverty --------------------------------------------------------
    # share of SSN-collecting sources that store only the last four digits (last-4 availability
    # median 80% across 20 organisations, Deng 2023)
    "ssn_last4_sources": 0.35,
    # --- source 3: population diversity (UK audit: 3-4x the error rate for non-Anglo names) ----
    # Hispanic patients carry two surnames; each source keeps them by its own convention
    "hispanic_two_surnames": 0.85,
    # share of Hispanic patients with an anglicised first name used by some sources; use per record
    "anglicised_patient": 0.25, "anglicised_use": 0.5,
    # share of sources that keep accents and n-tildes (most US systems strip them)
    "sources_keep_accents": 0.30,
    # first/last name order swapped for Asian/Pacific-group patients (family-name-first conventions)
    "api_name_order_swap": 0.06,
    # --- source 5: dirty structure ------------------------------------------------------------
    # overlays: a record carrying another person's address (70%) or birth date (30%); 0.1-0.2% of
    # records (Hagger-Johnson 2015)
    "overlay": 0.002,
    # derived thin sources (share of patients that appear there). Kept low: in real
    # linkage data most records have no duplicate (Songs 8%, Citations 12% of records;
    # 6-10% within one MPI; ~12% excess identities across an HIE).
    "registry_share": 0.03, "lab_share": 0.02, "pharmacy_share": 0.03, "claims_share": 0.03,
}

# How many of the chosen custodians hold a given person (synthetic sources mode only;
# with a full export this comes from who actually visited which organisation).
# Singleton-majority by default, so that 10-15% of records have a duplicate, as in the
# paper's other datasets. The old Leipzig-style half-and-half layout is kept as a variant.
SPAN_DISTS: Dict[str, Dict[int, float]] = {
    "singleton_majority": {1: 0.93, 2: 0.06, 3: 0.01},      # target: extra copies ~10% of records
    "hie_like": {1: 0.80, 2: 0.14, 3: 0.05, 4: 0.01},       # a denser exchange-like variant
    "leipzig": dict(S.MUSICBRAINZ_SPAN_DIST),               # the old half-and-half layout
}

PRESETS: Dict[str, Dict[str, Any]] = {
    # today's build, roughly: character noise only, no life events, no families
    "typos": {"life_events": False, "households": False, "profiles": False, "span_dist": "singleton_majority",
              "rates": {**{k: 0.0 for k in RATES},
                        "first_typo": 0.20, "last_typo": 0.20, "address_typo": 0.20, "zip_typo": 0.20,
                        "dob_day": 0.07, "dob_year": 0.07, "dob_month": 0.06, "ssn_collect_scale": 1.0,
                        "middle_name_share": 0.70,
                        "registry_share": 0.03, "lab_share": 0.0, "pharmacy_share": 0.03, "claims_share": 0.0}},
    # every dial at the table's default
    "calibrated": {"life_events": True, "households": True, "profiles": True, "span_dist": "singleton_majority",
                   "rates": dict(RATES)},
    # every structural dial at the top of its measured range: namesakes 5% (sites run 0.16-15%),
    # moves 12%/yr (Census upper), siblings 10%, same-name parent 2%; error rates unchanged
    "calibrated_upper": {"life_events": True, "households": True, "profiles": True, "span_dist": "singleton_majority",
                         "rates": {**RATES, "namesake": 0.05, "move_hazard_per_year": 0.12, "household_sibling": 0.10,
                                   "parent_same_name": 0.02, "nickname_patient": 0.06}},
    # harder still at the SAME duplicate density as calibrated_upper (more copies only make F1
    # easier): namesakes concentrated in the same city (regional name clustering: 2,488 "Maria
    # Garcia" records in one Houston system), records back to 1985 so more pairs straddle a move
    # or a marriage, fewer middle names on file. SSN stays: its shared placeholders are a real trap.
    "hardest": {"life_events": True, "households": True, "profiles": True, "span_dist": "singleton_majority",
                "window_start": "1985-01-01",
                "rates": {**RATES, "namesake": 0.05, "namesake_same_city": 0.6, "move_hazard_per_year": 0.12,
                          "household_sibling": 0.10, "parent_same_name": 0.02, "nickname_patient": 0.06,
                          "middle_name_share": 0.50}},
    # calibrated_upper with the duplicate DENSITY matched to the paper's other datasets
    # (Songs: extra copies 8.3% of records, 6.3% of entities duplicated; Citations: 12.3% / 9.1%).
    # Only the dials that add copies move: repeat registrations at the low end of the 6-10%
    # within-MPI range, derived thin sources at 1% of people each, birth registrations 5%;
    # the custodian count (CLI) sets the cross-source overlap. Every error rate is unchanged.
    "calibrated_upper_matched": {"life_events": True, "households": True, "profiles": True,
                                 "span_dist": "singleton_majority",
                                 "rates": {**RATES, "namesake": 0.05, "move_hazard_per_year": 0.12, "household_sibling": 0.10,
                                           "parent_same_name": 0.02, "nickname_patient": 0.06,
                                           "rereg": 0.06, "birth_registration": 0.02,
                                           "registry_share": 0.005, "lab_share": 0.005, "pharmacy_share": 0.005, "claims_share": 0.005}},
    # the same, in a world where no source shares SSN (common HIE and PPRL policy)
    "calibrated_nossn": {"life_events": True, "households": True, "profiles": True, "span_dist": "singleton_majority",
                         "rates": {**RATES, "ssn_collect_scale": 0.0}},
    # every dial at its upper measured bound
    "hard": {"life_events": True, "households": True, "profiles": True, "span_dist": "singleton_majority",
             "rates": {**RATES, "ssn_site_missing_span": 0.60, "ssn_blank": 0.12, "ssn_placeholder": 0.14,
                       "move_hazard_per_year": 0.15,
                       "nickname_patient": 0.08, "household_sibling": 0.10, "namesake": 0.02,
                       "rereg": 0.12, "first_typo": 0.10, "last_typo": 0.07, "middle_blank": 0.25,
                       "address_missing": 0.05, "lab_share": 0.10, "registry_share": 0.05, "pharmacy_share": 0.10,
                       "claims_share": 0.10, "birth_registration": 0.25}},
}

SSN_PLACEHOLDERS = ("999-99-9999", "111-11-1111", "123-45-6789")

# Nickname table (ours; GeCo ships none). English and Spanish forms common in a
# Massachusetts population. Looked up on the canonical first name.
NICKNAMES: Dict[str, Sequence[str]] = {
    "William": ("Bill", "Will"), "Robert": ("Bob", "Rob"), "Richard": ("Rick", "Dick"), "James": ("Jim",),
    "John": ("Jack",), "Charles": ("Chuck", "Charlie"), "Edward": ("Ed", "Ted"), "Thomas": ("Tom",),
    "Michael": ("Mike",), "Daniel": ("Dan",), "Joseph": ("Joe",), "Anthony": ("Tony",),
    "Christopher": ("Chris",), "Matthew": ("Matt",), "Andrew": ("Andy", "Drew"), "Nicholas": ("Nick",),
    "Jonathan": ("Jon",), "Benjamin": ("Ben",), "Samuel": ("Sam",), "Alexander": ("Alex",),
    "Theodore": ("Ted", "Theo"), "Henry": ("Hank",), "Leonard": ("Lenny", "Leo"), "Raymond": ("Ray",),
    "Walter": ("Walt",), "Lawrence": ("Larry",), "Gerald": ("Jerry",), "Donald": ("Don",),
    "Ronald": ("Ron",), "Kenneth": ("Ken",), "Timothy": ("Tim",), "Gregory": ("Greg",),
    "Jeffrey": ("Jeff",), "Steven": ("Steve",), "Peter": ("Pete",), "Philip": ("Phil",),
    "Frederick": ("Fred",), "Harold": ("Harry", "Hal"), "Albert": ("Al",), "Arthur": ("Art",),
    "Vincent": ("Vince",), "Nathaniel": ("Nate",), "Zachary": ("Zach",), "Patrick": ("Pat",),
    "Patricia": ("Pat", "Trish"), "Elizabeth": ("Liz", "Beth", "Betsy"), "Katherine": ("Kate", "Kathy"),
    "Catherine": ("Cathy", "Cate"), "Margaret": ("Peggy", "Meg", "Maggie"), "Jennifer": ("Jen",),
    "Susan": ("Sue",), "Deborah": ("Deb", "Debbie"), "Barbara": ("Barb",), "Rebecca": ("Becky",),
    "Stephanie": ("Steph",), "Victoria": ("Vicky",), "Jessica": ("Jess",), "Kimberly": ("Kim",),
    "Abigail": ("Abby",), "Isabella": ("Bella",), "Dorothy": ("Dot", "Dottie"), "Florence": ("Flo",),
    "Eleanor": ("Ellie", "Nora"), "Virginia": ("Ginny",), "Josephine": ("Jo", "Josie"), "Josefa": ("Josie",),
    "Shirley": ("Shirl",), "Mickey": ("Mick",), "Christine": ("Chris", "Tina"), "Alexandra": ("Alex",),
    "Gabriel": ("Gabe",), "Alejandro": ("Alex", "Ale"), "Guillermo": ("Memo",), "Ignacio": ("Nacho",),
    "Manuel": ("Manolo",), "Jesús": ("Chuy",), "Enrique": ("Quique",), "Antonio": ("Toño",),
    "Eduardo": ("Lalo",), "Fernando": ("Fer",), "Francisco": ("Paco", "Pancho"), "José": ("Pepe",),
    "Guadalupe": ("Lupe",), "Dolores": ("Lola",), "Concepción": ("Concha",), "Mercedes": ("Meche",),
    "Rosario": ("Charo",), "Teodoro": ("Teo",), "Eusebio": ("Chebo",), "Roberto": ("Beto",),
}

# Source types and the field profile distribution of each (Deng 2023, Culbertson 2017).
SOURCE_TYPES = ("hospital", "clinic", "registry", "lab", "pharmacy", "claims")
_TYPE_KEYWORDS = (
    ("hospital", ("HOSPITAL", "MEDICAL CENTER", "HEALTH SYSTEM", "INFIRMARY")),
    ("clinic", ("CLINIC", "HEALTH CENTER", "URGENT CARE", "PHYSICIANS", "PRIMARY CARE", "FAMILY", "PRACTICE", "ASSOCIATES", "PC")),
)
_TYPE_PROFILE: Dict[str, Dict[str, Any]] = {
    "hospital": {"collects_ssn": 0.90, "middle": (("full", 0.6), ("initial", 0.3), ("none", 0.1)),
                 "date_fmt": (("iso", 0.8), ("us", 0.2)), "addr_std": 0.6, "clinical": ("problem_list", "medications", "allergies"),
                 "clinical_keep": 0.80, "mrn": True},
    "clinic": {"collects_ssn": 0.60, "middle": (("none", 0.5), ("initial", 0.3), ("full", 0.2)),
               "date_fmt": (("us", 0.5), ("iso", 0.3), ("us_nopad", 0.2)), "addr_std": 0.5, "clinical": ("problem_list", "medications"),
               "clinical_keep": 0.70, "mrn": True},
    "registry": {"collects_ssn": 0.80, "middle": (("initial", 0.6), ("full", 0.3), ("none", 0.1)),
                 "date_fmt": (("iso", 1.0),), "addr_std": 0.7, "clinical": (), "clinical_keep": 0.0, "mrn": False},
    "lab": {"collects_ssn": 0.0, "middle": (("none", 1.0),), "date_fmt": (("year", 1.0),), "addr_std": 0.0,
            "clinical": (), "clinical_keep": 0.0, "mrn": False, "initials_only": True, "upper": True},
    "pharmacy": {"collects_ssn": 0.05, "middle": (("none", 1.0),), "date_fmt": (("iso_nopad", 0.6), ("iso", 0.4)),
                 "addr_std": 0.3, "clinical": ("medications",), "clinical_keep": 0.9, "mrn": False},
    # an insurer's claims extract: full name, birth year, sex, zip; nothing else
    "claims": {"collects_ssn": 0.0, "middle": (("none", 1.0),), "date_fmt": (("year", 1.0),), "addr_std": 0.0,
               "clinical": (), "clinical_keep": 0.0, "mrn": False, "zip_only": True},
}

IDENTITY_FIELDS: Tuple[str, ...] = ("first", "middle", "last", "birthdate", "gender", "ssn", "address", "city", "state", "zip")
CLINICAL_FIELDS: Tuple[str, ...] = S.CLINICAL_FIELDS
# What a matcher is shown. Patient matching runs on demographics: a master patient index, an
# exchange query or a PPRL protocol never sees the problem list at matching time. The clinical
# fields stay in the files as an optional extension (``--fields`` decides).
MATCH_FIELDS: Tuple[str, ...] = ("first", "middle", "last", "birthdate", "gender", "ssn", "address", "city", "zip")
OUTPUT_FIELDS: Tuple[str, ...] = ("id", "cluster_id", "source", "source_type", "registered", "mrn") + IDENTITY_FIELDS + CLINICAL_FIELDS
HISPANIC_SURNAME_CONVENTIONS: Tuple[Tuple[str, float], ...] = (
    ("first_only", 0.45), ("both", 0.25), ("hyphen", 0.15), ("second_only", 0.10), ("swapped", 0.05))
SIX_KEY_FIELDS: Tuple[str, ...] = ("first", "middle", "last", "birthdate", "gender", "ssn")  # Just et al. 2016


# --------------------------------------------------------------------------- #
# 1. Loading. Column names are matched case-insensitively (older exports are
#    upper-case, the current data dictionary is title-case).
# --------------------------------------------------------------------------- #

def _rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}


def _date(text: str) -> Optional[dt.date]:
    text = (text or "")[:10]
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _active_descriptions(path: Path, max_items: int) -> Dict[str, List[str]]:
    """Per patient, the distinct descriptions of rows with no STOP date (ongoing
    problems, medications, allergies): the stable facts that follow a person."""
    out: Dict[str, List[str]] = defaultdict(list)
    if not path.exists():
        return {}
    for row in _rows(path):
        if row.get("STOP", ""):
            continue
        uuid, desc = row.get("PATIENT", ""), S._strip_qualifier(row.get("DESCRIPTION", ""))
        if desc and desc not in out[uuid] and len(out[uuid]) < max_items:
            out[uuid].append(desc)
    return dict(out)


def load_patients(raw_dir: PathLike, names: str = "census", seed: int = 0,
                  middle_name_share: float = 0.70, hispanic_two_surnames: float = 0.85) -> List[Dict[str, Any]]:
    """Canonical patients with first/middle/last/maiden, SSN, dates and the stable
    clinical profile. Column names are matched case-insensitively.

    ``names="census"`` redraws first, middle, last and maiden names from the public
    frequency tables (see ``blueprint.names``) so namesakes occur at real rates;
    ``names="synthea"`` keeps the engine's nearly unique names."""
    raw = Path(raw_dir)
    clinical = {"_conditions": _active_descriptions(raw / "conditions.csv", 6),
                "_medications": _active_descriptions(raw / "medications.csv", 6),
                "_allergies": _active_descriptions(raw / "allergies.csv", 4)}
    tabs = N.tables() if names == "census" else None
    nrng = random.Random(seed * 7919 + 1)
    out: List[Dict[str, Any]] = []
    for row in _rows(raw / "patients.csv"):
        p = {"last": S._strip_digits(row.get("LAST", "")), "maiden": S._strip_digits(row.get("MAIDEN", "")),
             "gender": row.get("GENDER", ""), "address": row.get("ADDRESS", ""), "city": row.get("CITY", ""),
             "state": row.get("STATE", ""), "zip": row.get("ZIP", ""),
             **{k: v.get(row["ID"], []) for k, v in clinical.items()}}
        first = S._strip_digits(row.get("FIRST", ""))
        middle = S._strip_digits(row.get("MIDDLE", ""))
        if not middle and len(first.split()) > 1:            # older exports fold the middle name into FIRST
            first, middle = first.split()[0], " ".join(first.split()[1:])
        birth = _date(row.get("BIRTHDATE", ""))
        if birth is None:
            continue
        last, maiden = p["last"], p["maiden"]
        group = N.group_of(row.get("RACE", ""), row.get("ETHNICITY", ""))
        surname2 = ""
        if tabs is not None:
            sex = p["gender"]
            first = N.accented(tabs.first_name(sex, birth.year, nrng) or first)
            middle = (N.accented(tabs.first_name(sex, birth.year, nrng)) if nrng.random() < middle_name_share else "")
            if middle == first:
                middle = ""
            last = N.accented(tabs.surname_for(row.get("RACE", ""), row.get("ETHNICITY", ""), nrng) or last)
            maiden = (N.accented(tabs.surname_for(row.get("RACE", ""), row.get("ETHNICITY", ""), nrng)) or maiden) if p["maiden"] else ""
            if maiden == last:
                maiden = ""
            if group == "hispanic" and nrng.random() < hispanic_two_surnames:
                surname2 = N.accented(tabs.surname_for(row.get("RACE", ""), row.get("ETHNICITY", ""), nrng))
                if surname2 == last:
                    surname2 = ""
        out.append({
            "uuid": row["ID"], "first": first, "middle": middle, "last": last, "maiden": maiden,
            "group": group, "surname2": surname2, "alt_first": N.ANGLICISED.get(first, "") if group == "hispanic" else "",
            "suffix": row.get("SUFFIX", ""), "marital": row.get("MARITAL", ""), "gender": p["gender"],
            "birthdate": birth, "deathdate": _date(row.get("DEATHDATE", "")), "ssn": row.get("SSN", ""),
            "address": p["address"], "city": p["city"], "state": p["state"], "zip": p["zip"],
            "_conditions": p["_conditions"], "_medications": p["_medications"], "_allergies": p["_allergies"],
            "role": "patient",
        })
    return out


def load_visits(raw_dir: PathLike) -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], Dict[str, Dict[str, str]]]:
    """Per patient: organisation -> {first, last, n}. Per organisation: name/type.
    Returns empty dicts when the export has no encounter or organisation table."""
    raw = Path(raw_dir)
    enc, org = raw / "encounters.csv", raw / "organizations.csv"
    if not enc.exists() or not org.exists():
        return {}, {}
    orgs: Dict[str, Dict[str, str]] = {}
    for row in _rows(org):
        name = row.get("NAME", "")
        kind = "clinic"
        upper = name.upper()
        for t, keys in _TYPE_KEYWORDS:
            if any(k in upper for k in keys):
                kind = t
                break
        orgs[row["ID"]] = {"name": name, "type": kind, "city": row.get("CITY", "")}
    visits: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for row in _rows(enc):
        d = _date(row.get("START", ""))
        o = row.get("ORGANIZATION", "")
        if d is None or not o:
            continue
        v = visits[row["PATIENT"]].setdefault(o, {"first": d, "last": d, "n": 0})
        v["first"], v["last"], v["n"] = min(v["first"], d), max(v["last"], d), v["n"] + 1
    return dict(visits), orgs


# --------------------------------------------------------------------------- #
# 2. Timeline: surname and address periods per entity
# --------------------------------------------------------------------------- #

def _add_years(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:                                        # 29 Feb
        return d.replace(year=d.year + years, day=28)


def build_timeline(p: Mapping[str, Any], rng: random.Random, rates: Mapping[str, float],
                   address_pool: Sequence[Tuple[str, str, str, str]], life_events: bool,
                   horizon: dt.date) -> Dict[str, Any]:
    """Surname periods (engine: marriage at 28 for women with a maiden name) and
    address periods (ours: Census mover hazard, address borrowed from another
    patient so formats stay real)."""
    birth: dt.date = p["birthdate"]
    end = min(horizon, p["deathdate"] or horizon)
    surnames: List[Tuple[dt.date, str]] = [(birth, p["maiden"] or p["last"])]
    if life_events and p["maiden"] and p["maiden"] != p["last"]:
        marriage = _add_years(birth, 28) + dt.timedelta(days=rng.randint(0, 364))
        if marriage < end:
            surnames.append((marriage, p["last"]))
    else:
        surnames = [(birth, p["last"])]
    addresses: List[Tuple[dt.date, Tuple[str, str, str, str]]] = [(birth, (p["address"], p["city"], p["state"], p["zip"]))]
    if life_events and address_pool:
        year = _add_years(birth, int(rates["move_start_age"]))
        while year < end:
            if rng.random() < rates["move_hazard_per_year"]:
                when = year + dt.timedelta(days=rng.randint(0, 364))
                if when < end:
                    addresses.append((when, rng.choice(address_pool)))
            year = _add_years(year, 1)
    nickname = ""
    if life_events and rng.random() < rates["nickname_patient"]:
        opts = NICKNAMES.get(p["first"])
        if opts:
            nickname = rng.choice(opts)
    anglicised = bool(p.get("alt_first")) and life_events and rng.random() < rates.get("anglicised_patient", 0.0)
    return {"surnames": surnames, "addresses": addresses, "nickname": nickname, "anglicised": anglicised, "end": end}


def _at(periods: Sequence[Tuple[dt.date, Any]], when: dt.date) -> Tuple[Any, int]:
    value, idx = periods[0][1], 0
    for i, (start, v) in enumerate(periods):
        if start <= when:
            value, idx = v, i
    return value, idx


# --------------------------------------------------------------------------- #
# 3. Sources: from visits when the export has them, else synthesised
# --------------------------------------------------------------------------- #

def _make_profile(kind: str, rng: random.Random, profiles: bool, rates: Mapping[str, float] = RATES) -> Dict[str, Any]:
    base = _TYPE_PROFILE[kind]
    pick = lambda dist: rng.choices([v for v, _ in dist], weights=[w for _, w in dist], k=1)[0]
    if not profiles:                                          # "typos" preset: one full schema everywhere
        return {"type": kind, "collects_ssn": True, "ssn_missing": 0.0, "middle": "full", "date_fmt": "iso",
                "addr_std": False, "keep_unit": True, "clinical": tuple(CLINICAL_FIELDS), "clinical_keep": 0.75,
                "mrn": base["mrn"], "initials_only": False, "upper": False, "zip_only": False,
                "ssn_format": "full", "keeps_accents": True, "hispanic_surname": "both"}
    collects = rng.random() < base["collects_ssn"] * rates.get("ssn_collect_scale", 1.0)
    return {
        "type": kind, "collects_ssn": collects, "zip_only": base.get("zip_only", False),
        "ssn_format": ("last4" if collects and rng.random() < rates.get("ssn_last4_sources", 0.0) else "full"),
        "keeps_accents": rng.random() < rates.get("sources_keep_accents", 0.0),
        "hispanic_surname": pick(HISPANIC_SURNAME_CONVENTIONS),
        "ssn_missing": (rates["ssn_site_missing_lo"] + rates["ssn_site_missing_span"] * rng.betavariate(2, 2)) if collects else 1.0,
        "middle": pick(base["middle"]), "date_fmt": pick(base["date_fmt"]),
        "addr_std": rng.random() < base["addr_std"], "keep_unit": rng.random() < 0.7,
        "clinical": tuple(base["clinical"]), "clinical_keep": base["clinical_keep"], "mrn": base["mrn"],
        "initials_only": base.get("initials_only", False), "upper": base.get("upper", False),
    }


def assign_sources(patients: Sequence[Mapping[str, Any]], visits: Mapping[str, Mapping[str, Mapping[str, Any]]],
                   orgs: Mapping[str, Mapping[str, str]], rng: random.Random, rates: Mapping[str, float],
                   profiles: bool, max_sources: int, n_synthetic_orgs: int, horizon: dt.date,
                   span_dist: Mapping[int, float] = SPAN_DISTS["singleton_majority"], n_custodians: int = 8,
                   window_start: dt.date = dt.date(1995, 1, 1), n_hospital_custodians: int = 0,
                   spread_cities: bool = False, window_years: float = 0.0, coverage: float = 1.0,
                   secondary_share: float = 1.0, go_live_years: float = 0.0,
                   ) -> Tuple[Dict[str, List[Tuple[str, dt.date, dt.date]]], Dict[str, Dict[str, Any]], str]:
    """Per entity uuid: list of (source id, first registration, last visit).
    Also the profile of every source and the mode used."""
    source_profiles: Dict[str, Dict[str, Any]] = {}
    out: Dict[str, List[Tuple[str, dt.date, dt.date]]] = {}
    if visits:
        mode = "visits"
        # Source 4 (scale): the benchmark links a handful of CUSTODIANS, not every organisation
        # anyone ever visited. A patient appears in a custodian's file only if they visited it, so
        # overlap comes from geography and most people stay singletons, as in real linkage data.
        patients_per_org: Counter = Counter()
        for v in visits.values():
            for oid in v:
                patients_per_org[oid] += 1
        ranked = [oid for oid, _ in patients_per_org.most_common() if oid in orgs]
        if spread_cities:
            # one custodian per city, largest first: custodians in different towns share fewer
            # patients, which is how real linkage data gets its singleton-majority structure
            seen, spread = set(), []
            for o in ranked:
                city = orgs[o].get("city", "")
                if city not in seen:
                    seen.add(city)
                    spread.append(o)
            ranked = spread
        if n_custodians:
            # reserve slots for the largest hospitals, since the biggest organisations by
            # patient count are urgent-care chains and a hospital is the natural record holder
            hosp = [o for o in ranked if orgs[o]["type"] == "hospital"][:n_hospital_custodians]
            rest = [o for o in ranked if o not in hosp][:max(0, n_custodians - len(hosp))]
            custodians = hosp + rest
        else:
            custodians = ranked
        for oid in custodians:
            meta = orgs[oid]
            prof = {**_make_profile(meta["type"], rng, profiles, rates), "name": meta["name"]}
            if window_years:
                # a real extract covers a date range ("encounters 2012-2018"); two custodians hold
                # the same person only if they saw them inside both windows
                lo = window_start + dt.timedelta(days=rng.randint(0, max(0, (horizon - window_start).days - int(window_years * 365.25))))
                prof["window"] = (lo, lo + dt.timedelta(days=int(window_years * 365.25)))
            elif go_live_years:
                # stream variant: each custodian's system went live at some point in the first
                # go_live_years of the window and holds a patient from their first encounter after
                # go-live until the horizon, so registration dates are real arrival times
                lo = window_start + dt.timedelta(days=rng.randint(0, int(go_live_years * 365.25)))
                prof["window"] = (lo, horizon)
            source_profiles[oid] = prof
        for p in patients:
            v = visits.get(p["uuid"], {})
            held = []
            if go_live_years and p["birthdate"] > horizon:
                out[p["uuid"]] = []                                # born after the horizon: not in any extract
                continue
            for oid, d in v.items():
                if oid not in source_profiles:
                    continue
                win = source_profiles[oid].get("window")
                if win:
                    lo, hi = win
                    if d["last"] < lo or d["first"] > hi:          # no visit inside the extract window
                        continue
                    if go_live_years and (d["first"] < lo or d["last"] > hi):
                        # first and last encounter INSIDE the window, not the window edges: the
                        # patient's n visits spread over their span, so take the earliest and latest
                        # of the k that fall inside (a clip at the edge would pile registrations on
                        # go-live day and re-registrations on the horizon)
                        a_, b_ = max(d["first"], lo), min(d["last"], hi)
                        span = max(1, (d["last"] - d["first"]).days); overlap = max(0, (b_ - a_).days)
                        k = max(1, round(d["n"] * overlap / span))
                        us = sorted(rng.random() for _ in range(k))
                        first = a_ + dt.timedelta(days=int(overlap * us[0])) if d["first"] < lo else d["first"]
                        last = a_ + dt.timedelta(days=int(overlap * us[-1])) if d["last"] > hi else d["last"]
                        d = {"first": first, "last": max(first, last), "n": d["n"]}
                    else:
                        d = {"first": max(d["first"], lo), "last": min(d["last"], hi), "n": d["n"]}
                held.append((oid, d))
            if coverage < 1.0:
                # an extract holds a share of an organisation's patients (a department, a payer,
                # a consent list); overlap between two extracts falls with the square of the share
                held = [(oid, d) for oid, d in held if rng.random() < coverage]
            held.sort(key=lambda kv: -kv[1]["n"])
            if secondary_share < 1.0 and held:
                # Synthea patients see many organisations over a lifetime, so any two large
                # extracts overlap heavily. A patient's PRIMARY organisation (most visits) always
                # holds them; a secondary one holds them with this probability, which sets the
                # duplicate density directly (a one-off ER visit that made it into the file)
                held = held[:1] + [(oid, d) for oid, d in held[1:] if rng.random() < secondary_share]
            top = held[:max_sources]
            out[p["uuid"]] = [(oid, d["first"], d["last"]) for oid, d in top]
    else:
        mode = "synthetic"
        kinds = [("hospital" if i % 3 == 0 else "clinic") for i in range(n_synthetic_orgs)]
        for i, kind in enumerate(kinds):
            sid = f"org{i + 1}"
            source_profiles[sid] = {**_make_profile(kind, rng, profiles, rates), "name": f"{kind.title()} {i + 1}"}
        sids = list(source_profiles)
        hospitals = [s for s in sids if source_profiles[s]["type"] == "hospital"]
        sizes = list(span_dist)
        for p in patients:
            n = min(rng.choices(sizes, weights=[span_dist[s] for s in sizes], k=1)[0], len(sids), max_sources)
            start = max(p["birthdate"], window_start)
            end = min(horizon, p["deathdate"] or horizon)
            chosen = []
            for sid in rng.sample(sids, n):
                if end <= start:
                    first = last = start
                else:
                    first = start + dt.timedelta(days=rng.randint(0, (end - start).days))
                    last = first + dt.timedelta(days=rng.randint(0, max(0, (end - first).days)))
                chosen.append((sid, first, last))
            # the birth hospital registers newborns at birth (placeholder names, no SSN yet)
            if hospitals and p["birthdate"] >= window_start and rng.random() < rates.get("birth_registration", 0.0):
                h = rng.choice(hospitals)
                chosen = [c for c in chosen if c[0] != h]
                chosen.insert(0, (h, p["birthdate"], max(p["birthdate"], min(end, p["birthdate"] + dt.timedelta(days=rng.randint(0, 3000))))))
            out[p["uuid"]] = chosen[:max_sources]
    # derived thin sources shared by everyone: a state registry, a lab, a pharmacy
    for sid, kind in (("registry", "registry"), ("lab", "lab"), ("pharmacy", "pharmacy"), ("claims", "claims")):
        source_profiles[sid] = {**_make_profile(kind, rng, profiles, rates), "name": {"registry": "MA immunization registry",
                                "lab": "Reference laboratory", "pharmacy": "Retail pharmacy",
                                "claims": "Insurer claims extract"}[kind]}
    for p in patients:
        own = out.setdefault(p["uuid"], [])
        anchor_dates = [d for _, d, _ in own] or [max(p["birthdate"], window_start)]
        end = min(horizon, p["deathdate"] or horizon)
        if go_live_years and (end < window_start or p["birthdate"] > horizon):
            continue                                               # died before the window or born after it
        for sid, share, cond in (("registry", rates["registry_share"], True), ("lab", rates["lab_share"], True),
                                 ("pharmacy", rates["pharmacy_share"], bool(p["_medications"])),
                                 ("claims", rates.get("claims_share", 0.0), True)):
            if cond and rng.random() < share:
                base = rng.choice(anchor_dates)
                when = min(end, base + dt.timedelta(days=rng.randint(0, 730)))
                own.append((sid, when, when))
    return out, source_profiles, mode


# --------------------------------------------------------------------------- #
# 4. One record = entity x source x date, through the profile and the errors
# --------------------------------------------------------------------------- #

def _fmt_date(d: Optional[dt.date], fmt: str) -> str:
    if d is None:
        return ""
    if fmt == "iso":
        return d.isoformat()
    if fmt == "iso_nopad":
        return f"{d.year}-{d.month}-{d.day}"
    if fmt == "us":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if fmt == "us_nopad":
        return f"{d.month}/{d.day}/{d.year}"
    if fmt == "year":
        return str(d.year)
    return d.isoformat()


def _std_address(addr: str, keep_unit: bool) -> str:
    out = addr
    for full, ab in S._STREET_ABBR.items():
        out = re.sub(rf"\b{full}\b", ab, out)
    if not keep_unit:
        out = S._UNIT_RE.sub("", out).strip() or out
    return out


def _typo(value: str, rng: random.Random) -> str:
    # GeCo corruptors (edit / keyboard / OCR / phonetic) or an accent drop
    random.setstate(rng.getstate())
    out = S._corrupt_name(value)
    rng.setstate(random.getstate())
    return out


def _ssn_typo(ssn: str, rng: random.Random) -> str:
    digits = [c for c in ssn if c.isdigit()]
    if len(digits) != 9:
        return ssn
    for _ in range(rng.choice((1, 2))):
        i = rng.randrange(9)
        digits[i] = str((int(digits[i]) + rng.randint(1, 9)) % 10)
    return f"{''.join(digits[:3])}-{''.join(digits[3:5])}-{''.join(digits[5:])}"


def _perturb_dob(d: dt.date, kind: str, rng: random.Random) -> dt.date:
    try:
        if kind == "day":
            return d.replace(day=max(1, min(28, d.day + rng.choice((-2, -1, 1, 2, 9, 10, -10)))))
        if kind == "month":
            return d.replace(month=max(1, min(12, d.month + rng.choice((-1, 1)))))
        if kind == "year":
            return d.replace(year=d.year + rng.choice((-10, -1, 1, 10)))
    except ValueError:
        return d
    return d


def make_record(entity: Mapping[str, Any], timeline: Mapping[str, Any], source_id: str,
                profile: Mapping[str, Any], when: dt.date, rng: random.Random, rates: Mapping[str, float],
                life_events: bool) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Returns (record fields, provenance)."""
    applied: List[str] = []
    surname, s_idx = _at(timeline["surnames"], when) if life_events else (entity["last"], 0)
    (address, city, state, zipc), a_idx = _at(timeline["addresses"], when) if life_events else \
        ((entity["address"], entity["city"], entity["state"], entity["zip"]), 0)
    first, middle, last = entity["first"], entity["middle"], surname
    dob: Optional[dt.date] = entity["birthdate"]
    gender = entity["gender"]
    ssn = entity["ssn"]
    age_days = (when - entity["birthdate"]).days

    # --- source profile (schema-level, no clerical error yet) ---
    if life_events and timeline.get("nickname") and rng.random() < rates["nickname_use"]:
        first = timeline["nickname"]; applied.append("first:nickname")
    elif entity.get("alt_first") and timeline.get("anglicised") and rng.random() < rates.get("anglicised_use", 0.0):
        first = entity["alt_first"]; applied.append("first:anglicised")
    # Hispanic double surnames: the source's convention decides which part it keeps
    s2 = entity.get("surname2", "")
    if s2 and last == entity["last"]:                         # the paternal surname period (not a married surname)
        conv = profile.get("hispanic_surname", "both")
        last = {"first_only": last, "both": f"{last} {s2}", "hyphen": f"{last}-{s2}",
                "second_only": s2, "swapped": f"{s2} {last}"}[conv]
        if conv != "first_only":
            applied.append(f"last:hispanic_{conv}")
    if life_events and s_idx > 0 and entity["maiden"] and rng.random() < rates["married_hyphen"]:
        last = f"{entity['maiden']}-{surname}"; applied.append("last:married_hyphen")
    if entity.get("group") == "api" and first and last and rng.random() < rates.get("api_name_order_swap", 0.0):
        first, last = last, first; applied.append("name:order_swap")
    if profile["middle"] == "none":
        middle = ""
    elif profile["middle"] == "initial" and middle:
        middle = middle[0] + "."
    if not profile["collects_ssn"]:
        ssn = ""
    elif rng.random() < profile["ssn_missing"]:
        ssn = ""; applied.append("ssn:site_missing")
    if profile["addr_std"]:
        address = _std_address(address, profile["keep_unit"])
    if profile.get("initials_only"):
        first, middle = (first[:1] if first else ""), ""
        address, city, state = "", "", ""
        applied.append("profile:initials_only")
    if profile.get("zip_only"):
        address, city, state, middle = "", "", "", ""
        applied.append("profile:zip_only")
    if profile.get("upper"):
        first, last = first.upper(), last.upper()
    if not profile.get("keeps_accents", True):
        f2, l2, m2 = S._drop_accents(first), S._drop_accents(last), S._drop_accents(middle)
        if (f2, l2, m2) != (first, last, middle):
            first, last, middle = f2, l2, m2; applied.append("profile:accents_stripped")
    if ssn and profile.get("ssn_format") == "last4":
        ssn = "xxx-xx-" + ssn[-4:]; applied.append("profile:ssn_last4")

    # --- clerical errors at the calibrated per-record rates ---
    r = rng.random
    if middle and r() < rates["middle_blank"]:
        middle = ""; applied.append("middle:blank")
    elif middle and len(middle) > 2 and r() < rates["middle_initial"]:
        middle = middle[0] + "."; applied.append("middle:initial")
    if ssn:
        u = r()
        last4 = ssn.startswith("xxx-xx-")
        if u < rates["ssn_blank"]:
            ssn = ""; applied.append("ssn:blank")
        elif u < rates["ssn_blank"] + rates["ssn_placeholder"]:
            ssn = rng.choice(SSN_PLACEHOLDERS); applied.append("ssn:placeholder")
            if last4:
                ssn = "xxx-xx-" + ssn[-4:]
        elif u < rates["ssn_blank"] + rates["ssn_placeholder"] + rates["ssn_typo"]:
            if last4:
                d = list(ssn[-4:]); i = rng.randrange(4); d[i] = str((int(d[i]) + rng.randint(1, 9)) % 10)
                ssn = "xxx-xx-" + "".join(d)
            else:
                ssn = _ssn_typo(ssn, rng)
            applied.append("ssn:typo")
    if first and not profile.get("initials_only"):
        if age_days < 365 and r() < rates["newborn_placeholder"]:
            first = "Baby Girl" if gender == "F" else "Baby Boy"; applied.append("first:newborn_placeholder")
        elif r() < rates["first_typo"]:
            first = _typo(first, rng); applied.append("first:typo")
        elif r() < rates["first_blank"]:
            first = ""; applied.append("first:blank")
    if first and last and r() < rates["first_last_swap"]:
        first, last = last, first; applied.append("name:first_last_swap")
    elif first and middle and len(middle) > 2 and r() < rates["first_middle_swap"]:
        first, middle = middle, first; applied.append("name:first_middle_swap")
    if last:
        if r() < rates["last_typo"]:
            last = _typo(last, rng); applied.append("last:typo")
        elif r() < rates["last_blank"]:
            last = ""; applied.append("last:blank")
        elif r() < rates["accent_drop"] and S._drop_accents(last) != last:
            last = S._drop_accents(last); applied.append("last:accent_drop")
    if first and r() < rates["accent_drop"] and S._drop_accents(first) != first:
        first = S._drop_accents(first); applied.append("first:accent_drop")
    if dob is not None:
        u = r()
        thresholds = (("dob_day", "day"), ("dob_year", "year"), ("dob_month", "month"))
        acc = 0.0
        done = False
        for key, kind in thresholds:
            acc += rates[key]
            if u < acc:
                dob = _perturb_dob(dob, kind, rng); applied.append(f"dob:{kind}"); done = True
                break
        if not done and u < acc + rates["dob_blank"]:
            dob = None; applied.append("dob:blank")
    dob_text = _fmt_date(dob, profile["date_fmt"])
    if dob is not None and dob.day <= 12 and profile["date_fmt"] in ("us", "us_nopad") and r() < rates["dob_swap"]:
        dob_text = _fmt_date(dob.replace(month=dob.day, day=dob.month), profile["date_fmt"]); applied.append("dob:swap")
    if gender:
        u = r()
        if u < rates["gender_blank"]:
            gender = ""; applied.append("gender:blank")
        elif u < rates["gender_blank"] + rates["gender_flip"]:
            gender = "F" if gender == "M" else "M"; applied.append("gender:flip")
    if address:
        u = r()
        if u < rates["address_missing"]:
            address = ""; applied.append("address:missing")
        elif u < rates["address_missing"] + rates["address_typo"]:
            random.setstate(rng.getstate()); address = S._corrupt_address(address); rng.setstate(random.getstate())
            applied.append("address:typo")
    if zipc:
        u = r()
        if u < rates["zip_missing"]:
            zipc = ""; applied.append("zip:missing")
        elif u < rates["zip_missing"] + rates["zip_typo"]:
            random.setstate(rng.getstate()); zipc = S._corrupt_zip(zipc); rng.setstate(random.getstate())
            applied.append("zip:typo")

    # --- clinical snapshot kept by this source ---
    clinical = {f: "" for f in CLINICAL_FIELDS}
    for field, key in (("problem_list", "_conditions"), ("medications", "_medications"), ("allergies", "_allergies")):
        if field in profile["clinical"]:
            items = [x for x in entity.get(key, []) if rng.random() < profile["clinical_keep"]]
            rng.shuffle(items)
            clinical[field] = "; ".join(items)

    rec = {"first": first, "middle": middle, "last": last, "birthdate": dob_text, "gender": gender, "ssn": ssn,
           "address": address, "city": city, "state": state, "zip": zipc, **clinical,
           "mrn": (f"{source_id[:3].upper()}-{rng.randint(10000, 99999)}" if profile["mrn"] else "")}
    prov = {"as_of": when.isoformat(), "surname_period": ("maiden" if s_idx == 0 and len(timeline["surnames"]) > 1
                                                           else ("married" if s_idx > 0 else "birth")),
            "address_period": a_idx, "profile": [f"ssn:{'collected' if profile['collects_ssn'] else 'not_collected'}",
                                                 f"middle:{profile['middle']}", f"date:{profile['date_fmt']}",
                                                 f"addr_std:{profile['addr_std']}"],
            "applied": applied}
    return rec, prov


# --------------------------------------------------------------------------- #
# 5. Hard negatives: new entities that look like an existing patient
# --------------------------------------------------------------------------- #

def _shadow(base: Mapping[str, Any], rng: random.Random, role: str, first_pool: Sequence[Tuple[str, str]],
            address_pool: Sequence[Tuple[str, str, str, str]], counter: List[int],
            namesake_same_city: float = 0.0) -> Dict[str, Any]:
    counter[0] += 1
    e = {k: v for k, v in base.items() if not k.startswith("_")}
    e.update({"uuid": f"{role}-{counter[0]:06d}", "role": role, "maiden": "", "marital": "", "suffix": "",
              "deathdate": None, "ssn": f"999-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}",
              "alt_first": "", "_conditions": [], "_medications": [], "_allergies": []})
    birth_surname = base["maiden"] or base["last"]
    if role == "sibling":
        g, f = rng.choice(first_pool)
        e.update({"first": f, "middle": "", "gender": g, "last": birth_surname,
                  "alt_first": N.ANGLICISED.get(f, "") if base.get("group") == "hispanic" else "",
                  "birthdate": _add_years(base["birthdate"], rng.choice((-8, -6, -4, -3, -2, -1, 1, 2, 3, 4, 6, 8)))})
    elif role == "twin":
        same_sex = rng.random() < 0.5
        pool = [f for g, f in first_pool if (g == base["gender"]) == same_sex] or [f for _, f in first_pool]
        alike = [f for f in pool if f[:1] == base["first"][:1]]
        f = rng.choice(alike) if alike and rng.random() < 0.5 else rng.choice(pool)
        e.update({"first": f, "middle": "", "gender": base["gender"] if same_sex else ("M" if base["gender"] == "F" else "F"),
                  "last": birth_surname})
    elif role == "parent":                                     # same first and last name, one generation older
        e.update({"last": birth_surname, "middle": "", "birthdate": _add_years(base["birthdate"], -rng.randint(22, 38)),
                  "suffix": "Sr"})
    elif role == "namesake":                                   # same name and birth date, somewhere else
        same_city = [a for a in address_pool if a[1] == base["city"] and a[0] != base["address"]]
        if same_city and rng.random() < namesake_same_city:
            addr = rng.choice(same_city)                       # common names cluster regionally
        else:
            addr = rng.choice(address_pool) if address_pool else (base["address"], base["city"], base["state"], base["zip"])
        e.update({"middle": "", "last": base["last"], "address": addr[0], "city": addr[1], "state": addr[2], "zip": addr[3]})
    return e


# --------------------------------------------------------------------------- #
# 6. Assembly
# --------------------------------------------------------------------------- #

def build_benchmark(raw_dir: PathLike, preset: str = "calibrated", seed: int = 29, max_sources: int = 5,
                    n_synthetic_orgs: int = 12, horizon: dt.date = dt.date(2024, 6, 30),
                    limit: Optional[int] = None, names: str = "census", n_custodians: int = 8,
                    n_hospital_custodians: int = 0, spread_cities: bool = False,
                    window_years: float = 0.0, coverage: float = 1.0, secondary_share: float = 1.0,
                    go_live_years: float = 0.0) -> Dict[str, Any]:
    """Build the benchmark. Returns {records, provenance, stats, params}."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose from {sorted(PRESETS)}")
    cfg = PRESETS[preset]
    rates, life_events, households, profiles = cfg["rates"], cfg["life_events"], cfg["households"], cfg["profiles"]
    rng = random.Random(seed)
    random.seed(seed)

    if names == "census" and not N.available():
        names = "synthea"
    patients = load_patients(raw_dir, names=names, seed=seed, middle_name_share=rates.get("middle_name_share", 0.0),
                             hispanic_two_surnames=rates.get("hispanic_two_surnames", 0.0) if life_events else 0.0)
    if limit:
        patients = patients[:limit]
    visits, orgs = load_visits(raw_dir)
    address_pool = [(p["address"], p["city"], p["state"], p["zip"]) for p in patients if p["address"]]
    first_pool = [(p["gender"], p["first"]) for p in patients if p["first"]]

    # hard negatives are entities too; they get sources and records like everyone else
    entities: List[Dict[str, Any]] = list(patients)
    shadow_of: Dict[str, str] = {}
    counter = [0]
    if households:
        for p in patients:
            for role, key in (("sibling", "household_sibling"), ("twin", "twin"), ("parent", "parent_same_name"),
                              ("namesake", "namesake")):
                if rng.random() < rates[key]:
                    e = _shadow(p, rng, role, first_pool, address_pool, counter,
                                namesake_same_city=rates.get("namesake_same_city", 0.0))
                    entities.append(e)
                    shadow_of[e["uuid"]] = p["uuid"]

    sources, source_profiles, mode = assign_sources(entities, visits, orgs, rng, rates, profiles, max_sources,
                                                    n_synthetic_orgs, horizon,
                                                    span_dist=SPAN_DISTS[cfg.get("span_dist", "singleton_majority")],
                                                    n_custodians=n_custodians, n_hospital_custodians=n_hospital_custodians,
                                                    spread_cities=spread_cities, window_years=window_years,
                                                    coverage=coverage, secondary_share=secondary_share, go_live_years=go_live_years,
                                                    window_start=dt.date.fromisoformat(cfg.get("window_start", "1995-01-01")))
    # a planted look-alike is a confuser, not a duplicate: it gets ONE record, in the source where
    # its base patient is held (same household, same clinic), so it sits in the same blocks
    for sid, base_id in shadow_of.items():
        own = sources.get(sid, [])
        base_src = sources.get(base_id, [])
        if own:
            sources[sid] = own[:1]
        elif base_src and rng.random() < 0.8:
            sources[sid] = [base_src[0]]
        else:
            sources[sid] = []

    timelines = {e["uuid"]: build_timeline(e, rng, rates, address_pool, life_events, horizon) for e in entities}

    records: List[Dict[str, Any]] = []
    provenance: List[Dict[str, Any]] = []
    rid = 0
    for e in entities:
        tl = timelines[e["uuid"]]
        for source_id, first_visit, last_visit in sources.get(e["uuid"], []):
            prof = source_profiles[source_id]
            when = max(first_visit, e["birthdate"])
            if go_live_years and when > horizon:
                continue                                           # stream variant: nothing is registered after the horizon
            rec, prov = make_record(e, tl, source_id, prof, when, rng, rates, life_events)
            rid += 1
            row = {"id": f"r{rid:07d}", "cluster_id": e["uuid"], "source": source_id, "source_type": prof["type"],
                   "registered": when.isoformat(), **rec}
            records.append(row)
            provenance.append({"id": row["id"], "role": e["role"], "rereg": False, **prov})
            # repeat registration at the same source, years later, under a new MRN
            years_apart = (last_visit - (when if go_live_years else first_visit)).days / 365.25
            if life_events and years_apart >= 2 and rng.random() < rates["rereg"]:
                when2 = last_visit
                if go_live_years:
                    # stream variant: the repeat registration happens at some visit at least two
                    # years in, not at the last visit (living patients' last visits pile up at the horizon)
                    when2 = when + dt.timedelta(days=rng.randint(730, (last_visit - when).days))
                rec2, prov2 = make_record(e, tl, source_id, prof, when2, rng, rates, life_events)
                rid += 1
                row2 = {"id": f"r{rid:07d}", "cluster_id": e["uuid"], "source": source_id, "source_type": prof["type"],
                        "registered": when2.isoformat(), **rec2}
                records.append(row2)
                provenance.append({"id": row2["id"], "role": e["role"], "rereg": True, **prov2})

    # overlays (source 5): a record that carries another person's address or birth date
    if rates.get("overlay", 0.0) > 0 and len(entities) > 1:
        ent_by_id = {e["uuid"]: e for e in entities}
        prov_by_id = {p["id"]: p for p in provenance}
        for row in records:
            if rng.random() < rates["overlay"]:
                other = rng.choice(entities)
                if other["uuid"] == row["cluster_id"]:
                    continue
                if rng.random() < 0.7 and row["address"]:
                    row["address"], row["city"], row["zip"] = other["address"], other["city"], other["zip"]
                    prov_by_id[row["id"]]["applied"].append("overlay:address_of_other")
                elif row["birthdate"]:
                    prof = source_profiles[row["source"]]
                    row["birthdate"] = _fmt_date(other["birthdate"], prof["date_fmt"])
                    prov_by_id[row["id"]]["applied"].append("overlay:dob_of_other")
                prov_by_id[row["id"]]["overlay_from"] = other["uuid"]

    stats = realism_stats(records, source_profiles, entities)
    stats["sources_mode"] = mode
    params = {"preset": preset, "seed": seed, "max_sources": max_sources, "horizon": horizon.isoformat(),
              "span_dist": cfg.get("span_dist", "singleton_majority"), "names": names, "n_custodians": n_custodians,
              "window_start": cfg.get("window_start", "1995-01-01"), "n_hospital_custodians": n_hospital_custodians,
              "spread_cities": spread_cities, "window_years": window_years, "coverage": coverage,
              "secondary_share": secondary_share, "go_live_years": go_live_years,
              "rates": rates, "life_events": life_events, "households": households, "profiles": profiles,
              "n_patients": len(patients), "n_shadow_entities": len(entities) - len(patients)}
    return {"records": records, "provenance": provenance, "stats": stats, "params": params,
            "source_profiles": source_profiles}


# --------------------------------------------------------------------------- #
# 7. Realism statistics against the published anchors
# --------------------------------------------------------------------------- #

def _norm(v: str) -> str:
    v = S._drop_accents(v or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", v).strip()


_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), ("y", "m", "d")),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), ("m", "d", "y")),
    (re.compile(r"^(\d{4})$"), ("y",)),
)


def canon_date(text: str) -> Tuple[str, ...]:
    """Parse any format the sources write into a (y, m, d) or (y,) tuple so the
    realism check compares dates, not strings."""
    text = (text or "").strip()
    for pat, order in _DATE_PATTERNS:
        m = pat.match(text)
        if m:
            parts = dict(zip(order, m.groups()))
            if "m" in parts:
                return (parts["y"], f"{int(parts['m']):02d}", f"{int(parts['d']):02d}")
            return (parts["y"],)
    return (text,) if text else ()


def _dates_disagree(a: str, b: str) -> Optional[bool]:
    """None when either side is empty; compares at the coarser granularity
    (a lab's year against a hospital's full date compares the year only)."""
    ca, cb = canon_date(a), canon_date(b)
    if not ca or not cb:
        return None
    n = min(len(ca), len(cb))
    return ca[:n] != cb[:n]


def realism_stats(records: Sequence[Mapping[str, Any]], source_profiles: Mapping[str, Mapping[str, Any]],
                  entities: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_cluster: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for r in records:
        by_cluster[r["cluster_id"]].append(r)
    n_rec, n_ent = len(records), len(by_cluster)
    multi = [c for c in by_cluster.values() if len(c) > 1]
    n_pairs = sum(len(c) * (len(c) - 1) // 2 for c in multi)

    def keeps(r: Mapping[str, Any], field: str) -> bool:
        prof = source_profiles[r["source"]]
        if field == "ssn":
            return bool(prof["collects_ssn"])
        if field == "middle":
            return prof["middle"] != "none"
        if field == "first":
            return not prof.get("initials_only")
        return True

    disagree = Counter()
    denom = Counter()
    any_disagree = 0
    any_denom = 0
    full_disagree = 0          # pairs where both sources keep all six fields
    full_denom = 0
    rereg_disagree = 0         # within-source pairs (repeat registrations): the population Just et al. measured
    rereg_denom = 0
    for c in multi:
        for i in range(len(c)):
            for j in range(i + 1, len(c)):
                a, b = c[i], c[j]
                fields_compared = 0
                diff = 0
                schema_full = all(keeps(a, f) and keeps(b, f) for f in SIX_KEY_FIELDS)
                for f in SIX_KEY_FIELDS:
                    if not (keeps(a, f) and keeps(b, f)):
                        continue
                    if f == "birthdate":
                        d = _dates_disagree(a[f], b[f])
                        if d is None:
                            if a[f] or b[f]:                  # one blank: a clerical discrepancy
                                d = True
                            else:
                                continue
                        unequal = d
                    elif f == "ssn":
                        va, vb = a[f], b[f]
                        if not va and not vb:
                            continue
                        if not va or not vb:
                            unequal = True
                        elif va.startswith("xxx-xx-") or vb.startswith("xxx-xx-"):
                            unequal = va[-4:] != vb[-4:]       # a last-four source agrees on its four digits
                        else:
                            unequal = va != vb
                    else:
                        va, vb = _norm(a[f]), _norm(b[f])
                        if not va and not vb:
                            continue
                        unequal = va != vb
                    denom[f] += 1
                    fields_compared += 1
                    if unequal:
                        disagree[f] += 1
                        diff += 1
                if fields_compared:
                    any_denom += 1
                    any_disagree += int(diff > 0)
                if schema_full:                               # both sources keep all six fields
                    full_denom += 1
                    full_disagree += int(diff > 0)
                if a["source"] == b["source"] and fields_compared:
                    rereg_denom += 1
                    rereg_disagree += int(diff > 0)
    tuple_ids: Dict[Tuple[str, str, Tuple[str, ...]], set] = defaultdict(set)
    tuple_recs: Counter = Counter()
    for r in records:
        cd = canon_date(r["birthdate"])
        if r["first"] and r["last"] and len(cd) == 3:
            key = (_norm(r["first"]), _norm(r["last"]), cd)
            tuple_ids[key].add(r["cluster_id"])
            tuple_recs[key] += 1
    per_source = Counter(r["source_type"] for r in records)
    within = Counter((r["cluster_id"], r["source"]) for r in records)
    roles = Counter(e["role"] for e in entities)
    firsts = Counter(_norm(e["first"]) for e in entities if e["first"])
    lasts = Counter(_norm(e["last"]) for e in entities if e["last"])
    groups = Counter(e.get("group", "?") for e in entities)
    tags = Counter(t.split(":")[0] + ":" + t.split(":")[1] for r in records for t in r.get("_applied", []))
    name_dob = Counter((_norm(e["first"]), _norm(e["last"]), e["birthdate"].isoformat()) for e in entities)
    name_only = Counter((_norm(e["first"]), _norm(e["last"])) for e in entities)
    return {
        "records": n_rec, "entities": n_ent, "true_pairs": n_pairs,
        "share_entities_with_duplicate": round(len(multi) / n_ent, 4) if n_ent else 0.0,
        # anchor: Songs 8%, Citations 12% of records; 6-10% within one MPI
        "share_records_with_duplicate": round(sum(len(c) for c in multi) / n_rec, 4) if n_rec else 0.0,
        "records_minus_entities_over_records": round(1 - n_ent / n_rec, 4) if n_rec else 0.0,
        "within_source_duplicate_share": round(sum(1 for v in within.values() if v > 1) / max(1, len(within)), 4),
        "pairs_disagreeing_on_any_of_six": round(any_disagree / any_denom, 4) if any_denom else None,
        # anchor 0.95 (Just 2016, single full-schema MPI): compare with the full-schema subset
        "pairs_disagreeing_on_any_of_six_full_schema": round(full_disagree / full_denom, 4) if full_denom else None,
        "pairs_with_full_schema": full_denom,
        "within_source_pairs_disagreeing_on_any_of_six": round(rereg_disagree / rereg_denom, 4) if rereg_denom else None,
        "within_source_pairs": rereg_denom,
        "pair_disagreement_by_field": {f: round(disagree[f] / denom[f], 4) if denom[f] else None for f in SIX_KEY_FIELDS},
        "pair_denominator_by_field": {f: denom[f] for f in SIX_KEY_FIELDS},
        # anchors: middle .58, ssn .53, last .237, first .226, dob .062, gender .06
        # anchors: people per tuple 1.0062 (SSDMF, Zech 2016); records (MRNs) per tuple 1.12 overall and
        # 1.29 for multi-site patients in an HIE. This benchmark over-samples multi-source patients by
        # design (Leipzig structure), so records per tuple runs above the HIE figure.
        "people_per_name_dob_tuple": round(sum(len(v) for v in tuple_ids.values()) / len(tuple_ids), 4) if tuple_ids else None,
        "records_per_name_dob_tuple": round(sum(tuple_recs.values()) / len(tuple_recs), 4) if tuple_recs else None,
        "tuples_shared_by_two_people": sum(1 for v in tuple_ids.values() if len(v) > 1),
        "records_by_source_type": dict(per_source),
        "entities_by_role": dict(roles),
        "largest_cluster": max((len(c) for c in by_cluster.values()), default=0),
        # name realism: in a real population the 100 most common first names cover ~half the people
        "distinct_first_names": len(firsts),
        "top100_first_name_coverage": round(sum(n for _, n in firsts.most_common(100)) / max(1, sum(firsts.values())), 3),
        "distinct_surnames": len(lasts),
        "people_sharing_full_name": sum(n for n in name_only.values() if n > 1),
        "people_sharing_name_and_dob": sum(n for n in name_dob.values() if n > 1),
        "entities_by_group": dict(groups),
        "ssn_last4_sources": sum(1 for p in source_profiles.values() if p.get("ssn_format") == "last4"),
        "sources_keeping_accents": sum(1 for p in source_profiles.values() if p.get("keeps_accents")),
    }


# --------------------------------------------------------------------------- #
# 8. Writers
# --------------------------------------------------------------------------- #

def write_benchmark(result: Mapping[str, Any], out_dir: PathLike) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = result["records"]
    with (out / "records.csv").open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=list(OUTPUT_FIELDS))
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in OUTPUT_FIELDS})
    by_cluster: Dict[str, List[str]] = defaultdict(list)
    for r in records:
        by_cluster[r["cluster_id"]].append(r["id"])
    with (out / "gold_clusters.txt").open("w", encoding="utf-8") as handle:
        for ids in by_cluster.values():
            if len(ids) > 1:
                handle.write(" ".join(ids) + "\n")
    with (out / "records.jsonl").open("w", encoding="utf-8") as handle:
        for r in records:
            handle.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out / "provenance.jsonl").open("w", encoding="utf-8") as handle:
        for p in result["provenance"]:
            handle.write(json.dumps(p, ensure_ascii=False) + "\n")
    with (out / "datasheet.json").open("w", encoding="utf-8") as handle:
        json.dump({"params": result["params"], "stats": result["stats"],
                   "sources": {k: {kk: vv for kk, vv in v.items()} for k, v in result["source_profiles"].items()}},
                  handle, ensure_ascii=False, indent=1, default=str)
    return out
