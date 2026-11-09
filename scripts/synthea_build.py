"""Build and persist Synthea-based multi-partite ER benchmark variants.

Run from repo root:  .venv/bin/python scripts/synthea_build.py

Writes one JSON record list per (profile, p) variant to data/processed/synthea/,
plus entity-disjoint train/valid/gs splits for the primary (moderate, p=0)
variant. All variants are reproducible from their seed.
"""

import json
from pathlib import Path

from blueprint.synthea import build_dataset, load_patients_with_clinical, split_patients, true_pairs

OUT = Path("data/processed/synthea")
OUT.mkdir(parents=True, exist_ok=True)
PATIENTS = load_patients_with_clinical("data/raw/synthea")
print(f"loaded {len(PATIENTS)} canonical patients (with clinical profiles)")


def summary(records):
    by_clu = {}
    for r in records:
        by_clu.setdefault(r["cluster_id"], set()).add(r["source_domain"])
    multi = sum(1 for s in by_clu.values() if len(s) >= 2)
    return {"records": len(records), "entities": len(by_clu),
            "multi_source_entities": multi, "true_pairs": len(true_pairs(records))}


def dump(records, name):
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(records))
    print(f"  wrote {path}  {summary(records)}")


# Full-population variants (the "train_large" analogue). Primary = MusicBrainz-
# matched structure; the p=0.1 twin adds within-source dups (the A5-breaker);
# moderate kept as a reference alternative.
print("\n== full-population variants ==")
for profile, p in [("musicbrainz", 0.0), ("musicbrainz", 0.1), ("moderate", 0.0)]:
    recs = build_dataset(PATIENTS, k_sources=5, profile=profile,
                         within_source_dup_rate=p, seed=0)
    dump(recs, f"synthea_{profile}_p{int(p*100):02d}_k5")

# Entity-disjoint protocol splits for the primary (MusicBrainz-matched) variant.
print("\n== protocol splits (musicbrainz, p=0, K=5) ==")
splits = split_patients(PATIENTS, fracs=(0.6, 0.2, 0.2), seed=0)
for split_name, patients in splits.items():
    recs = build_dataset(patients, k_sources=5, profile="musicbrainz",
                         within_source_dup_rate=0.0, seed=0)
    dump(recs, f"synthea_musicbrainz_k5_{split_name}")
