#!/usr/bin/env python3
"""Fail-closed research-only NBA post-007 shadow runner.

Run only *after* a completed authenticated 18:00 main-chain capture.
Source board and fixed-slate main-chain JSON are never rewritten; all
candidate model artifact outputs are written to the GitHub Actions workspace
and retained as run artifacts. Does not fetch odds, notify, bet or deploy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import nba_shadow_model_integration as I
import nba_postcapture_crossplay_shadow as MODEL

BJ=ZoneInfo("Asia/Shanghai")
SLOT="1800"
MAX_SOURCE_AGE_MINUTES=120
SCHEMA="nba-postmarket-prospective-autorun-v1"

def clock(value):
    return I.D.clock(value)

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def gate(daily,sent,now,trigger_run=None):
    if now.tzinfo is None:
        raise ValueError("LOCAL_TIMEZONE_REQUIRED")
    bj=now.astimezone(BJ)
    # This trigger is only meaningful for the prior-day 18:00 capture.
    # All later or unrelated workflow_run triggers must not replay stale odds.
    if not 17 <= bj.hour <= 20:
        return {"status":"SKIPPED_NOT_EARLY_EVENING","reason":"BEIJING_18_SLOT_ONLY"}
    day=(bj.date()+timedelta(days=1)).isoformat()
    base=Path(daily)/day
    marker=Path(sent)/day/(SLOT+".json")
    req={
        "earlier_consensus":base/"1200"/"nba_market_consensus.json",
        "later_consensus":base/SLOT/"nba_market_consensus.json",
        "original_dynamic_five_market":base/SLOT/"nba_dynamic_five_market_shadow.json",
        "original_five_market_forecast":base/SLOT/"nba_five_market_forecast.json",
    }
    if not marker.is_file():
        return {"status":"SKIPPED_NO_SUCCESSFUL_1800_PRODUCTION_MARKER"}
    m=load(marker)
    if m.get("state")!="API_ACCEPTED_NOT_DEVICE_CONFIRMED":
        return {"status":"SKIPPED_1800_ORIGINAL_DELIVERY_NOT_ACCEPTED"}
    if trigger_run and str(m.get("run_id"))!=str(trigger_run):
        return {"status":"SKIPPED_UNRELATED_COMPLETED_PRODUCTION_RUN",
                "expected_run":str(m.get("run_id")),"incoming_run":str(trigger_run)}
    absent=[str(v) for v in req.values() if not v.is_file()]
    if absent:
        return {"status":"SKIPPED_INCOMPLETE_ORIGINAL_FROZEN_INPUT",
                "missing_paths":absent}
    earlier=load(req["earlier_consensus"])
    later=load(req["later_consensus"])
    frozen=load(req["original_dynamic_five_market"])
    t0=clock(earlier.get("collection_completed_at_utc"))
    t1=clock(later.get("collection_completed_at_utc"))
    tmodel=clock(frozen.get("model_capture_utc"))
    if not t0 or not t1 or not tmodel or not t0<t1<=now or not tmodel<t1:
        return {"status":"SKIPPED_UNVERIFIED_SOURCE_AND_MODEL_CLOCK_ORDER"}
    age=(now-t1).total_seconds()/60
    if age<0 or age>MAX_SOURCE_AGE_MINUTES:
        return {"status":"SKIPPED_STALE_007_1800_CAPTURE",
                "captured_utc":t1.isoformat(),"age_minutes":round(age,3)}
    if any(doc.get("target_date")!=day for doc in (earlier,later,frozen)):
        return {"status":"SKIPPED_WRONG_BEIJING_GAME_DATE"}
    if any(tip<=now for tip in (
        clock(game.get("tipoff_beijing")) or now for game in later.get("games",[])
    )):
        return {"status":"SKIPPED_ONE_OR_MORE_GAMES_ALREADY_TIPPED"}
    if len(later.get("games",[]))<1:
        return {"status":"SKIPPED_EMPTY_REAL_NBA_BOARD"}
    return {"status":"READY","target_date":day,
            "source_capture_utc":t1.isoformat(),
            "source_age_minutes":round(age,3),
            "original_delivery_marker_run":str(m.get("run_id")),
            "source_file_sha256":{k:I.sha(v) for k,v in req.items()}}

def validate_candidate(bridge,candidate,bridge_hash):
    """Verify every real future fixture BEFORE any Final exists.

    compare_candidate() scores only with official finals, so it cannot
    verify the candidate's pretip status alone. Here all 5 frozen independent
    model directions, signed lines and source clocks are checked.
    """
    if candidate.get("market_feature_source_sha256")!=bridge_hash:
        raise ValueError("PROSPECTIVE_BRIDGE_SHA_MISMATCH")
    if candidate.get("model_type")!="INDEPENDENT_POST_MARKET_SHADOW_MODEL":
        raise ValueError("NON_INDEPENDENT_MODEL_SUBSTITUTED")
    if not candidate.get("model_probabilities_are_frozen"):
        raise ValueError("UNSEALED_PROSPECTIVE_PREDICTION")
    now=clock(candidate.get("generated_at_utc"))
    if not now:
        raise ValueError("NEW_MODEL_CAPTURE_TIMESTAMP_NOT_PRESENT")
    original={str(x["game_id"]):x for x in bridge["games"]}
    predicted=I.D.unique_games(candidate)
    if set(original)!=set(predicted):
        raise ValueError("ORIGINAL_AND_CANDIDATE_NBA_BOARD_DIVERGED")
    totals={"games":0,"markets":0,"numerically_adjusted":0,"flipped_directions":0,
            "ineligible_direct_jc_id3_prices":0}
    for gid,old in original.items():
        new=predicted[gid]
        if not I.D.consistent_identity(new,old):
            raise ValueError("NEW_MODEL_TEAM_ID_SIDES_OR_TIP_DIVERGED")
        tip=clock(old.get("tipoff_beijing"))
        feature=clock(old["preintegration_model_input_features"]["market_features_effective_asof_utc"])
        if not tip or not feature or not feature<=now<tip:
            raise ValueError("CURRENT_MODEL_FEATURE_IS_FUTURE_OR_MATCH_STARTED")
        raw=old["three_play_five_target_judgments"]
        target=new.get("markets") or {}
        if set(raw)!=set(I.KEYS) or set(target)!=set(I.KEYS):
            raise ValueError("FIVE_ORIGINAL_DIRECT_INSTITUTION_TARGETS_MISSING")
        totals["games"]+=1
        for key in I.KEYS:
            a,b=raw[key],target[key]
            if b.get("market")!=key:
                raise ValueError("FROZEN_NEW_MARKET_KEY_MISMATCH")
            if not I.equal(a.get("direct_market_line"),b.get("line")):
                raise ValueError("DIRECT_JC_OR_CROWN_LINE_INCONSISTENT")
            if key.endswith("HANDICAP") and not I.equal(
                    a.get("signed_home_handicap"),b.get("signed_home_handicap")):
                raise ValueError("CROWN_OR_JC_SIGNED_HANDICAP_REVERSED")
            p=I.finite(b.get("probability_first_side"))
            if p is None or not 0<p<1:
                raise ValueError("NEW_SHADOW_MODEL_MUST_ISSUE_FIVE_PROBABILITIES")
            correct=(I.EXPECTED[key][0] if p>.5 else
                     I.EXPECTED[key][1] if p<.5 else "TIE")
            if b.get("direction")!=correct:
                raise ValueError("PROBABILITY_AND_DIRECTION_INCONSISTENT")
            if not b.get("direct_institution_quote_eligible"):
                totals["ineligible_direct_jc_id3_prices"]+=1
            if b.get("adjusted_from_current_model"):
                totals["numerically_adjusted"]+=1
                if a.get("original_direction") in I.EXPECTED[key] and (
                        a.get("original_direction")!=correct):
                    totals["flipped_directions"]+=1
            totals["markets"]+=1
    return totals

def run(daily,sent,params,out,trigger_run=None,now=None):
    now=now or datetime.now(timezone.utc)
    state=gate(daily,sent,now,trigger_run)
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    status=root/"auto_run_status.json"
    if state["status"]!="READY":
        status.write_text(json.dumps({**state,"research_only":True,
                                      "no_original_forecast_or_push_mutation":True},
                                    ensure_ascii=False,indent=2)+"\n")
        print("NBA_INDEPENDENT_POSTMARKET_SHADOW_SAFE_SKIP",state["status"])
        return state
    day=state["target_date"]
    bridge,out_copy,grade=I.run(daily,day,"1200",SLOT,root)
    bridge_path=root/"nba_shadow_model_bridge.json"
    param_path=Path(params)
    pinned=load(param_path)
    params_sha=hashlib.sha256(param_path.read_bytes()).hexdigest()
    # Future-owned model invocation: the only timestamp for the sealed new
    # predictions is the real time of THIS process, never a backdated quote.
    at=datetime.now(timezone.utc) if now is None else now
    if at<clock(bridge["games"][0]["late_capture_utc"]):
        raise ValueError("SHADOW_INFERENCE_PRECEDES_MARKET_CAPTURE")
    sha=hashlib.sha256(bridge_path.read_bytes()).hexdigest()
    candidate=MODEL.compute(bridge,pinned,at,sha)
    candidate["trained_parameters_sha256"]=params_sha
    candidate["actual_model_generation_verified_by_this_workflow"]=True
    candidate["research_automatic_no_live_production_fusion"]=True
    cand_path=root/"nba_postmarket_independent_candidate.json"
    cand_path.write_text(json.dumps(candidate,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    verified=validate_candidate(bridge,candidate,sha)
    frozen={
        **state,"status":"NEW_INDEPENDENT_SHADOW_FROZEN_PRETIP",
        "original_frozen_model_input_unchanged":True,
        "candidate_sha256":hashlib.sha256(cand_path.read_bytes()).hexdigest(),
        "candidate_generated_utc":at.isoformat(),
        "params_sha256":params_sha,"integrity":verified,
        "research_only":True,"no_original_forecast_or_push_mutation":True,
        "no_new_schedule_or_production_api_call":True,
        "no_five_market_probability_promotion":True,
        "official_outcome_accuracy_not_yet_known":True,
    }
    status.write_text(json.dumps(frozen,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print("NBA_ACTUAL_NEW_FIVE_PLAY_POSTMARKET_SHADOW_FROZEN",
          json.dumps({"date":day,**verified,
                      "new_model_utc":at.isoformat(),
                      "source_run":state["original_delivery_marker_run"]},ensure_ascii=False))
    return frozen

def selftest():
    from tempfile import TemporaryDirectory
    assert gate("/nonexistent","/nonexistent",datetime.fromisoformat(
        "2026-11-02T15:00:00+00:00"))["status"]=="SKIPPED_NOT_EARLY_EVENING"
    with TemporaryDirectory() as root:
        daily=Path(root)/"daily";sent=Path(root)/"sent";day="2027-11-03"
        base=daily/day
        (base/"1200").mkdir(parents=True)
        (base/"1800").mkdir(parents=True)
        (sent/day).mkdir(parents=True)
        now=datetime.fromisoformat("2027-11-02T10:30:00+00:00")
        raw={"collection_completed_at_utc":"2027-11-02T10:00:00Z",
             "target_date":day,
             "games":[{"tipoff_beijing":"2027-11-03T08:00:00+08:00"}]}
        old={**raw,"collection_completed_at_utc":"2027-11-02T04:00:00Z"}
        model={**raw,"model_capture_utc":"2027-11-02T09:55:00Z"}
        for p,src in ((base/"1200"/"nba_market_consensus.json",old),
                      (base/"1800"/"nba_market_consensus.json",raw),
                      (base/"1800"/"nba_dynamic_five_market_shadow.json",model),
                      (base/"1800"/"nba_five_market_forecast.json",{})):
            p.write_text(json.dumps(src))
        marker=sent/day/"1800.json"
        marker.write_text(json.dumps({"state":"API_ACCEPTED_NOT_DEVICE_CONFIRMED",
                                     "run_id":111}))
        assert gate(daily,sent,now,trigger_run="222")["status"]==(
            "SKIPPED_UNRELATED_COMPLETED_PRODUCTION_RUN")
        s=gate(daily,sent,now,trigger_run="111")
        assert s["status"]=="READY",s
        assert gate(daily,sent,datetime.fromisoformat(
            "2027-11-02T12:02:00Z"),trigger_run="111")["status"]==(
            "SKIPPED_STALE_007_1800_CAPTURE")
        raw["collection_completed_at_utc"]="2027-11-03T01:00:00Z"
        (base/"1800"/"nba_market_consensus.json").write_text(json.dumps(raw))
        assert gate(daily,sent,now,trigger_run="111")["status"]==(
            "SKIPPED_UNVERIFIED_SOURCE_AND_MODEL_CLOCK_ORDER")
    print("NBA_POSTMARKET_INDEPENDENT_AUTORUN_FAILCLOSED_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--daily-root",default="reports/daily")
    p.add_argument("--sent-root",default="reports/pushplus-sent")
    p.add_argument("--params",default="config/nba_shadow_three_play_params.json")
    p.add_argument("--trigger-run",default=None)
    p.add_argument("--out",default="/tmp/nba-automated-postmarket-shadow")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:selftest()
    else:run(a.daily_root,a.sent_root,a.params,a.out,a.trigger_run)
if __name__=="__main__":main()
