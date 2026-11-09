import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build import make_world
from diplomacy import agreement_pairs, make_diplomacy, pair, vote_alignment


class DiplomacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings, world = make_world()
        cls.config, cls.rows, cls.formal, cls.report = make_diplomacy(settings, world)
        cls.agreements = {a["id"]: a for a in cls.config["agreements"]}
        cls.relations = {(r["country_a"], r["country_b"]): r for r in cls.rows}

    def rel(self, a, b):
        return self.relations[pair(a, b)]

    def test_all_scenario_pairs_have_one_record(self):
        self.assertEqual(len(self.rows), 198 * 197 // 2)
        self.assertEqual(len(self.rows), len(self.relations))
        for row in self.rows:
            self.assertLess(row["country_a"], row["country_b"])
            self.assertIn(row["score_status"], ["game_estimate", "unknown"])
            if row["relation_score"] is not None:
                self.assertTrue(-100 <= row["relation_score"] <= 100)
            else:
                self.assertEqual(row["score_status"], "unknown")

    def test_historical_membership_and_no_later_blocs(self):
        for name, count in [("NATO", 28), ("CSTO", 7), ("EU", 27)]:
            self.assertEqual(len(self.agreements[name]["members"]), count)
        self.assertIn("UZB", self.agreements["CSTO"]["members"])
        self.assertIn("GBR", self.agreements["EU"]["members"])
        self.assertNotIn("HRV", self.agreements["EU"]["members"])
        for tag in ["FIN", "SWE", "MNE", "MKD", "UKR", "GEO"]:
            self.assertNotIn(tag, self.agreements["NATO"]["members"])
        for tag in ["VEN", "BOL"]:
            self.assertNotIn(tag, self.agreements["MERCOSUR"]["members"])
        self.assertNotIn("CHE", self.agreements["EEA"]["members"])
        for exclusion in self.config["explicit_exclusions"]:
            self.assertNotIn(exclusion["id"], self.agreements)
        self.assertEqual(len(self.agreements["EAC_CUSTOMS"]["members"]), 5)

    def test_partial_trade_entry_and_partner_sides(self):
        aanzfta = self.agreements["AANZFTA"]
        self.assertEqual(set(aanzfta["members"]), set("AUS NZL BRN MYS MMR PHL SGP VNM".split()))
        for pending in aanzfta["pending_members"]:
            self.assertGreater(pending["in_force_from"], "2010-01-01")
            self.assertNotIn(pending["tag"], aanzfta["members"])
        self.assertNotIn("AANZFTA", self.rel("THA", "AUS")["trade_agreements"])
        self.assertIn("AANZFTA", self.rel("VNM", "AUS")["trade_agreements"])
        aifta = self.agreements["ASEAN_INDIA_GOODS"]
        self.assertEqual(agreement_pairs(aifta), {pair("IND", t) for t in ["MYS", "SGP", "THA"]})
        self.assertNotIn("ASEAN_INDIA_GOODS", self.rel("MYS", "THA")["trade_agreements"])
        self.assertNotIn("ASEAN_INDIA_GOODS", self.rel("IND", "BRN")["trade_agreements"])
        self.assertNotIn("AFG", self.agreements["SAFTA"]["members"])
        self.assertNotIn("SYC", self.agreements["SADC_FTA"]["members"])

    def test_consultation_and_trade_do_not_create_defense_alliances(self):
        for ident in ["FPDA", "SCO", "ASEAN", "NATO_RUSSIA_COUNCIL", "RUSSIA_CHINA_PARTNERSHIP", "EU"]:
            self.assertFalse(self.agreements[ident]["mutual_defense"])
        self.assertTrue(self.agreements["EU"]["qualified_mutual_assistance"])
        self.assertEqual(self.rel("RUS", "CHN")["defense_agreements"], [])
        self.assertEqual(self.rel("USA", "ISR")["defense_agreements"], [])
        self.assertNotIn("ANZUS", self.rel("USA", "NZL")["defense_agreements"])
        self.assertIn("ANZUS", self.rel("USA", "AUS")["defense_agreements"])
        self.assertIn("ANZUS", self.rel("NZL", "AUS")["defense_agreements"])
        self.assertIn("US_THAILAND", self.rel("USA", "THA")["defense_agreements"])

    def test_context_overrides_outvote_affinity_and_institutional_bonuses(self):
        self.assertGreater(self.rel("IND", "PAK")["vote_alignment"], 0)
        self.assertLess(self.rel("IND", "PAK")["relation_score"], 0)
        self.assertIn("SAFTA", self.rel("IND", "PAK")["trade_agreements"])
        self.assertIn("NATO", self.rel("GRC", "TUR")["defense_agreements"])
        self.assertEqual(self.rel("GRC", "TUR")["relation_score"], 15)
        self.assertEqual(self.rel("RUS", "USA")["relation_score"], 10)
        for other in ["UKR", "GEO"]:
            relation = self.rel("RUS", other)
            self.assertLess(relation["relation_score"], 0)
            self.assertFalse(relation["active_interstate_war"])
            self.assertIn("RU_BILATERAL_FTA_" + other, relation["trade_agreements"])
        for other in ["AFG", "IRQ"]:
            self.assertGreater(self.rel("USA", other)["relation_score"], 0)
        self.assertEqual(self.rel("KOR", "PRK")["political_status"], "armistice")

    def test_no_future_votes_or_inactive_treaties(self):
        self.assertEqual(self.report["votes_2009"], 14680)
        self.assertEqual(self.report["roll_calls_2009"], 84)
        self.assertEqual(self.report["un_countries"], 192)
        self.assertLess(self.report["un_date_max"], "2010-01-01")
        for treaty in self.formal:
            self.assertLessEqual(treaty["observed_start_date"], "2010-01-01")
            if treaty["observed_end_date"]:
                self.assertGreaterEqual(treaty["observed_end_date"], "2010-01-01")
            self.assertFalse(treaty["legal_scope_individually_reviewed"])
        self.assertEqual(self.report["estimated_pairs"] + self.report["unknown_score_pairs"], 19503)
        self.assertIsNone(self.rel("VAT", "TWN")["relation_score"])
        self.assertIsNone(self.rel("VAT", "TWN")["active_interstate_war"])

    def test_alignment_is_not_imputed_for_absences(self):
        score, common = vote_alignment({1: 1, 2: 0, 3: -1, 4: 1}, {1: -1, 2: 0, 3: 1, 5: 1}, 3)
        self.assertAlmostEqual(score, -1 / 3)
        self.assertEqual(common, 3)
        score, common = vote_alignment({1: 1, 2: 0}, {1: 1, 3: 0}, 2)
        self.assertIsNone(score)
        self.assertEqual(common, 1)


if __name__ == "__main__":
    unittest.main()
