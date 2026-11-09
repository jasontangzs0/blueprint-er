"""Build the patient-linkage benchmark from a Synthea CSV export.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/patients_build.py --raw data/raw/synthea \
      --out data/processed/patients/calibrated --preset calibrated --seed 29

Writes records.csv + gold_clusters.txt (what scripts/reper.py and
scripts/splink_generic.py read), records.jsonl, provenance.jsonl and
datasheet.json, and prints the realism statistics next to their anchors.
"""
import argparse
import datetime as dt
import json

from blueprint.patients import MATCH_FIELDS, PRESETS, build_benchmark, write_benchmark

ANCHORS = {
    "pairs_disagreeing_on_any_of_six": 0.95,
    "identities_per_name_dob_tuple": 1.12,
    "share_entities_with_duplicate": "0.50 (Leipzig structure) / 6-10% within-source",
}
FIELD_ANCHORS = {"middle": 0.58, "ssn": 0.53, "last": 0.237, "first": 0.226, "birthdate": 0.062, "gender": 0.06}

ap = argparse.ArgumentParser()
ap.add_argument("--raw", default="data/raw/synthea")
ap.add_argument("--out", required=True)
ap.add_argument("--preset", default="calibrated", choices=sorted(PRESETS))
ap.add_argument("--seed", type=int, default=29)
ap.add_argument("--max-sources", type=int, default=5)
ap.add_argument("--limit", type=int, default=0, help="first N patients only (smoke tests)")
ap.add_argument("--horizon", default="2024-06-30")
ap.add_argument("--names", default="census", choices=("census", "synthea"), help="redraw names from real frequency tables, or keep Synthea's")
ap.add_argument("--custodians", type=int, default=8, help="visits mode: link the N organisations with the most patients (0 = all)")
ap.add_argument("--hospitals", type=int, default=0, help="visits mode: reserve this many custodian slots for the largest hospitals")
ap.add_argument("--spread-cities", action="store_true", help="visits mode: at most one custodian per city, largest first (less overlap)")
ap.add_argument("--window-years", type=float, default=0.0, help="visits mode: each custodian's extract covers a random window of this many years (0 = all history)")
ap.add_argument("--coverage", type=float, default=1.0, help="visits mode: share of an organisation's patients its extract holds (overlap falls with the square)")
ap.add_argument("--secondary", type=float, default=1.0, help="visits mode: a patient's primary organisation always holds them; a secondary one holds them with this probability")
ap.add_argument("--go-live-years", type=float, default=0.0, help="stream variant: each custodian goes live at a random point in the first N years of the window and holds a patient from their first encounter after go-live to the horizon (0 = off, dates as before)")
a = ap.parse_args()

res = build_benchmark(a.raw, preset=a.preset, seed=a.seed, max_sources=a.max_sources,
                      horizon=dt.date.fromisoformat(a.horizon), limit=a.limit or None, names=a.names,
                      n_custodians=a.custodians, n_hospital_custodians=a.hospitals, spread_cities=a.spread_cities,
                      window_years=a.window_years, coverage=a.coverage, secondary_share=a.secondary,
                      go_live_years=a.go_live_years)
out = write_benchmark(res, a.out)
s = res["stats"]
print(f"wrote {out}  preset={a.preset} seed={a.seed} sources={s['sources_mode']}")
print(f"records {s['records']:,}  entities {s['entities']:,}  true pairs {s['true_pairs']:,}  largest cluster {s['largest_cluster']}")
print(f"extra copies / records {s['records_minus_entities_over_records']:.3f} (Songs .08, Citations .12)   records with a duplicate {s['share_records_with_duplicate']:.3f}   entities with a duplicate {s['share_entities_with_duplicate']:.3f}   within-source dup share {s['within_source_duplicate_share']:.3f}")
print(f"pairs disagreeing on >=1 of six key fields: all pairs {s['pairs_disagreeing_on_any_of_six']}; "
      f"full-schema pairs {s['pairs_disagreeing_on_any_of_six_full_schema']} (n={s['pairs_with_full_schema']:,}); "
      f"within-source repeat registrations {s['within_source_pairs_disagreeing_on_any_of_six']} (n={s['within_source_pairs']:,})   anchor 0.95")
print("per-field pair disagreement (anchor):")
for f, v in s["pair_disagreement_by_field"].items():
    n = s["pair_denominator_by_field"][f]
    print(f"  {f:10s} {v if v is not None else '  n/a'}   (anchor {FIELD_ANCHORS[f]}, n={n:,})")
print(f"people per name+dob tuple {s['people_per_name_dob_tuple']}   anchor 1.006 (SSDMF); tuples shared by two people {s['tuples_shared_by_two_people']}")
print(f"records per name+dob tuple {s['records_per_name_dob_tuple']}   HIE 1.12 overall / 1.29 multi-site (ours is denser by design)")
print("records by source type", json.dumps(s["records_by_source_type"]))
print("entities by role", json.dumps(s["entities_by_role"]))
print(f"names ({res['params']['names']}): distinct first {s['distinct_first_names']:,}, top-100 first-name coverage {s['top100_first_name_coverage']:.2f} (real ~0.5), "
      f"distinct surnames {s['distinct_surnames']:,}, people sharing full name {s['people_sharing_full_name']}, sharing name+DOB {s['people_sharing_name_and_dob']}")
print(f"groups {json.dumps(s['entities_by_group'])}; sources storing SSN last-4 only {s['ssn_last4_sources']}, keeping accents {s['sources_keeping_accents']}")
print(f"matching schema (demographics only): --fields {','.join(MATCH_FIELDS)}")
