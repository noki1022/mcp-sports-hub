#!/usr/bin/env python3
"""No-leakage, disjoint season window, input integrity regression."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import sports_point_in_time_admission as A

CONFIG = {
    "fit_before_utc": "2023-01-01T00:00:00Z",
    "tune_before_utc": "2024-01-01T00:00:00Z",
    "calibration_before_utc": "2025-01-01T00:00:00Z",
    "holdout_before_utc": "2026-01-01T00:00:00Z",
    "embargo_days": 7,
}

def fixture(sport="basketball", mid="10", kickoff="2025-06-10T12:00:00Z"):
    decision = "2025-06-10T09:00:00Z" if kickoff == "2025-06-10T12:00:00Z" else "2022-12-24T09:00:00Z"
    return {
        "sport": sport, "match_id": mid, "kickoff_utc": kickoff, "decision_utc": decision,
        "source_sha256": "a" * 64, "capture_run_id": "100", "model_version": "frozen-v1",
        "features": {"multi_book_home_line": {
            "value": {"median": -3.5}, "observed_at_utc": decision, "available_at_utc": decision}},
    }

def label(sport="basketball", mid="10", verified="2025-06-11T14:00:00Z"):
    return {"sport": sport, "match_id": mid, "result_verified_utc": verified,
            "result_source_sha256": "b"*64, "verified_final": True,
            "outcome": {"home_won": True}}

class TestAdmission(unittest.TestCase):
    def test_valid_and_manifest_has_no_outcome(self):
        manifest = A.admit([fixture()], [label()], CONFIG)
        self.assertEqual(manifest["counts"]["holdout"], 1)
        self.assertNotIn("outcome", manifest["records"][0])
        self.assertTrue(manifest["no_same_game_outcomes_in_model_inputs"])
    def test_injury_available_only_after_forecast_rejected(self):
        f = fixture()
        f["features"]["multi_book_home_line"]["available_at_utc"] = "2025-06-10T10:00:00Z"
        with self.assertRaisesRegex(ValueError, "FEATURE_AVAILABLE_AFTER"):
            A.admit([f], [label()], CONFIG)
    def test_postkickoff_quote_rejected(self):
        f = fixture()
        f["decision_utc"] = "2025-06-10T13:00:00Z"
        with self.assertRaisesRegex(ValueError, "POST_KICKOFF"):
            A.admit([f], [label()], CONFIG)
    def test_final_result_in_feature_key_rejected(self):
        f = fixture()
        f["features"]["final_score"] = f["features"]["multi_book_home_line"]
        with self.assertRaisesRegex(ValueError, "POSTGAME_OR_TARGET"):
            A.admit([f], [label()], CONFIG)
    def test_hidden_nested_outcome_rejected(self):
        f = fixture()
        f["features"]["multi_book_home_line"]["value"]["future_result"] = 121
        with self.assertRaisesRegex(ValueError, "POSTGAME_OR_TARGET"):
            A.admit([f], [label()], CONFIG)
    def test_naive_timestamp_rejected(self):
        f = fixture()
        f["features"]["multi_book_home_line"]["observed_at_utc"] = "2025-06-10T09:00:00"
        with self.assertRaisesRegex(ValueError, "NAIVE_TIMESTAMP"):
            A.admit([f], [label()], CONFIG)
    def test_no_source_hash_or_result_hash_rejected(self):
        f = fixture()
        f["source_sha256"] = "unknown"
        with self.assertRaisesRegex(ValueError, "MISSING_RAW_SOURCE_HASH"):
            A.admit([f], [label()], CONFIG)
        l = label()
        l["result_source_sha256"] = ""
        with self.assertRaisesRegex(ValueError, "RESULT_SOURCE_HASH_MISSING"):
            A.admit([fixture()], [l], CONFIG)
    def test_result_same_game_wrong_identity_rejected(self):
        with self.assertRaisesRegex(ValueError, "IDENTITY_SET_MISMATCH"):
            A.admit([fixture()], [label(mid="11")], CONFIG)
    def test_unverified_result_rejected(self):
        l = label()
        l["verified_final"] = False
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_RESULT"):
            A.admit([fixture()], [l], CONFIG)
    def test_duplicate_result_and_capture_rejected(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_RESULT"):
            A.admit([fixture()], [label(), label()], CONFIG)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_FEATURE"):
            A.admit([fixture(), fixture()], [label()], CONFIG)
    def test_embargo_never_admitted(self):
        f = fixture(kickoff="2023-01-03T12:00:00Z")
        f["decision_utc"] = "2023-01-03T09:00:00Z"
        f["features"]["multi_book_home_line"]["observed_at_utc"] = f["decision_utc"]
        f["features"]["multi_book_home_line"]["available_at_utc"] = f["decision_utc"]
        l = label(verified="2023-01-04T14:00:00Z")
        result = A.admit([f], [l], CONFIG)
        self.assertEqual(result["usable_count"], 0)
        self.assertEqual(result["counts"]["embargo"], 1)
    def test_football_valid_with_distinct_identity(self):
        x = fixture(sport="football", mid="123")
        y = label(sport="football", mid="123")
        self.assertEqual(A.admit([x], [y], CONFIG)["usable_count"], 1)
    def test_bad_boundaries_rejected(self):
        c = copy.deepcopy(CONFIG)
        c["tune_before_utc"] = "2023-01-02T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "SPLITS_OVERLAP"):
            A.admit([fixture()], [label()], c)

if __name__ == "__main__":
    unittest.main()
