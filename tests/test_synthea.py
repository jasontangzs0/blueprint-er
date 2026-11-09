import os
import unittest

from blueprint.synthea import (
    ATTR_FIELDS,
    CLINICAL_FIELDS,
    PROFILES,
    build_dataset,
    load_patients,
    load_patients_with_clinical,
    split_patients,
    true_pairs,
)

RAW_DIR = "data/raw/synthea"

PATIENTS_CSV = "data/raw/synthea/patients.csv"


def make_patients(n):
    """Inline canonical entities (bypass the CSV) for fast, deterministic tests."""
    patients = []
    for i in range(n):
        patients.append(
            {
                "uuid": f"u{i}",
                "first": f"Given{chr(65 + i % 26)}",
                "last": f"Surname{chr(65 + (i * 7) % 26)}",
                "maiden": "",
                "birthdate": f"19{80 + i % 20:02d}-0{i % 9 + 1}-1{i % 9}",
                "gender": "M" if i % 2 else "F",
                "address": f"{100 + i} Example Street Unit {i % 5}",
                "city": f"Town{chr(65 + i % 10)}",
                "state": "Massachusetts",
                "zip": f"0{1000 + i}",
                "ssn": f"999-{i:02d}-{1000 + i}",
            }
        )
    return patients


def _attr_tuple(record):
    return tuple(record[f] for f in ATTR_FIELDS)


def _by_cluster(records):
    out = {}
    for r in records:
        out.setdefault(r["cluster_id"], []).append(r)
    return out


class RecordShape(unittest.TestCase):
    def test_records_have_required_keys_and_unique_ids(self):
        records = build_dataset(make_patients(40), k_sources=5, seed=0)
        self.assertTrue(records)
        ids = [r["id"] for r in records]
        self.assertEqual(len(ids), len(set(ids)))
        for r in records:
            for key in ("id", "cluster_id", "source_domain", *ATTR_FIELDS, *CLINICAL_FIELDS):
                self.assertIn(key, r)
                if key in CLINICAL_FIELDS:
                    self.assertIsInstance(r[key], str)

    def test_gold_standard_matches_true_pairs(self):
        records = build_dataset(make_patients(40), k_sources=5, seed=0)
        expected = 0
        for ids in _by_cluster(records).values():
            k = len(ids)
            expected += k * (k - 1) // 2
        self.assertEqual(len(true_pairs(records)), expected)


class SourceModel(unittest.TestCase):
    def test_p0_has_at_most_one_record_per_source_per_entity(self):
        records = build_dataset(make_patients(60), k_sources=5,
                                within_source_dup_rate=0.0, seed=0)
        for ids in _by_cluster(records).values():
            sources = [r["source_domain"] for r in ids]
            self.assertEqual(len(sources), len(set(sources)))

    def test_within_source_dup_rate_creates_same_source_duplicates(self):
        records = build_dataset(make_patients(60), k_sources=5,
                                within_source_dup_rate=0.9, seed=0)
        same_source_dup = any(
            len([r["source_domain"] for r in ids]) != len({r["source_domain"] for r in ids})
            for ids in _by_cluster(records).values()
        )
        self.assertTrue(same_source_dup, "p>0 should put 2 records of an entity in one source")


class MusicBrainzProfile(unittest.TestCase):
    def test_no_within_source_dups_and_a_mix_of_spans(self):
        records = build_dataset(make_patients(400), k_sources=5,
                                profile="musicbrainz", within_source_dup_rate=0.0, seed=0)
        spans = []
        for ids in _by_cluster(records).values():
            sources = [r["source_domain"] for r in ids]
            self.assertEqual(len(sources), len(set(sources)),
                             "musicbrainz profile (p=0) must have no within-source duplicates")
            spans.append(len(set(sources)))
        self.assertIn(1, spans, "should produce singletons")
        self.assertTrue(any(s >= 2 for s in spans), "should produce multi-source entities")
        # roughly half singletons (50% in the MB distribution); generous tolerance.
        singleton_frac = spans.count(1) / len(spans)
        self.assertGreater(singleton_frac, 0.35)
        self.assertLess(singleton_frac, 0.65)


class Corruption(unittest.TestCase):
    def test_clean_replicated_entities_are_identical_across_sources(self):
        records = build_dataset(make_patients(80), k_sources=5,
                                profile="moderate", seed=0)
        # The moderate profile's 50% clean bucket => some entity is byte-identical
        # across all its (>=2) sources.
        found = False
        for ids in _by_cluster(records).values():
            if len(ids) >= 2 and len({_attr_tuple(r) for r in ids}) == 1:
                found = True
                break
        self.assertTrue(found)

    def test_corruption_makes_some_records_differ(self):
        records = build_dataset(make_patients(80), k_sources=5,
                                profile="moderate", seed=0)
        differing = any(
            len(ids) >= 2 and len({_attr_tuple(r) for r in ids}) > 1
            for ids in _by_cluster(records).values()
        )
        self.assertTrue(differing, "corrupted buckets should yield differing records")


class Reproducibility(unittest.TestCase):
    def test_same_seed_same_dataset(self):
        patients = make_patients(50)
        a = build_dataset(patients, k_sources=5, within_source_dup_rate=0.1, seed=7)
        b = build_dataset(patients, k_sources=5, within_source_dup_rate=0.1, seed=7)
        self.assertEqual(a, b)

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            build_dataset(make_patients(5), profile="nope")


class Splits(unittest.TestCase):
    def test_entity_disjoint_and_complete(self):
        patients = make_patients(100)
        splits = split_patients(patients, fracs=(0.6, 0.2, 0.2), seed=0)
        uuids = {s: {p["uuid"] for p in ps} for s, ps in splits.items()}
        self.assertEqual(uuids["train"] & uuids["valid"], set())
        self.assertEqual(uuids["train"] & uuids["gs"], set())
        self.assertEqual(uuids["valid"] & uuids["gs"], set())
        total = sum(len(ps) for ps in splits.values())
        self.assertEqual(total, len(patients))


@unittest.skipUnless(os.path.exists(PATIENTS_CSV), "staged Synthea sample required")
class LoadPatients(unittest.TestCase):
    def test_load_strips_name_digits_and_keeps_fields(self):
        patients = load_patients(PATIENTS_CSV)
        self.assertGreater(len(patients), 1000)
        for p in patients[:200]:
            self.assertNotRegex(p["first"], r"\d", "Synthea name digits should be stripped")
            self.assertNotRegex(p["last"], r"\d")
            for field in ATTR_FIELDS:
                self.assertIn(field, p)


@unittest.skipUnless(os.path.exists(f"{RAW_DIR}/conditions.csv"), "staged Synthea clinical files required")
class ClinicalProfile(unittest.TestCase):
    def test_clinical_lists_attached_and_nonempty_for_some(self):
        patients = load_patients_with_clinical(RAW_DIR)
        for p in patients[:50]:
            for key in ("_conditions", "_medications", "_allergies"):
                self.assertIsInstance(p[key], list)
        self.assertTrue(any(p["_conditions"] for p in patients), "some patient has a problem list")

    def test_built_records_carry_clinical_text(self):
        patients = load_patients_with_clinical(RAW_DIR)
        records = build_dataset(patients, k_sources=5, profile="moderate", seed=0)
        self.assertTrue(any(r["problem_list"] for r in records),
                        "some record should carry a non-empty problem list")


if __name__ == "__main__":
    unittest.main()
