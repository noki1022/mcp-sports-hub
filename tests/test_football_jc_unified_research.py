#!/usr/bin/env python3
"""Offline contract: no score/low-odds favorite is used to drive predictions."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_unified_research as research
import football_jc_probability as core
NOW=datetime(2026,11,6,13,tzinfo=timezone.utc)
TIP=NOW+timedelta(hours=6)

def samples():
    fixture={"match_id":"3075305","jc_number":"周五002","league":"德乙",
             "home_team":"甲队","away_team":"乙队","kickoff_beijing":TIP.isoformat(),
             "injury_report_state":"UNVERIFIED","injury_source_facts":[{"player_id":"999"}],
             "jc_markets":{"had":[1.9,3.5,4.5],
                  "hhad":{"signed_home_handicap":-1,"odds":[3.8,3.4,1.8]},
                  "ttg":[23.,8.4,4.75,3.4,4.,6.5,10.,12.]}}
    snapshot={"schema_version":"football-jc-007-v1",
        "beijing_date":"2026-11-06","captured_at_utc":NOW.isoformat(),
        "games":[fixture]}
    shared={"source_sha256":research.digest(snapshot),
            "captured_at_utc":NOW.isoformat(),
            "generated_at_utc":(NOW+timedelta(seconds=25)).isoformat()}
    base={"model_version":core.VERSION,**shared,"games":[{
            "match_id":"3075305","jc_number":"周五002","home_team":"甲队",
            "away_team":"乙队","kickoff_beijing":TIP.isoformat(),
            "status":"RESEARCH_READY","goal_expectation":{"home":1.45,"away":1.30},
            "data_quality":{"home_recent":5,"away_recent":5,"h2h":1}}]}
    asian={"model_version":"football-jc-poisson-asian-assimilation-v4",**shared,
            "games":[{"match_id":"3075305","jc_number":"周五002",
            "home_team":"甲队","away_team":"乙队","kickoff_beijing":TIP.isoformat(),
            "status":"RESEARCH_READY","goal_expectation":{"home":1.5,"away":1.25},
            "market_assimilation":{"status":"APPLIED_BOUNDED_007_REAL_ASIAN"}}]}
    return snapshot,base,asian

class TestIndependentFirst(unittest.TestCase):
    def test_probabilities_are_nonprice_and_no_score_or_bet_tip(self):
        s,b,a=samples()
        before=deepcopy((s,b,a))
        out=research.analyze(s,b,a)
        self.assertEqual((s,b,a),before)
        row=out["games"][0]
        self.assertEqual(out["counts"]["independent_ready"],1)
        self.assertTrue(out["independent_probabilities_do_not_read_prices"])
        self.assertIsNone(row["exact_score_prediction"])
        self.assertIsNone(row["total_goals_two_buckets_recommendation"])
        self.assertEqual(row["betting_value_status"],"UNAVAILABLE_UNTIL_OUT_OF_SAMPLE_CALIBRATION")
        for key in ("had","hhad","ttg"):
            self.assertAlmostEqual(sum(row["independent_probabilities"][key].values()),1,places=5)
        self.assertAlmostEqual(row["asian_price_competitor"]["market_minus_independent_goals"]["home"],.05)

    def test_adversarial_odds_change_does_not_change_independent_probability(self):
        s,b,a=samples()
        old=research.analyze(s,b,a)["games"][0]
        changed=deepcopy(s)
        offered=changed["games"][0]["jc_markets"]
        offered["had"]=[6.,4.8,1.28]
        offered["hhad"]["odds"]=[1.25,3.5,6.2]
        offered["ttg"]=[2.2,3.7,6.,11.,25.,70.,100.,150.]
        b2=deepcopy(b);a2=deepcopy(a)
        for doc in (b2,a2):doc["source_sha256"]=research.digest(changed)
        a2["games"][0]["goal_expectation"]={"home":.65,"away":2.2}
        new=research.analyze(changed,b2,a2)["games"][0]
        self.assertEqual(old["independent_probabilities"],new["independent_probabilities"])
        self.assertNotEqual(old["official_market_diagnostics"],new["official_market_diagnostics"])
        self.assertIsNone(new["official_market_diagnostics"]["had"]["recommendation"])

    def test_missing_price_allows_price_independent_forecast(self):
        s,b,a=samples()
        s["games"][0]["jc_markets"]={"had":None,"ttg":None,"hhad":None}
        for doc in (b,a):doc["source_sha256"]=research.digest(s)
        row=research.analyze(s,b,a)["games"][0]
        self.assertIsNone(row["independent_probabilities"]["hhad"])
        self.assertIsNotNone(row["independent_probabilities"]["ttg"])
        self.assertEqual(row["official_market_diagnostics"]["had"]["state"],"NO_COMPARABLE_OFFICIAL_PRICE")

    def test_source_tampering_and_future_information_rejected(self):
        s,b,a=samples()
        s["games"][0]["home_team"]="错误球队"
        with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):research.analyze(s,b,a)
        s,b,a=samples()
        s["games"][0]["kickoff_beijing"]=(NOW-timedelta(minutes=1)).isoformat()
        for doc in (b,a):
            doc["source_sha256"]=research.digest(s)
            doc["games"][0]["kickoff_beijing"]=s["games"][0]["kickoff_beijing"]
        self.assertEqual(research.analyze(s,b,a)["games"][0]["reason"],
                         "NOT_PREMATCH_AT_ALL_SOURCE_AND_MODEL_TIMES")

    def test_insufficient_independent_history_never_fills_from_prices(self):
        s,b,a=samples()
        b["games"][0]["status"]="INSUFFICIENT_FORM"
        row=research.analyze(s,b,a)["games"][0]
        self.assertEqual(row["reason"],"INDEPENDENT_FEATURE_BASELINE_NOT_READY")
        s,b,a=samples()
        row=research.analyze(s,b,a)["games"][0]
        self.assertFalse(row["feature_evidence"]["injuries_verified"])
        self.assertEqual(row["feature_evidence"]["injury_reported_unconfirmed"],1)

if __name__=="__main__":unittest.main()
