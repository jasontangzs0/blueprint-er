import unittest

from blueprint.wdc_four_domains import clean_value, compose, stats


def _pool():
    offers, gold = {}, set()
    # 6 products x 7 listings; products 0 and 1 have two checked listings, the rest one
    for p in range(6):
        for k in range(7):
            oid = f"{p}{k:02d}"
            offers[oid] = {"id": oid, "cluster_id": f"c{p}", "source": "computers",
                           "title": f"t{oid}", "brand": "", "price": "", "description": ""}
            if k == 0 or (p < 2 and k == 1):
                gold.add(oid)
    pairs = [("000", "001", 1), ("100", "101", 1), ("200", "300", 0), ("400", "500", 0)]
    return offers, gold, pairs


class CleanValue(unittest.TestCase):
    def test_strips_quotes_and_language_tags(self):
        self.assertEqual(clean_value('"Gigabyte"@en'), "Gigabyte")
        self.assertEqual(clean_value(' "Radeon RX 480"@en "▷ Gigabyte Gr… | OcUK"@en'), "Radeon RX 480 ▷ Gigabyte Gr… | OcUK")
        self.assertEqual(clean_value('"Air Jordan 4"@en-US (#308497-100) | Shop"@en-US'), "Air Jordan 4 (#308497-100) | Shop")
        self.assertEqual(clean_value('"\n   More>>>\n   \n"'), "More>>>")
        self.assertEqual(clean_value(None), "")
        self.assertEqual(clean_value("None"), "")


class Compose(unittest.TestCase):
    def test_keeps_gold_respects_cap_and_counts(self):
        offers, gold, pairs = _pool()
        chosen = compose(offers, gold, n_records=20, n_singletons=2, cap=5, seed=0)
        kept = {o for ids in chosen.values() for o in ids}
        self.assertTrue(gold <= kept)
        self.assertEqual(len(kept), 20)
        self.assertLessEqual(max(len(ids) for ids in chosen.values()), 5)
        s = stats(offers, chosen, pairs)
        self.assertEqual((s["singletons"], s["dup_products"], s["records"]), (2, 4, 20))
        self.assertEqual(s["checked_pairs_resolvable"], 4)
        self.assertEqual(compose(offers, gold, 20, 2, 5, 0), chosen)  # deterministic

    def test_stops_at_capacity(self):
        offers, gold, _ = _pool()
        chosen = compose(offers, gold, n_records=60, n_singletons=0, cap=3, seed=0)
        self.assertEqual(sum(len(ids) for ids in chosen.values()), 18)  # 6 products x cap 3

    def test_refuses_more_singletons_than_single_gold_products(self):
        offers, gold, _ = _pool()
        with self.assertRaises(ValueError):
            compose(offers, gold, n_records=20, n_singletons=5, cap=5, seed=0)


if __name__ == "__main__":
    unittest.main()
