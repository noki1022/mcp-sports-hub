#!/usr/bin/env python3
"""Post-007 capture independently RE-GENERATED five-market research forecasts.

Time-strict, single-pass, CPU-only local inference. Starts with the existing
independent model and applies a separately earlier-season TRAINED market
movement correction (if the validation-approved coefficient is nonzero).
Every new output is a genuinely new model invocation, not a copy passed off
as new. Never affects original probabilities/PushPlus. Market composition is
not manufactured into a trend. No ROI, EV, price-difference or bet selection.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import math

import nba_shadow_model_integration as I
import nba_three_play_direction_shadow as D
from nba_shadow_three_play_train import SCHEMA as PARAM_SCHEMA, phi, logistic, logit

SCHEMA="nba-independent-postmarket-five-play-shadow-v1"
CAP_ABSOLUTE_PROBABILITY_CHANGE=.035
MAX_HOME_STRENGTH_MOVEMENT=4.0
MAX_TOTAL_MOVEMENT=6.0

def bounded(v,limit):
    return max(-limit,min(limit,v))

def new_prob(p,logit_change):
    return max(.001,min(.999,logistic(logit(p)+logit_change)))

def market_probability(mean,sigma,threshold):
    if sigma is None or sigma<=0 or mean is None or threshold is None:
        return None
    return max(.001,min(.999,phi((mean-threshold)/sigma)))

def verify_parameters(params):
    if (params.get("schema_version")!=PARAM_SCHEMA
            or params.get("research_shadow_only") is not True
            or params.get("production_model_weights_not_authorized") is not True
            or params.get("zero_profit_arbitrage_or_EV_training") is not True
            or params.get("actual_crosschecked_independent_games",0)<1200
            or params.get("exact_original_quote_update_times_known") is not False):
        raise ValueError("UNVERIFIED_TRAINING_PARAMETER_PROVENANCE")
    co=params.get("coefficients") or {}
    if set(co)!={"ml","margin","total"}:
        raise ValueError("MISSING_ONE_OF_THREE_TRAINED_MARKET_TARGETS")
    for key,val in co.items():
        coef=I.finite(val.get("effective_beta"))
        full=I.finite(val.get("trained_beta"))
        weight=I.finite(val.get("validation_selected_weight"))
        if (coef is None or full is None or weight not in (0,.25,.5,1.)
                or abs(coef-full*weight)>1e-7 or
                val.get("validation_precommitted_gain")!=.0005):
            raise ValueError("TRAINING_COEFFICIENT_CHANGED_OR_WAS_NOT_SELECTED")
    if not params.get("train_last_date")<params.get("validation_first_date") or not (
        params.get("validation_last_date")<params.get("retrospective_later_first_date")):
        raise ValueError("TRAINING_VIOLATES_CHRONOLOGY")
    return {key:co[key]["effective_beta"] for key in co}

def compute(bridge,params,now,source_sha):
    coefficients=verify_parameters(params)
    if bridge.get("schema_version")!=I.SCHEMA or not bridge.get("research_read_only_sidecar"):
        raise ValueError("ORIGINAL_BRIDGE_NOT_VALIDATED")
    if bridge.get("promotion_status")!="BLOCKED_UNTIL_INDEPENDENT_PROSPECTIVE_OUTCOME_LIFT":
        raise ValueError("BRIDGE_WAS_ALREADY_FUSED")
    if not bridge.get("original_five_market_independent_probabilities_changed") is False:
        raise ValueError("BRIDGE_ORIGINAL_MODEL_MUTATED")
    if now.tzinfo is None:
        raise ValueError("UNWARE_CAPTURE_CLOCK")
    seen=set();rows=[];model_adjusted=0;invalid=0
    for game in bridge.get("games",[]):
        gid=str(game.get("game_id") or "")
        if not gid or gid in seen:raise ValueError("REPEATED_EVENT_ID_IN_BRIDGE")
        seen.add(gid)
        tip=D.clock(game.get("tipoff_beijing"))
        f=game.get("preintegration_model_input_features") or {}
        ready=D.clock(f.get("market_features_effective_asof_utc"))
        original_clock=D.clock(game.get("original_model_capture_utc"))
        if not tip or not ready or not original_clock or not original_clock<=ready<=now<tip:
            raise ValueError("NEW_MODEL_NOT_AFTER_REAL_MARKET_OR_BEFORE_NBA_TIP")
        spread=f.get("spread_home_strength_direction_code")
        total=f.get("total_expected_scoring_direction_code")
        delta_spread=I.finite(f.get("spread_home_strength_median_line_change_points"))
        delta_total=I.finite(f.get("total_expected_scoring_line_change_points"))
        margin_slope=I.finite(coefficients["margin"])
        total_slope=I.finite(coefficients["total"])
        moneyline_slope=I.finite(coefficients["ml"])
        spread_eligible=spread in (-1,1) and delta_spread is not None and (
            delta_spread>0 if spread==1 else delta_spread<0)
        total_eligible=total in (-1,1) and delta_total is not None and (
            delta_total>0 if total==1 else delta_total<0)
        delta_m=bounded(delta_spread,MAX_HOME_STRENGTH_MOVEMENT)*margin_slope if spread_eligible else 0.
        delta_t=bounded(delta_total,MAX_TOTAL_MOVEMENT)*total_slope if total_eligible else 0.
        base=game["three_play_five_target_judgments"]
        if set(base)!=set(I.KEYS):raise ValueError("ORIGINAL_FIVE_TARGETS_NOT_COMPLETE")
        # Derive ORIGINAL numerical strength central values from consistent
        # Gaussian inverse only when possible; avoid creating arbitrary means
        # by simply shifting every existing first-side model p with an
        # independent trained logit shift, preserving exactly the JC/ID3 line.
        # sigma is not archived in the bridge, so a research-only conservative
        # calibration transfer is used for ATS/Totals; no claim it is accurate
        # until paired true OOS scoring.
        sig_margin=15.55
        sig_total=19.47
        markets={}
        for key in I.KEYS:
            record=base[key]
            baseline=I.finite(record.get("independent_first_side_probability"))
            if key=="JINGCAI_WIN" and baseline is None:
                baseline=I.finite(record.get("original_independent_model_moneyline_home_probability"))
            line=record.get("direct_market_line")
            signed=record.get("signed_home_handicap")
            status=record.get("source_quality")
            original=record.get("original_direction")
            reasons=list(record.get("integration_blockers") or [])
            has_direct_quote=status=="ASOF_MODEL_AND_LINE_VERIFIED"
            if baseline is None or not 0<baseline<1:
                result=None
                reasons.append("NO_ACTUAL_INDEPENDENT_MODEL_PROBABILITY")
            elif key=="JINGCAI_WIN":
                # Previously fitted logit gradient for +2 HOME-favorable points.
                result=new_prob(baseline,moneyline_slope*
                    bounded(delta_spread,MAX_HOME_STRENGTH_MOVEMENT)/2) if spread_eligible else baseline
            elif key.endswith("HANDICAP"):
                if I.finite(signed) is None:
                    result=None;reasons.append("NO_SIGNED_HOME_COVER_LINE")
                else:
                    # Shift the original CDF's z-score by the predicted margin
                    # point correction, preserving the original Gaussian z.
                    z=math.sqrt(2)*inverse_erf(2*baseline-1)
                    result=max(.001,min(.999,phi(z+delta_m/sig_margin)))
            else:
                if I.finite(line) is None:
                    result=None;reasons.append("NO_VERIFIED_TOTAL_LINE")
                else:
                    z=math.sqrt(2)*inverse_erf(2*baseline-1)
                    result=max(.001,min(.999,phi(z+delta_t/sig_total)))
            if result is not None and baseline is not None:
                result=max(.001,min(.999,baseline+bounded(
                    result-baseline,CAP_ABSOLUTE_PROBABILITY_CHANGE)))
            if result is not None and abs(result-baseline)>1e-12:
                model_adjusted+=1
            if not has_direct_quote:invalid+=1
            direction=(I.EXPECTED[key][0] if result is not None and result>.5 else
                       I.EXPECTED[key][1] if result is not None and result<.5 else
                       "TIE" if result is not None else None)
            markets[key]={
                "market":key,"line":line,"signed_home_handicap":signed,
                "probability_first_side":round(result,10) if result is not None else None,
                "direction":direction,
                "baseline_independent_first_side_probability":baseline,
                "original_direction":original,
                "direct_institution_quote_eligible":has_direct_quote,
                "research_source_status":"Genuine_PRETIP_DIRECT" if has_direct_quote else "OFFICIAL_QUOTE_NOT_CERTIFIED",
                "adjusted_from_current_model":bool(
                    baseline is not None and result is not None and abs(result-baseline)>1e-12),
                "training_coefficient_transfer_not_independently_proven":True,
                "injury_research_quality":game.get("injury_context_frozen_quality"),
                "source_reasons":reasons,
            }
        rows.append({
            "game_id":gid,"nba_game_id":game.get("nba_game_id"),
            "home_team":game.get("home_team"),"away_team":game.get("away_team"),
            "tipoff_beijing":game.get("tipoff_beijing"),
            "market_feature_capture_utc":ready.isoformat(),
            "new_prediction_generated_at_utc":now.isoformat(),
            "jingcai_number":game.get("jingcai_number"),
            "market_movement_features":f,"markets":markets,
        })
    return {
        "schema_version":SCHEMA,
        "model_type":"INDEPENDENT_POST_MARKET_SHADOW_MODEL",
        "model_version":"P0_EXISTING_TEAM_MODEL_PLUS_EARLIER_TRAINED_CROSSPLAY_RESEARCH",
        "target_date":bridge["target_date"],
        "generated_at_utc":now.isoformat(),
        "market_feature_source_sha256":source_sha,
        "trained_parameters_sha256":None,
        "model_probabilities_are_frozen":True,
        "games":rows,"game_count":len(rows),
        "changed_probability_market_count":model_adjusted,
        "uncertified_direct_institution_quote_count":invalid,
        "separately_training_validated_live_model_improvement":False,
        "historical_stage_coefficients_transfer_not_live_verified":True,
        "market_trend_not_used_when_unverified":True,
        "base_existing_independent_team_model_unchanged":True,
        "official_injury_adjustment_not_replaced":True,
        "zero_bets_zero_ev_zero_roi_arbitrage":True,
        "auto_promote_into_production":False,
        "pushplus_report_modified":False,
    }

def inverse_erf(x):
    # Safe inverse Phi by monotonic bisection: 50 iterations, deterministic,
    # no numpy/scipy dependency or learned extra parameters at runtime.
    v=max(-.999999,min(.999999,x))
    lo,hi=-6.,6.
    for _ in range(50):
        mid=(lo+hi)/2
        if math.erf(mid)<v:lo=mid
        else:hi=mid
    return (lo+hi)/2

def selftest():
    assert abs(phi(math.sqrt(2)*inverse_erf(2*.82-1))-.82)<1e-10
    assert D.num(False) is None
    assert bounded(-6,4)==-4
    params={"schema_version":PARAM_SCHEMA,"research_shadow_only":True,
            "production_model_weights_not_authorized":True,
            "zero_profit_arbitrage_or_EV_training":True,
            "actual_crosschecked_independent_games":1312,
            "exact_original_quote_update_times_known":False,
            "train_last_date":"2025-01-10","validation_first_date":"2025-01-11",
            "validation_last_date":"2025-02-28","retrospective_later_first_date":"2025-03-01",
            "coefficients":{
                k:{"effective_beta":v,"trained_beta":v,
                   "validation_selected_weight":1.,
                   "validation_precommitted_gain":.0005}
                for k,v in (("ml",.1),("margin",.6),("total",.5))}}
    base={"schema_version":I.SCHEMA,
          "target_date":"2026-11-03","research_read_only_sidecar":True,
          "promotion_status":"BLOCKED_UNTIL_INDEPENDENT_PROSPECTIVE_OUTCOME_LIFT",
          "original_five_market_independent_probabilities_changed":False,
          "games":[{"game_id":"a","nba_game_id":"espn1",
            "home_team":"主","away_team":"客",
            "tipoff_beijing":"2026-11-03T08:00+08:00",
            "original_model_capture_utc":"2026-11-02T09:58:00Z",
            "preintegration_model_input_features":{
                "market_features_effective_asof_utc":"2026-11-02T10:00:00Z",
                "spread_home_strength_direction_code":1,
                "spread_home_strength_median_line_change_points":2,
                "total_expected_scoring_direction_code":1,
                "total_expected_scoring_line_change_points":3},
            "three_play_five_target_judgments":{
                k:{"independent_first_side_probability":.6,
                   "original_independent_model_moneyline_home_probability":.6,
                   "direct_market_line":230.5 if k.endswith("TOTAL") else
                       -7.5 if k.endswith("HANDICAP") else None,
                   "signed_home_handicap":-7.5 if k.endswith("HANDICAP") else None,
                   "original_direction":I.EXPECTED[k][0],
                   "source_quality":"ASOF_MODEL_AND_LINE_VERIFIED"}
                for k in I.KEYS}}]}
    now=datetime.fromisoformat("2026-11-02T10:10:00+00:00")
    z=compute(base,params,now,"a"*64)
    assert z["game_count"]==1 and z["changed_probability_market_count"]==5
    for k in I.KEYS:
        assert z["games"][0]["markets"][k]["probability_first_side"]>.6
    nope=json.loads(json.dumps(base))
    nope["games"][0]["preintegration_model_input_features"]["spread_home_strength_direction_code"]=None
    n=compute(nope,params,now,"a"*64)
    assert n["games"][0]["markets"]["JINGCAI_WIN"]["probability_first_side"]==.6
    try:compute(base,params,datetime.fromisoformat("2026-11-03T01:00:00Z".replace("Z","+00:00")),"a"*64)
    except ValueError as e:
        assert str(e)=="NEW_MODEL_NOT_AFTER_REAL_MARKET_OR_BEFORE_NBA_TIP"
    else:raise AssertionError("AFTER_TIP_PROBABILITY_ACCEPTED")
    print("NBA_POST_CAPTURE_FIVE_MARKET_NEW_SHADOW_MODEL_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--bridge",required=False)
    p.add_argument("--params",default="config/nba_shadow_three_play_params.json")
    p.add_argument("--out",default="/tmp/nba-postmarket-new-shadow.json")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:
        selftest();return
    if not args.bridge:raise SystemExit("BRIDGE_INPUT_REQUIRED")
    path=Path(args.bridge)
    now=datetime.now(timezone.utc)
    orig=I.load(path);params=I.load(args.params)
    candidate=compute(orig,params,now,hashlib.sha256(path.read_bytes()).hexdigest())
    candidate["trained_parameters_sha256"]=hashlib.sha256(
        Path(args.params).read_bytes()).hexdigest()
    Path(args.out).write_text(json.dumps(candidate,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print("NBA_POST_CAPTURE_NEW_MODEL_FROZEN",json.dumps({
        "games":candidate["game_count"],"modified_five_market_probability_count":
        candidate["changed_probability_market_count"],"missing_direct_market":
        candidate["uncertified_direct_institution_quote_count"],
        "model_promotion":False},ensure_ascii=False))

if __name__=="__main__":main()
