import csv
import datetime as dt
import json
import os
import random
import tempfile
import unittest

from blueprint.patients import (
    OUTPUT_FIELDS,
    PRESETS,
    RATES,
    build_benchmark,
    build_timeline,
    canon_date,
    load_patients,
    make_record,
    write_benchmark,
    _make_profile,
)

RAW_DIR = "data/raw/synthea"
HAS_RAW = os.path.exists(os.path.join(RAW_DIR, "patients.csv"))


def josefa():
    return {
        "uuid": "u-josefa", "first": "Josefa", "middle": "María", "last": "Rivera", "maiden": "Gómez",
        "suffix": "", "marital": "M", "gender": "F", "birthdate": dt.date(1989, 5, 25), "deathdate": None,
        "ssn": "999-76-6866", "address": "427 Balistreri Way Unit 19", "city": "Chicopee",
        "state": "Massachusetts", "zip": "01013", "_conditions": ["Chronic sinusitis"],
        "_medications": ["amoxicillin"], "_allergies": [], "role": "patient",
    }


class CanonDate(unittest.TestCase):
    def test_formats_agree(self):
        self.assertEqual(canon_date("1989-05-25"), canon_date("05/25/1989"))
        self.assertEqual(canon_date("1989-5-25"), canon_date("5/25/1989"))
        self.assertEqual(canon_date("1989"), ("1989",))
        self.assertEqual(canon_date(""), ())


class Timeline(unittest.TestCase):
    def test_marriage_renames_after_28_only(self):
        rng = random.Random(1)
        tl = build_timeline(josefa(), rng, RATES, [], life_events=True, horizon=dt.date(2024, 6, 30))
        self.assertEqual(tl["surnames"][0], (dt.date(1989, 5, 25), "Gómez"))
        self.assertEqual(len(tl["surnames"]), 2)
        self.assertEqual(tl["surnames"][1][1], "Rivera")
        self.assertGreaterEqual(tl["surnames"][1][0], dt.date(2017, 5, 25))
        self.assertLess(tl["surnames"][1][0], dt.date(2018, 5, 26))

    def test_no_life_events_means_current_surname_everywhere(self):
        rng = random.Random(1)
        tl = build_timeline(josefa(), rng, RATES, [], life_events=False, horizon=dt.date(2024, 6, 30))
        self.assertEqual(tl["surnames"], [(dt.date(1989, 5, 25), "Rivera")])
        self.assertEqual(len(tl["addresses"]), 1)

    def test_moves_only_with_a_pool_and_after_18(self):
        rng = random.Random(3)
        pool = [("12 Front St", "Springfield", "Massachusetts", "01103")]
        rates = {**RATES, "move_hazard_per_year": 1.0}
        tl = build_timeline(josefa(), rng, rates, pool, life_events=True, horizon=dt.date(2024, 6, 30))
        self.assertGreater(len(tl["addresses"]), 1)
        self.assertGreaterEqual(tl["addresses"][1][0], dt.date(2007, 5, 25))


class RecordsThroughProfiles(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)
        self.tl = build_timeline(josefa(), random.Random(1), RATES, [], True, dt.date(2024, 6, 30))
        self.quiet = {**{k: 0.0 for k in RATES}, "nickname_use": 0.0}  # no clerical errors

    def test_pre_marriage_record_carries_maiden_name(self):
        prof = _make_profile("hospital", random.Random(0), profiles=False)
        rec, prov = make_record(josefa(), self.tl, "org1", prof, dt.date(2013, 9, 2), self.rng, self.quiet, True)
        self.assertEqual(rec["last"], "Gómez")
        self.assertEqual(prov["surname_period"], "maiden")
        self.assertEqual(rec["birthdate"], "1989-05-25")

    def test_post_marriage_record_carries_married_name(self):
        prof = _make_profile("hospital", random.Random(0), profiles=False)
        rec, prov = make_record(josefa(), self.tl, "org1", prof, dt.date(2022, 1, 1), self.rng, self.quiet, True)
        self.assertEqual(rec["last"], "Rivera")
        self.assertEqual(prov["surname_period"], "married")

    def test_lab_keeps_initial_year_zip_only(self):
        prof = _make_profile("lab", random.Random(0), profiles=True)
        rec, prov = make_record(josefa(), self.tl, "lab", prof, dt.date(2021, 2, 15), self.rng, self.quiet, True)
        self.assertEqual(rec["first"], "J")
        self.assertEqual(rec["last"], "RIVERA")
        self.assertEqual(rec["birthdate"], "1989")
        self.assertEqual(rec["ssn"], "")
        self.assertEqual(rec["address"], "")
        self.assertEqual(rec["zip"], "01013")
        self.assertIn("profile:initials_only", prov["applied"])

    def test_newborn_gets_placeholder_name(self):
        prof = _make_profile("hospital", random.Random(0), profiles=False)
        rates = {**self.quiet, "newborn_placeholder": 1.0}
        rec, prov = make_record(josefa(), self.tl, "org1", prof, dt.date(1989, 5, 26), self.rng, rates, True)
        self.assertEqual(rec["first"], "Baby Girl")
        self.assertIn("first:newborn_placeholder", prov["applied"])

    def test_every_applied_change_is_named(self):
        prof = _make_profile("hospital", random.Random(0), profiles=False)
        rates = {**self.quiet, "ssn_placeholder": 1.0, "middle_blank": 1.0}
        rec, prov = make_record(josefa(), self.tl, "org1", prof, dt.date(2013, 9, 2), self.rng, rates, True)
        self.assertEqual(rec["middle"], "")
        self.assertIn(rec["ssn"], ("999-99-9999", "111-11-1111", "123-45-6789"))
        self.assertIn("ssn:placeholder", prov["applied"])
        self.assertIn("middle:blank", prov["applied"])


@unittest.skipUnless(HAS_RAW, "Synthea sample not present")
class EndToEnd(unittest.TestCase):
    def test_loader_splits_folded_middle_names(self):
        ps = load_patients(RAW_DIR)
        self.assertEqual(len(ps), 1171)
        folded = [p for p in ps if p["middle"]]
        self.assertTrue(all(" " not in p["first"] for p in ps))
        self.assertGreater(len(folded), 0)

    def test_same_seed_same_output(self):
        a = build_benchmark(RAW_DIR, "calibrated", seed=5, limit=150)
        b = build_benchmark(RAW_DIR, "calibrated", seed=5, limit=150)
        self.assertEqual(a["records"], b["records"])
        self.assertEqual(a["provenance"], b["provenance"])

    def test_gold_is_exact_and_shadows_are_distinct(self):
        res = build_benchmark(RAW_DIR, "calibrated", seed=11, limit=300)
        patients = {p["uuid"] for p in load_patients(RAW_DIR)[:300]}
        clusters = {r["cluster_id"] for r in res["records"]}
        self.assertTrue(clusters <= patients | {c for c in clusters if "-" in c and c.split("-")[0] in ("sibling", "twin", "parent", "namesake")})
        roles = {p["role"] for p in res["provenance"]}
        self.assertIn("sibling", roles)
        # a shadow entity never shares a cluster with its base patient
        self.assertTrue(all(not c.startswith(("sibling", "twin", "parent", "namesake")) or c not in patients for c in clusters))

    def test_typos_preset_has_no_life_events_or_families(self):
        res = build_benchmark(RAW_DIR, "typos", seed=2, limit=300)
        self.assertEqual(res["stats"]["entities_by_role"], {"patient": 300})
        self.assertTrue(all(p["surname_period"] == "birth" and p["address_period"] == 0 for p in res["provenance"]))

    def test_calibrated_rates_land_near_anchors(self):
        s = build_benchmark(RAW_DIR, "calibrated", seed=29)["stats"]
        f = s["pair_disagreement_by_field"]
        # a few hundred pairs on the sample: allow sampling noise of about four points
        self.assertLess(abs(f["birthdate"] - 0.062), 0.04)
        self.assertLess(abs(f["gender"] - 0.06), 0.04)
        if s["pair_denominator_by_field"]["middle"] >= 200:   # the 1,171 sample has almost no middle names
            self.assertLess(abs(f["middle"] - 0.58), 0.12)
        self.assertLess(abs(f["ssn"] - 0.53), 0.16)   # ~250 SSN-bearing pairs on the sample: noisy
        self.assertGreater(s["within_source_duplicate_share"], 0.02)

    def test_writer_round_trip(self):
        res = build_benchmark(RAW_DIR, "calibrated", seed=3, limit=120)
        with tempfile.TemporaryDirectory() as d:
            out = write_benchmark(res, d)
            rows = list(csv.DictReader(open(out / "records.csv", encoding="utf-8")))
            self.assertEqual(len(rows), len(res["records"]))
            self.assertEqual(list(rows[0].keys()), list(OUTPUT_FIELDS))
            ids = {r["id"] for r in rows}
            for line in open(out / "gold_clusters.txt"):
                members = line.split()
                self.assertGreater(len(members), 1)
                self.assertTrue(set(members) <= ids)
            sheet = json.load(open(out / "datasheet.json"))
            self.assertEqual(sheet["params"]["preset"], "calibrated")
            self.assertIn("pair_disagreement_by_field", sheet["stats"])


class VisitsMode(unittest.TestCase):
    """A mock full export: encounters and organisations tables (title-case headers, as the
    current Synthea data dictionary writes them). Custodians are chosen by patient count and
    records are dated at the first visit."""

    def _write_export(self, d):
        rows = [
            # Id,BIRTHDATE,DEATHDATE,SSN,...,FIRST,MIDDLE,LAST,SUFFIX,MAIDEN,MARITAL,RACE,ETHNICITY,GENDER,...
            ("p1", "1989-05-25", "", "999-76-6866", "Josefa", "Maria", "Rivera", "", "Gomez", "M", "white", "hispanic", "F",
             "427 Balistreri Way Unit 19", "Chicopee", "Massachusetts", "01013"),
            ("p2", "1975-02-02", "", "999-11-2222", "Daniel", "", "Auer", "", "", "S", "white", "nonhispanic", "M",
             "1050 Lindgren Extension Apt 38", "Boston", "Massachusetts", "02135"),
            ("p3", "2001-09-09", "", "999-33-4444", "Mei", "", "Nguyen", "", "", "S", "asian", "nonhispanic", "F",
             "8 Pleasant St", "Worcester", "Massachusetts", "01609"),
        ]
        with open(os.path.join(d, "patients.csv"), "w", encoding="utf-8") as f:
            f.write("Id,BirthDate,DeathDate,SSN,First,Middle,Last,Suffix,Maiden,Marital,Race,Ethnicity,Gender,Address,City,State,Zip\n")
            for r in rows:
                f.write(",".join(r) + "\n")
        for name in ("conditions", "medications", "allergies"):
            with open(os.path.join(d, f"{name}.csv"), "w", encoding="utf-8") as f:
                f.write("Start,Stop,Patient,Encounter,Code,Description\n")
        with open(os.path.join(d, "organizations.csv"), "w", encoding="utf-8") as f:
            f.write("Id,Name,Address,City,State,Zip,Lat,Lon,Phone,Revenue,Utilization\n")
            f.write("o1,BAYSTATE MEDICAL CENTER,759 Chestnut St,Springfield,MA,01199,0,0,,0,0\n")
            f.write("o2,CHICOPEE FAMILY HEALTH,100 Front St,Chicopee,MA,01013,0,0,,0,0\n")
            f.write("o3,TINY URGENT CARE,1 Side St,Boston,MA,02135,0,0,,0,0\n")
        with open(os.path.join(d, "encounters.csv"), "w", encoding="utf-8") as f:
            f.write("Id,Start,Stop,Patient,Organization,Provider,Payer,EncounterClass,Code,Description\n")
            enc = [("p1", "2013-09-02", "o1"), ("p1", "2014-01-10", "o1"), ("p1", "2016-03-11", "o2"), ("p1", "2021-08-30", "o2"),
                   ("p2", "2002-03-15", "o2"), ("p2", "2019-04-04", "o2"), ("p2", "2010-01-01", "o3"),
                   ("p3", "2015-05-05", "o1")]
            for i, (p, d_, o) in enumerate(enc):
                f.write(f"e{i},{d_}T10:00:00Z,{d_}T11:00:00Z,{p},{o},pr1,pay1,ambulatory,1,visit\n")

    def test_custodians_and_dates(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_export(d)
            quiet = {**{k: 0.0 for k in RATES}, "middle_name_share": 0.0}
            from blueprint import patients as P
            P.PRESETS["_test_visits"] = {"life_events": True, "households": False, "profiles": False,
                                         "span_dist": "singleton_majority", "rates": quiet}
            try:
                res = build_benchmark(d, "_test_visits", seed=1, names="synthea", n_custodians=2)
            finally:
                del P.PRESETS["_test_visits"]
            self.assertEqual(res["stats"]["sources_mode"], "visits")
            srcs = {r["source"] for r in res["records"]}
            self.assertIn("o1", srcs); self.assertIn("o2", srcs)
            self.assertNotIn("o3", srcs)                      # the smallest organisation is not a custodian
            p1 = sorted((r for r in res["records"] if r["cluster_id"] == "p1"), key=lambda r: r["registered"])
            self.assertEqual([r["registered"] for r in p1], ["2013-09-02", "2016-03-11"])
            self.assertEqual([r["last"] for r in p1], ["Gomez", "Gomez"])   # both before the marriage at 28 (2017)
            self.assertEqual(res["source_profiles"]["o1"]["type"], "hospital")
            self.assertEqual(res["source_profiles"]["o2"]["type"], "clinic")


if __name__ == "__main__":
    unittest.main()
