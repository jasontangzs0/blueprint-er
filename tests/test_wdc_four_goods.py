import random
import unittest

from blueprint.wdc_four_goods import choose_products, plain_members, hard_members, plain_singletons, hard_singletons


def _index():
    rng = random.Random(0)
    clusters = {}
    words = ["nike", "adidas", "puma", "shirt", "jacket", "blue", "red", "xl", "kids", "running", "hoodie", "cap"]
    for p in range(60):
        base = " ".join(rng.sample(words, 4))
        n = rng.choice([1, 1, 1, 2, 3, 5, 8, 14, 150])
        clusters[f"c{p}"] = [(f"{p}_{k}", f"{base} {rng.choice(words)} v{k}") for k in range(n)]
    clusters["c_untitled"] = [("u1", ""), ("u2", "")]
    return clusters


class Selection(unittest.TestCase):
    def test_choose_products_respects_budget_cap_and_exclusions(self):
        clusters = _index()
        chosen = choose_products(clusters, exclude={"c1", "c2"}, record_budget=60, cap=6, max_size=100, seed=0)
        self.assertTrue(all(2 <= len(clusters[c]) <= 100 for c in chosen))
        self.assertTrue(all(k <= 6 and k <= len(clusters[c]) for c, k in chosen.items()))
        self.assertLessEqual(sum(chosen.values()), 60)
        self.assertFalse({"c1", "c2", "c_untitled"} & set(chosen))

    def test_two_versions_share_products_and_counts(self):
        clusters = _index()
        chosen = choose_products(clusters, set(), 60, 6, 100, 0)
        p, h = plain_members(clusters, chosen, 0), hard_members(clusters, chosen, 0)
        self.assertEqual(set(p), set(h))
        for c in chosen:
            self.assertEqual(len(p[c]), len(h[c]))
            self.assertEqual(len(set(h[c])), len(h[c]))
            self.assertTrue(set(h[c]) <= {o for o, _ in clusters[c]})
        sp = plain_singletons(clusters, chosen, set(), 8, 0)
        sh = hard_singletons(clusters, chosen, set(), 8, 0)
        self.assertEqual((len(sp), len(sh)), (8, 8))
        self.assertFalse(set(sp) & set(chosen) or set(sh) & set(chosen))
        for d in (sp, sh):
            for c, oid in d.items():
                self.assertIn(oid, {o for o, _ in clusters[c]})

    def test_hard_singletons_skip_near_identical_titles(self):
        from blueprint.wdc_four_goods import _vectorizer
        clusters = _index()
        chosen = choose_products(clusters, set(), 60, 6, 100, 0)
        twin_of = next(iter(chosen))
        clusters["twin"] = [("tw1", clusters[twin_of][0][1])]          # same title as a chosen product's copy
        sh = hard_singletons(clusters, chosen, set(), 8, 0)
        self.assertNotIn("twin", sh)
        vec, X = _vectorizer([t for c in chosen for _, t in clusters[c]])
        for c, oid in sh.items():
            title = dict(clusters[c])[oid]
            self.assertLess(float((vec.transform([title]) @ X.T).toarray().max()), 0.9)

    def test_hard_members_are_farther_apart_than_plain(self):
        from blueprint.wdc_four_goods import _vectorizer
        clusters = {"big": [(f"o{k}", t) for k, t in enumerate(
            ["nike air max 90 black", "nike air max 90 black men", "nike air max 90 black size 42",
             "air max 90 noir chaussure", "sneaker 90 schwarz herren", "nike am90 blk"])]}
        chosen = {"big": 3}
        h = hard_members(clusters, chosen, 0)["big"]
        titles = {o: t for o, t in clusters["big"]}
        _, X = _vectorizer([titles[o] for o in h]); s = (X @ X.T).toarray()
        self.assertLess(s[0, 1] + s[0, 2] + s[1, 2], 1.5)


class Multilingual(unittest.TestCase):
    def test_multilingual_products_and_preferred_share(self):
        from blueprint.wdc_four_goods import multilingual_products, choose_products_mixed
        clusters = _index()
        tags = {}
        for p in (3, 4, 5):                         # three products get a German copy
            L = clusters[f"c{p}"]
            if len(L) >= 2:
                tags[L[0][0]] = "en"; tags[L[1][0]] = "de"
        ml = multilingual_products(clusters, tags)
        self.assertTrue(ml <= {"c3", "c4", "c5"} and ml)
        chosen = choose_products_mixed(clusters, set(), record_budget=60, cap=6, max_size=100, seed=0, preferred=ml, preferred_share=0.5)
        self.assertTrue(ml & set(chosen))
        self.assertLessEqual(sum(chosen.values()), 60)
        self.assertLessEqual(sum(k for c, k in chosen.items() if c in ml), 30 + 6)


if __name__ == "__main__":
    unittest.main()
