#!/usr/bin/env python3
"""No-outcome contract tests; historical as-of fixtures are NOT forward scores."""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import nba_dual_independent_stage as ST
import nba_independent_market_shadow as MO
import nba_multibook_crossplay_signals as BOOK
import nba_dual_model_slot_seal as SE
import nba_dual_model_final_2130_grade as GR

ROOT=Path(__file__).resolve().parents[1]
def asof(v):return datetime.fromisoformat(v.replace("Z","+00:00"))
def prediction(stage_folder,now,slot):
    p=Path(stage_folder)
    data={n:json.loads((p/(n+".json")).read_text()) for n in ("joined","consensus","jingcai")}
    prev=json.loads((p/"previous.json").read_text()) if (p/"previous.json").is_file() else None
    history=json.loads((p/"history.json").read_text()) if (p/"history.json").is_file() else None
    safe_injury=json.loads((p/"injury.json").read_text())
    prior_injury=json.loads((p/"injury_history.json").read_text())
    result=MO.compute(data["joined"],data["consensus"],data["jingcai"],
                      prev,now,slot,history=history,
                      injury=safe_injury,injury_history=prior_injury)
    assert all(g["research_official_injury_asof"]["injury_adjusted_probability"] is None
               for g in result["games"])
    assert all(g["research_official_injury_asof"]["core_player_impact_points"] is None
               for g in result["games"])
    result["input_sha256"]={n:ST.sha(p/(n+".json")) for n in data}
    if prev:result["input_sha256"]["previous"]=ST.sha(p/"previous.json")
    if (p/"history.json").is_file():
        result["input_sha256"]["history"]=ST.sha(p/"history.json")
    result["input_sha256"]["injury"]=ST.sha(p/"injury.json")
    result["input_sha256"]["injury_history"]=ST.sha(p/"injury_history.json")
    assert result["original_model_inputs_read"] is False
    assert result["postgame_data_read"] is False
    assert all(len(g["markets"])==5 for g in result["games"])
    assert all("model_probability" not in str(g["market_strength_features"]) for g in result["games"])
    return result

def run():
    with TemporaryDirectory() as temp:
        tmp=Path(temp)
        # Actual archived 007 original 18:00 source; as-of clock is TEST ONLY
        # and no "fake future" candidate is published or scored.
        day,slot,marker=ST.marker(ROOT,"41425286650")
        assert (day,slot)==("2026-11-03","1800")
        simulated=asof("2026-11-02T10:12:00Z")
        manifest=ST.stage(ROOT,"41425286650",tmp/"stage18",simulated)
        assert manifest["original_model_output_never_mounted"] is True
        p=tmp/"stage18"
        assert not (p/"nba_five_market_forecast.json").exists()
        assert not (p/"nba_priority_model.json").exists()
        assert not (p/"settlement.json").exists()
        assert (p/"injury.json").exists() and (p/"injury_history.json").exists()
        assert "original_model" not in (p/"injury.json").read_text()
        assert all(g["research_official_injury_asof"]["injury_adjusted_probability"] is None
                   for g in generated["games"])
        assert "nba_independent_market_shadow.py" in (p/"analysis/nba_independent_market_shadow.py").name
        generated=prediction(p,simulated,slot)
        assert generated["game_count"]==15
        assert len(generated["games"][0]["markets"])==5
        assert generated["multibook_candidate_numerically_separate_not_promoted"] is True
        assert (p/"history.json").is_file()
        assert not (p/"analysis/nba_dual_model_final_2130_grade.py").exists()
        assert not (p/"analysis/nba_shadow_three_play_train.py").exists()
        assert (p/"analysis/nba_multibook_crossplay_signals.py").exists()
        assert all(x["research_multibook_features"]["not_yet_a_validated_forecast_uplift"]
                   for x in generated["games"])
        assert any(x["research_model_candidates"]["ROBUST_MULTIBOOK"] for x in generated["games"])
        assert all((not x["research_model_candidates"]["ROBUST_MULTIBOOK"]
                   or set(x["research_model_candidates"]["ROBUST_MULTIBOOK"]).issubset(
                       set(x["markets"]))) for x in generated["games"])
        assert generated["multibook_paired_sources_used"]>=1
        # Actual, independently completed ORIGINAL 21:30 source, replayed
        # strictly as of the clock before Nov3 games. This is a deterministic
        # archival CONTRACT test, not a newly frozen prospective result.
        real_2130=asof("2026-11-02T13:42:00Z")
        manifest21=ST.stage(ROOT,"41453596277",tmp/"real-valid-2130",real_2130)
        shadow21=prediction(tmp/"real-valid-2130",real_2130,"2130")
        assert manifest21["archive_slot_is_21:30_final"] is True
        assert shadow21["game_count"]==15
        assert shadow21["multibook_paired_sources_used"]>=2
        assert all(len(g["markets"])==5 for g in shadow21["games"])
        assert all(len(g["research_model_candidates"]["ROBUST_MULTIBOOK"])>=3
                   for g in shadow21["games"])
        assert all(g["research_multibook_features"]["full_spread"]["historical_capture_count"]>=1
                   for g in shadow21["games"])
        assert all(g["research_model_candidates"]["ROBUST_MULTIBOOK"][key]["market"]==key
                   for g in shadow21["games"]
                   for key in g["research_model_candidates"]["ROBUST_MULTIBOOK"])
        first=next(g for g in shadow21["games"] if g["game_id"]=="728298")
        assert first["research_multibook_features"]["full_spread"]["independent_books"]>=8
        assert first["research_multibook_features"]["full_spread"]["latest_capture_utc"]==(
            "2026-11-02T13:31:56.225645+00:00")
        print("REAL_NOV3_15_GAME_2130_MULTIBOOK_FIVE_MARKET_CONTRACT_ONLY_PASS",
              shadow21["multibook_paired_sources_used"],
              sum(len(g["research_model_candidates"]["ROBUST_MULTIBOOK"])
                  for g in shadow21["games"]))
        assert "source" not in generated or generated.get("postgame_data_read") is False
        # Hash changes must not be silently accepted as an identical freeze.
        found=generated["input_sha256"]["joined"]
        assert len(found)==64 and found==ST.sha(p/"joined.json")
        # Critical: the Nov 1 archive called "2130" was actually generated
        # at 21:21 Beijing. It must NOT be relabeled as a valid 21:30 exam.
        day2,slot2,marker2=ST.marker(ROOT,"41310772662")
        assert (day2,slot2)==("2026-11-02","2130")
        try:
            ST.stage(ROOT,"41310772662",tmp/"wrong-early-final",
                     asof("2026-11-01T13:25:00Z"))
        except ValueError as exc:
            assert "SKIP_EARLY_OR_WRONG_DAY_2130_CAPTURE" in str(exc)
        else:
            raise AssertionError("OLD_2121_FINAL_INCORRECTLY_PASSED_AS_2130")
        # No prediction may retroactively be manufactured from the
        # prior day's prematurely labeled 21:30 capture.
        existing=tmp/"ledger/2026-11-02/2130"
        existing.mkdir(parents=True)
        try:
            SE.seal(tmp,ROOT,tmp/"ledger","2026-11-02","2130",
                    "41310772662",asof("2026-11-01T13:30:00Z"))
        except ValueError as exc:
            assert "FIRST_FREEZE_ALREADY_SEALED_NEVER_OVERWRITE" in str(exc)
        else:raise AssertionError("ARCHIVED_FINAL_COULD_BE_OVERWRITTEN")
        print("HISTORICAL_2121_MISLABELED_2130_CORRECTLY_QUARANTINED")
        # Grade from an independent synthetic locked structure, not by
        # invoking the market model with completed game scores.
        original={"target_date":"2026-11-03","games":[{"game_id":"a",
            "home_team":"H","away_team":"A","markets":{
                "JINGCAI_WIN":{"status":"DIRECTION_ISSUED","direction":"HOME_WIN",
                               "model_direction_probability":.6},
                "JINGCAI_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"HOME_COVER",
                                    "line":-5.5,"signed_home_handicap":-5.5,
                                    "model_direction_probability":.55},
                "JINGCAI_TOTAL":{"status":"DIRECTION_ISSUED","direction":"UNDER",
                                 "line":220.5,"model_direction_probability":.51},
                "CROWN_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"AWAY_COVER",
                                  "line":5.5,"signed_home_handicap":-5.5,
                                  "model_direction_probability":.55},
                "CROWN_TOTAL":{"status":"DIRECTION_ISSUED","direction":"OVER",
                               "line":220.5,"model_direction_probability":.59}}}]}
        candidate={"target_date":"2026-11-03","games":[{"game_id":"a",
            "home_team":"H","away_team":"A","markets":{
                key:{"market":key,"line":row.get("line"),
                     "signed_home_handicap":row.get("signed_home_handicap"),
                     "direction":row["direction"],"first_side_probability":.6}
                for key,row in original["games"][0]["markets"].items()}}]}
        truth={"schema_version":"nba-five-market-settlement-v1","beijing_date":"2026-11-03",
               "games":[{"game_id":"a","home_team":"H","away_team":"A",
                         "home_points":120,"away_points":110}]}
        candidate["games"][0]["research_model_candidates"] = {
            "ROBUST_MULTIBOOK": {
                key:{"market":key,"line":row.get("line"),
                     "signed_home_handicap":row.get("signed_home_handicap"),
                     "direction":("HOME_WIN" if key=="JINGCAI_WIN" else
                                  "HOME_COVER" if key.endswith("HANDICAP") else "OVER"),
                     "first_side_probability":.65}
                for key,row in original["games"][0]["markets"].items()
            }}
        result=GR.score(original,candidate,{},truth)
        assert all(v["paired_graded"]==1 for v in result["five_market_by_market"].values())
        assert all(v["same_game_line_paired_n"]==1
                   for v in result["multibook_research_candidate_paired_vs_original_and_shadow"].values())
        assert result["candidate_is_not_official_second_model_answer"] is True
        assert result["multibook_research_candidate_paired_vs_original_and_shadow"][
            "JINGCAI_WIN"]["multibook_candidate_hits"] == 1
        # Research variant must never be graded against another JC/Crown
        # handicap line, however small the difference looks.
        candidate["games"][0]["research_model_candidates"]["ROBUST_MULTIBOOK"][
            "CROWN_HANDICAP"]["signed_home_handicap"]=-4.5
        try:
            GR.score(original,candidate,{},truth)
        except ValueError as ex:
            assert "RESEARCH_MULTIBOOK_SCORE_LINE_OR_SIDE_CHANGED" in str(ex)
        else:
            raise AssertionError("RESEARCH_MULTIBOOK_USED_CHANGED_DIRECT_MARKET_LINE")
        assert result["five_market_by_market"]["JINGCAI_WIN"]["original_hits"]==1
        assert result["five_market_by_market"]["JINGCAI_TOTAL"]["original_hits"]==0
        assert result["five_market_by_market"]["CROWN_HANDICAP"]["original_hits"]==0
        assert result["not_18_or_00_30_or_03_30_model_scores"] is True
        print("REAL_007_1800_SOURCE_ONLY_AND_EARLY_2130_QUARANTINE_CONTRACT_PASS",
              generated["game_count"],4)
    print("INDEPENDENT_MODEL_AND_SINGLE_2130_EXAM_WITHOUT_SCORE_LEAK_SELFTEST_PASS")
if __name__=="__main__":run()
