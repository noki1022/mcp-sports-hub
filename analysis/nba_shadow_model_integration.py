#!/usr/bin/env python3
"""Read-only five-play market-direction -> existing NBA model integration contract.

Uses exclusively archived *real* 007 company snapshots and the original
frozen model. Does not select odds, arbitrage, train with results, change
probabilities, edit live forecasts, make bets, or add scheduled actions.
A separate candidate report is intentionally a sidecar, not live model input.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import nba_three_play_direction_shadow as D

SCHEMA="nba-shadow-five-play-model-bridge-v1"
KEYS=D.KEYS
EXPECTED={"JINGCAI_WIN":("HOME_WIN","AWAY_WIN"),
          "JINGCAI_HANDICAP":("HOME_COVER","AWAY_COVER"),
          "JINGCAI_TOTAL":("OVER","UNDER"),
          "CROWN_HANDICAP":("HOME_COVER","AWAY_COVER"),
          "CROWN_TOTAL":("OVER","UNDER")}
MIN_EVENTS_FOR_REVIEW=100
MIN_DAYS_FOR_REVIEW=24


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(v):
    if v is None or isinstance(v,bool):
        return None
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):
        return None


def equal(a,b):
    x,y=finite(a),finite(b)
    return (x is None and y is None) or (x is not None and y is not None and abs(x-y)<1e-6)


def market_compatibility(key, original, dynamic):
    """Never convert signed JC/Crown handicap to an unsigned/favorite label."""
    issues=[]
    if original.get("market")!=key:
        issues.append("ORIGINAL_MARKET_TYPE_MISMATCH")
    if original.get("status")=="DIRECTION_ISSUED":
        if original.get("direction") not in EXPECTED[key]:
            issues.append("ORIGINAL_DIRECTION_INVALID")
        quote=D.clock(original.get("captured_at_utc"))
        if quote is None:
            issues.append("ORIGINAL_MARKET_CAPTURE_MISSING")
        if not equal(original.get("line"),dynamic.get("line")):
            issues.append("CURRENT_DIRECT_LINE_DIFFERS_FROM_FROZEN")
        if key.endswith("HANDICAP"):
            signed=finite(original.get("signed_home_handicap"))
            source_line=finite(original.get("line"))
            required=(source_line if key.startswith("JINGCAI") else -source_line
                      if source_line is not None else None)
            if signed is None or not equal(signed,required):
                issues.append("DIRECT_HOME_SIGNED_SPREAD_NOT_VERIFIED")
            if not equal(signed,dynamic.get("signed_home_handicap")):
                issues.append("DYNAMIC_SIGNED_HOME_SPREAD_CONFLICT")
        if key.startswith("CROWN") and (
            str(original.get("source_id"))!="3" or
            original.get("source") not in ("007_CROWN_ID3","007_CROWN_ID3_ARCHIVED_PRETIP")):
            issues.append("CROWN_SOURCE_MUST_BE_007_ID3")
        if key.startswith("JINGCAI") and original.get("source")!="007_JINGCAI":
            issues.append("JINGCAI_SOURCE_NOT_007")
        if (dynamic.get("frozen_direction")!=original.get("direction")):
            issues.append("FROZEN_DIRECTION_DIFFERS_FROM_ORIGINAL")
    elif original.get("direction") is not None:
        issues.append("NONISSUED_ORIGINAL_HAS_DIRECTION")
    return issues


def build(early,late,dynamic,five,hashes):
    """Fail closed on cross-source identity and time; preserve every model row."""
    day=late.get("target_date")
    if not day or any(doc.get("target_date")!=day for doc in (early,dynamic,five)):
        raise ValueError("FOUR_SOURCE_DATE_MISMATCH")
    if five.get("schema_version")!="nba-five-markets-v1" or (
        dynamic.get("schema_version")!="nba-dynamic-five-market-shadow-v2"):
        raise ValueError("UNKNOWN_ORIGINAL_MODEL_SCHEMA")
    freeze=D.clock(dynamic.get("five_market_freeze_utc"))
    generation=D.clock(five.get("analysis_generated_at_utc"))
    if freeze is None or generation is None or freeze!=generation:
        raise ValueError("FIVE_MARKET_GENERATION_AND_SHADOW_FREEZE_MISMATCH")
    original_model_time=D.clock(dynamic.get("model_capture_utc"))
    if original_model_time is None or original_model_time>freeze:
        raise ValueError("INVALID_INDEPENDENT_MODEL_CAPTURE_TIME")
    recorded=D.evaluate(early,late,dynamic)
    if recorded["game_count"]!=len(late.get("games",[])):
        raise ValueError("MODEL_AND_MARKET_IDENTITY_OR_TIME_REJECTED")
    frozen=D.unique_games(five)
    observed=D.unique_games(dynamic)
    consensus=D.unique_games(late)
    if set(frozen)!=set(observed) or set(frozen)!=set(consensus):
        raise ValueError("ORIGINAL_FIVE_MARKET_COHORT_CHANGED")
    early_end=D.clock(early.get("collection_completed_at_utc"))
    late_end=D.clock(late.get("collection_completed_at_utc"))
    if not early_end or not late_end or not early_end<late_end<=freeze:
        raise ValueError("MARKET_CAPTURE_CHRONOLOGY_INVALID")
    result=[]
    source_count=Counter()
    annotated=deepcopy(five)
    byid={x["game_id"]:x for x in annotated["games"]}
    for e in recorded["games"]:
        gid=e["game_id"]
        f=frozen[gid]; d=observed[gid]; m=consensus[gid]
        if not D.consistent_identity(f,d) or not D.consistent_identity(f,m):
            raise ValueError("ORIGINAL_MODEL_LINEUP_IDENTITY_CHANGED")
        if not D.clock(f.get("tipoff_beijing"))>freeze:
            raise ValueError("MARKET_DATA_NOT_PRETIP")
        ms=f.get("markets") or {}
        dm=d.get("markets") or {}
        if set(ms)!=set(KEYS) or set(dm)!=set(KEYS):
            raise ValueError("FIVE_TARGET_PLAY_KEYS_MISSING")
        technical={}
        for key in KEYS:
            raw=ms[key]; previous=dm[key]
            issues=market_compatibility(key,raw,previous)
            if previous.get("market_data_status")=="PRETIP_VALID" and (
                previous.get("probability_status")=="PRETIP_VALID"):
                p=finite(previous.get("first_side_probability"))
                if p is None or not 0<=p<=1:
                    issues.append("FROZEN_PROBABILITY_NOT_A_REAL_NUMBER")
                if key=="JINGCAI_WIN" and not equal(
                        p,(d.get("independent_model") or {}).get("home_win_probability")):
                    issues.append("INDEPENDENT_MONEYLINE_MODEL_MISMATCH")
            capture=D.clock(previous.get("quote_capture_utc"))
            if raw.get("status")=="DIRECTION_ISSUED" and (
                    not capture or capture>=freeze or capture>=D.clock(f.get("tipoff_beijing"))):
                issues.append("DIRECT_QUOTE_CAPTURE_NOT_BEFORE_FREEZE")
            asof_verified=(not issues and previous.get("probability_status")=="PRETIP_VALID"
                           and previous.get("market_data_status")=="PRETIP_VALID")
            baseline=e["independent_five_market_judgments"][key]
            evidence=baseline.get("directional_evidence")
            if key.endswith("HANDICAP"):
                # Explicitly avoid transferring HOME-WIN trend to HOME-COVER.
                evidence="MARGIN_DIRECTION_ONLY_NOT_SPREAD_COVER_PREDICTION"
            technical[key]={
                "market":key,
                "original_direction":raw.get("direction"),
                "original_source":raw.get("source"),
                "source_id":raw.get("source_id"),
                "direct_market_line":raw.get("line"),
                "signed_home_handicap":raw.get("signed_home_handicap"),
                "original_frozen_model_probability":previous.get("frozen_direction_probability"),
                "independent_first_side_probability":previous.get("first_side_probability"),
                "original_model_status":previous.get("probability_status"),
                "original_quote_or_market_invalid_reasons":previous.get("invalid_reasons") or [],
                "original_independent_model_moneyline_home_probability":(
                    (d.get("independent_model") or {}).get("home_win_probability")
                    if key=="JINGCAI_WIN" else None),
                "market_direction_context":baseline.get("market_direction_signal"),
                "market_direction_evidence":evidence,
                "source_quality":"ASOF_MODEL_AND_LINE_VERIFIED" if asof_verified else
                    "NO_AUTHORIZED_NUMERIC_ADJUSTMENT",
                "integration_blockers":issues,
                "confidence_delta_pp":0.0,
                "model_direction_unchanged":True,
                "market_probability_not_mislabeled_as_model_probability":True,
            }
            source_count[key+":" + technical[key]["source_quality"]]+=1
            # This COPY has a neutral, isolated research namespace. The
            # original five-market field contents, signs, directions and
            # numerical probabilities are never altered by the bridge.
            byid[gid]["markets"][key]["shadow_direction_context_v1"]={
                "market_direction_evidence":evidence,
                "market_direction_context":baseline.get("market_direction_signal"),
                "quality":technical[key]["source_quality"],
                "delta_pp":0.0,
                "production_fusion_allowed":False,
            }
        spread=e["observed_institution_line_directions"]["full_spread"]
        totals=e["observed_institution_line_directions"]["full_total"]
        encode=lambda x: (1 if x=="RISING" else -1 if x=="FALLING" else
                          0 if x=="STABLE" else None)
        # The interface is usable by a *NEW* model inference run at or after
        # late 007 company collection. Never pretend those later quotes
        # existed when an earlier independent forecast was computed.
        model_input_features={
            "market_features_effective_asof_utc":late_end.isoformat(),
            "new_model_prediction_must_be_generated_not_before_utc":late_end.isoformat(),
            "existing_independent_model_generated_utc":original_model_time.isoformat(),
            "historical_model_originally_saw_these_features":False,
            "features_available_for_original_model_time":late_end<=original_model_time,
            "spread_home_strength_direction_code":encode(spread["direction"]),
            "spread_home_strength_median_line_change_points":(
                spread["median_change"] if spread["status"]=="VERIFIED_PAIRED_COMPANY_TREND"
                else None),
            "spread_same_company_quote_pairs":spread["paired_companies"],
            "spread_direction_agreement":spread.get("agreement_fraction"),
            "total_expected_scoring_direction_code":encode(totals["direction"]),
            "total_expected_scoring_line_change_points":(
                totals["median_change"] if totals["status"]=="VERIFIED_PAIRED_COMPANY_TREND"
                else None),
            "total_same_company_quote_pairs":totals["paired_companies"],
            "total_direction_agreement":totals.get("agreement_fraction"),
            "no_moneyline_probability_manufactured_from_spread":True,
            "no_prediction_probability_numerically_changed":True,
        }
        result.append({
            "game_id":gid,"nba_game_id":f.get("nba_game_id"),
            "preintegration_model_input_features":model_input_features,
            "home_team":f.get("home_team"),"away_team":f.get("away_team"),
            "jingcai_number":f.get("jingcai_number"),
            "tipoff_beijing":f.get("tipoff_beijing"),
            "early_capture_utc":e["early_capture_utc"],
            "late_capture_utc":e["late_capture_utc"],
            "original_model_capture_utc":original_model_time.isoformat(),
            "original_model_frozen_utc":freeze.isoformat(),
            "market_information_available_before_original_model":late_end<=original_model_time,
            "injury_context_frozen_quality":(d.get("injury_context") or {}).get("quality"),
            "market_movement":e["observed_institution_line_directions"],
            "three_play_five_target_judgments":technical,
            "original_five_prediction_unchanged":True,
        })
    annotated["shadow_bridge_schema"]=SCHEMA
    annotated["shadow_bridge_mode"]="READ_ONLY_RESEARCH_ANNOTATION"
    annotated["production_shadow_fusion_enabled"]=False
    annotated["original_five_market_forecast_sha256"]=hashes["original_five_market_forecast"]
    summary={
        "schema_version":SCHEMA,"target_date":day,
        "game_count":len(result),"games":result,
        "quality_counts":dict(sorted(source_count.items())),
        "source_sha256":dict(sorted(hashes.items())),
        "market_capture_after_original_model_in_some_cases":any(
            not x["market_information_available_before_original_model"] for x in result),
        "original_five_market_independent_probabilities_changed":False,
        "research_read_only_sidecar":True,
        "prepared_model_input_contract":True,
        "five_play_weights":{"jingcai":0.7,"crown_id3":0.3},
        "model_probability_fusion_ready":False,
        "model_features_originally_used_in_frozen_model":False,
        "model_feature_availability_requires_NEW_prediction_after_market_capture":True,
        "number_of_games_with_newer_market_input_than_original_model":sum(
            not x["market_information_available_before_original_model"] for x in result),
        "promotion_status":"BLOCKED_UNTIL_INDEPENDENT_PROSPECTIVE_OUTCOME_LIFT",
        "promotion_requirements":{
            "minimum_independent_games_per_target_play":MIN_EVENTS_FOR_REVIEW,
            "minimum_distinct_beijing_dates":MIN_DAYS_FOR_REVIEW,
            "must_use_official_posttip_scores":True,
            "must_measure_paired_proper_scoring_lift":True,
            "must_validate_true_original_asof_model_input_availability":True,
            "no_backfill_of_unobserved_company_movements":True,
        },
        "no_ev_no_roi_no_price_arbitrage":True,
        "no_production_model_scheduler_pushplus_cloudflare_changes":True,
    }
    return summary,annotated


def grade(bridge,settlement):
    """Independent outcome-label evaluation of frozen SAME-SLOT directions.

    One event/market per frozen bridge. No model refitting or post-game odds.
    Settlement must independently match game ID, teams and explicit scores.
    """
    if settlement is None:
        return {"status":"AWAITING_INDEPENDENT_COMPLETED_SCORES",
                "graded_game_markets":0,"by_market":{k:{"n":0} for k in KEYS},
                "production_promotion_allowed":False}
    if settlement.get("beijing_date")!=bridge.get("target_date"):
        raise ValueError("SETTLEMENT_TARGET_DAY_CONFLICT")
    ss={}
    for g in settlement.get("games",[]):
        key=str(g.get("game_id") or "")
        if not key or key in ss:raise ValueError("DUPLICATE_SETTLEMENT_GAME")
        ss[key]=g
    bins={k:[] for k in KEYS};rejected=Counter()
    for g in bridge["games"]:
        score=ss.get(g["game_id"])
        if score is None:
            rejected["NO_OFFICIAL_GAME_RESULT"]+=1;continue
        if (score.get("home_team"),score.get("away_team"))!=(
                g["home_team"],g["away_team"]):
            rejected["SCORE_TEAM_IDENTITY_MISMATCH"]+=1;continue
        hp,ap=score.get("home_points"),score.get("away_points")
        if (not isinstance(hp,int) or isinstance(hp,bool) or
                not isinstance(ap,int) or isinstance(ap,bool) or hp<50 or ap<50):
            rejected["UNVERIFIED_COMPLETED_SCORE"]+=1;continue
        for k,feature in g["three_play_five_target_judgments"].items():
            p=finite(feature.get("independent_first_side_probability"))
            if p is None or not 0<=p<=1 or feature.get("source_quality")!="ASOF_MODEL_AND_LINE_VERIFIED":
                rejected["UNVERIFIED_FROZEN_SOURCE_"+k]+=1;continue
            if k=="JINGCAI_WIN":delta=hp-ap
            elif k.endswith("HANDICAP"):
                line=finite(feature.get("signed_home_handicap"))
                if line is None:
                    rejected["INVALID_SIGNED_HOME_LINE_"+k]+=1;continue
                delta=hp-ap+line
            else:
                line=finite(feature.get("direct_market_line"))
                if line is None:
                    rejected["INVALID_TOTAL_LINE_"+k]+=1;continue
                delta=hp+ap-line
            if abs(delta)<1e-8:
                rejected["PUSH_"+k]+=1;continue
            first=delta>0
            direction=EXPECTED[k][0] if first else EXPECTED[k][1]
            actual=int(first)
            prediction=feature.get("original_direction")
            if prediction not in EXPECTED[k]:
                rejected["FROZEN_DIRECTION_INVALID_"+k]+=1;continue
            evidence=feature.get("market_direction_evidence") or "UNKNOWN"
            bins[k].append({"game_id":g["game_id"],"day":bridge["target_date"],
                 "frozen_model_probability_first_side":p,
                 "observed_first_side":actual,
                 "market_evidence":evidence,
                 "model_direction":prediction,"observed_direction":direction,
                 "hit":int(prediction==direction),"brier":(p-actual)**2})
    stats={}
    for k,items in bins.items():
        per={}
        groups={label:[z for z in items if z["market_evidence"]==label]
                for label in sorted({z["market_evidence"] for z in items})}
        for label,rs in groups.items():
            per[label]={"independent_games":len(rs),
                "hits":sum(z["hit"] for z in rs),
                "accuracy":round(sum(z["hit"] for z in rs)/len(rs),6),
                "brier":round(sum(z["brier"] for z in rs)/len(rs),7)}
        stats[k]={"n":len(items),"hits":sum(z["hit"] for z in items),
                 "accuracy":round(sum(z["hit"] for z in items)/len(items),6)
                       if items else None,
                 "brier":round(sum(z["brier"] for z in items)/len(items),7)
                       if items else None,
                 "by_market_direction_evidence":per}
    return {
        "status":"FROZEN_SHADOW_DIRECTION_SCORECARD" if any(bins.values()) else
                  "NO_SETTLED_VALID_FROZEN_MARKETS",
        "target_date":bridge["target_date"],"by_market":stats,
        "graded_game_markets":sum(x["n"] for x in stats.values()),
        "distinct_games":len({r["game_id"] for group in bins.values() for r in group}),
        "reject_reasons":dict(sorted(rejected.items())),
        "promotion_status":"BLOCKED_NO_FROZEN_PROBABILITY_UPLIFT_ESTIMATOR",
        "production_promotion_allowed":False,
        "not_accuracy_lift_vs_new_model":True,
        "all_five_original_independent_model_probabilities_unchanged":True,
        "results_used_as_features":False,
    }


def compare_candidate(bridge,candidate,settlement,source_bridge_sha):
    """Pre-register NEXT-PREDICTION variant and grade only strict real pairs.

    A candidate has to be a new model invocation AFTER market features exist,
    with exactly the original JC/ID3 threshold and forecast before NBA tip.
    A declared artifact hash is NOT proof of historical archival provenance:
    require independent GitHub run timestamp inspection before promotion.
    """
    missing={"status":"AWAITING_GENUINE_SEALED_NEW_MODEL_AND_OFFICIAL_FINALS",
             "paired_by_market":{k:{"n":0,"model_brier":None,"shadow_brier":None,
                "shadow_minus_model_brier":None,"original_accuracy":None,
                "shadow_accuracy":None} for k in KEYS},
             "independent_games":0,"distinct_beijing_days":0,
             "promotion_allowed":False,
             "external_github_immutability_confirmed":False,
             "numeric_candidate_generated":False}
    if candidate is None or settlement is None:
        return missing
    if candidate.get("target_date")!=bridge["target_date"]:
        raise ValueError("CANDIDATE_TARGET_DATE_NOT_MATCHED")
    if candidate.get("model_type")!="INDEPENDENT_POST_MARKET_SHADOW_MODEL":
        raise ValueError("MARKET_CONSENSUS_IS_NOT_INDEPENDENT_MODEL")
    if candidate.get("market_feature_source_sha256")!=source_bridge_sha:
        raise ValueError("CANDIDATE_INPUT_FEATURE_DIGEST_NOT_MATCHED")
    if candidate.get("model_probabilities_are_frozen") is not True:
        raise ValueError("UNFROZEN_CANDIDATE_NOT_ADMISSIBLE")
    if settlement.get("beijing_date")!=bridge["target_date"]:
        raise ValueError("CANDIDATE_SETTLEMENT_DAY_CONFLICT")
    pred_time=D.clock(candidate.get("generated_at_utc"))
    if pred_time is None:raise ValueError("INVALID_CANDIDATE_GENERATION_CLOCK")
    preds=D.unique_games(candidate)
    finals=D.unique_games(settlement)
    originals={x["game_id"]:x for x in bridge["games"]}
    if set(preds)!=set(originals):
        raise ValueError("NEW_MODEL_AND_ORIGINAL_GAME_IDS_DIFFER")
    result={k:[] for k in KEYS}
    refused=Counter()
    for gid,original in originals.items():
        new=preds[gid]
        if not D.consistent_identity(new,original):
            # Ignore Jingcai number differences, but not event identity
            raise ValueError("NEW_MODEL_TEAM_TIP_OR_ESPN_ID_CONFLICT")
        tip=D.clock(original.get("tipoff_beijing"))
        features=original["preintegration_model_input_features"]
        feature_t=D.clock(features["market_features_effective_asof_utc"])
        if not feature_t or not tip or not feature_t<=pred_time<tip:
            raise ValueError("NEW_MODEL_PREDICTION_NOT_AFTER_FEATURE_AND_BEFORE_TIP")
        score=finals.get(gid)
        if score is None:
            refused["NO_VERIFIED_FINAL"]+=1
            continue
        if (score.get("home_team"),score.get("away_team"))!=(
                original["home_team"],original["away_team"]):
            raise ValueError("SCORE_TEAM_IDENTITY_CONFLICT")
        hp,ap=score.get("home_points"),score.get("away_points")
        if (not isinstance(hp,int) or isinstance(hp,bool)
                or not isinstance(ap,int) or isinstance(ap,bool)
                or hp<50 or ap<50):
            refused["NO_VERIFIED_FINAL"]+=1
            continue
        original_market=original["three_play_five_target_judgments"]
        newmarkets=new.get("markets") or {}
        if set(newmarkets)!=set(KEYS):
            raise ValueError("NEW_MODEL_FIVE_PLAY_KEYS_NOT_COMPLETE")
        for key in KEYS:
            baseline=original_market[key]; newrow=newmarkets[key]
            if newrow.get("market")!=key:raise ValueError("CANDIDATE_MARKET_KEY_CHANGED")
            if not equal(newrow.get("line"),baseline.get("direct_market_line")):
                raise ValueError("CANDIDATE_DIRECT_JC_OR_CROWN_LINE_CHANGED")
            if key.endswith("HANDICAP") and not equal(
                    newrow.get("signed_home_handicap"),baseline.get("signed_home_handicap")):
                raise ValueError("CANDIDATE_HOME_SIGN_INVERTED")
            p0=finite(baseline.get("independent_first_side_probability"))
            p1=finite(newrow.get("probability_first_side"))
            if (baseline["source_quality"]!="ASOF_MODEL_AND_LINE_VERIFIED"
                    or p0 is None or p1 is None or not 0<p0<1 or not 0<p1<1):
                refused["INVALID_PAIR_"+key]+=1
                continue
            expected=EXPECTED[key][0] if p1>.5 else EXPECTED[key][1] if p1<.5 else "TIE"
            if newrow.get("direction")!=expected:
                raise ValueError("NEW_MODEL_DIRECTION_PROBABILITY_CONTRADICTION")
            if key=="JINGCAI_WIN":delta=hp-ap
            elif key.endswith("HANDICAP"):delta=hp-ap+baseline["signed_home_handicap"]
            else:delta=hp+ap-baseline["direct_market_line"]
            if abs(delta)<1e-8:
                refused["PUSH_"+key]+=1
                continue
            y=int(delta>0)
            old_dir=baseline["original_direction"]
            if old_dir not in EXPECTED[key]:
                refused["ORIGINAL_DIRECTION_INVALID_"+key]+=1
                continue
            result[key].append({
                "event":gid,"day":bridge["target_date"],"y":y,
                "original_probability":p0,"candidate_probability":p1,
                "original_hit":int(old_dir==EXPECTED[key][1-y]),
                "candidate_hit":int(expected==EXPECTED[key][1-y]),
            })
    summary={}
    for key,values in result.items():
        n=len(values)
        a=lambda fn:round(sum(fn(x) for x in values)/n,8) if n else None
        summary[key]={
            "n":n,
            "model_brier":a(lambda x:(x["original_probability"]-x["y"])**2),
            "shadow_brier":a(lambda x:(x["candidate_probability"]-x["y"])**2),
            "shadow_minus_model_brier":a(lambda x:
                 (x["candidate_probability"]-x["y"])**2-
                 (x["original_probability"]-x["y"])**2),
            "original_accuracy":a(lambda x:x["original_hit"]),
            "shadow_accuracy":a(lambda x:x["candidate_hit"]),
            "source_duplicated_games_are_not_independent":True,
        }
    games={r["event"] for rs in result.values() for r in rs}
    return {
        "status":"RESEARCH_ONLY_CHRONOLOGICAL_PAIRED_GRADE",
        "paired_by_market":summary,
        "independent_games":len(games),
        "distinct_beijing_days":1 if games else 0,
        "rejected":dict(sorted(refused.items())),
        "model_feature_time_before_new_candidate":True,
        "candidate_outcome_label_not_used_as_model_feature":True,
        "candidate_generation_declared_not_independently_archival_proven":True,
        "external_github_immutability_confirmed":False,
        "promotion_allowed":False,
        "promotion_sample_requirements":{
            "minimum_independent_games_per_market":MIN_EVENTS_FOR_REVIEW,
            "minimum_distinct_days":MIN_DAYS_FOR_REVIEW,
            "must_compare_future_prospective_cohort":True
        }
    }


def run(root,date,earlier,later,out):
    base=Path(root)/date
    paths={"earlier_consensus":base/earlier/"nba_market_consensus.json",
           "later_consensus":base/later/"nba_market_consensus.json",
           "original_dynamic_five_market":base/later/"nba_dynamic_five_market_shadow.json",
           "original_five_market_forecast":base/later/"nba_five_market_forecast.json"}
    hashes={k:sha(v) for k,v in paths.items()}
    a,b,c,d=(load(paths[k]) for k in paths)
    summary,copy=build(a,b,c,d,hashes)
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    result=root/"nba_shadow_model_bridge.json"
    result.write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    sidecar=root/"nba_five_market_shadow_preintegration.json"
    sidecar.write_text(json.dumps(copy,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    settlement=Path("reports/five-market-settled")/date/"settlement.json"
    grade_report=grade(summary,load(settlement) if settlement.is_file() else None)
    (root/"nba_shadow_direction_scorecard.json").write_text(json.dumps(grade_report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("NBA_SHADOW_FIVE_PLAY_MODEL_BRIDGE",json.dumps({
        "target_date":date,"games":summary["game_count"],
        "quality":summary["quality_counts"],
        "grade_status":grade_report["status"],
        "model_fusion_ready":False,"production_changes":False},ensure_ascii=False))
    return summary,copy,grade_report


def selftest():
    # No fake fitted confidence: even perfect illustrative agreement remains
    # a context signal; all five independent numerical probabilities stay as is.
    from tempfile import TemporaryDirectory
    from nba_three_play_direction_shadow import selftest as directional_selftest
    directional_selftest()
    assert equal(-7.5,-7.5) and not equal(-7.5,+7.5)
    z={"target_date":"2026-11-03","games":[{
        "game_id":"g","home_team":"H","away_team":"A",
        "three_play_five_target_judgments":{
            k:{"original_direction":EXPECTED[k][0],
               "source_quality":"ASOF_MODEL_AND_LINE_VERIFIED",
               "direct_market_line":220.5 if k.endswith("TOTAL") else -3.5 if k.endswith("HANDICAP") else None,
               "signed_home_handicap":-3.5 if k.endswith("HANDICAP") else None,
               "independent_first_side_probability":.65,
               "market_direction_evidence":"CORROBORATES_MONEYLINE_SIDE"}
            for k in KEYS}}]}
    finals={"beijing_date":"2026-11-03","games":[{
        "game_id":"g","home_team":"H","away_team":"A",
        "home_points":116,"away_points":108}]}
    g=grade(z,finals)
    assert g["graded_game_markets"]==5
    assert all(g["by_market"][k]["n"]==1 for k in KEYS)
    assert g["by_market"]["JINGCAI_WIN"]["hits"]==1
    assert g["by_market"]["JINGCAI_TOTAL"]["hits"]==1
    assert grade(z,None)["graded_game_markets"]==0
    assert all(k in EXPECTED for k in KEYS)
    assert grade(z,{"beijing_date":"2026-11-03","games":[]})["graded_game_markets"]==0
    inverted=deepcopy(z)
    inverted["games"][0]["three_play_five_target_judgments"]["CROWN_HANDICAP"]["signed_home_handicap"]=-12
    assert grade(inverted,finals)["by_market"]["CROWN_HANDICAP"]["hits"]==0
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/"x";path.write_text("original")
        old=sha(path)
        path.write_text("changed")
        assert sha(path)!=old
    assert compare_candidate(z,None,finals,"a"*64)["independent_games"]==0
    # Strictly chronologically re-generated synthetic model after source capture.
    sample=deepcopy(z)
    sample["games"][0]["nba_game_id"]="test-event"
    sample["games"][0]["tipoff_beijing"]="2026-11-03T08:00:00+08:00"
    sample["games"][0]["preintegration_model_input_features"]={
        "market_features_effective_asof_utc":"2026-11-02T10:00:00Z"}
    candidate={"target_date":"2026-11-03",
               "model_type":"INDEPENDENT_POST_MARKET_SHADOW_MODEL",
               "market_feature_source_sha256":"a"*64,
               "model_probabilities_are_frozen":True,
               "generated_at_utc":"2026-11-02T10:30:00Z",
               "games":[{
                 "game_id":"g","nba_game_id":"test-event",
                 "home_team":"H","away_team":"A",
                 "tipoff_beijing":"2026-11-03T08:00:00+08:00",
                 "markets":{
                   k:{"market":k,
                      "line":(220.5 if k.endswith("TOTAL")
                               else -3.5 if k.endswith("HANDICAP") else None),
                      "signed_home_handicap":-3.5 if k.endswith("HANDICAP") else None,
                      "probability_first_side":.67,
                      "direction":EXPECTED[k][0]} for k in KEYS}}]}
    paired=compare_candidate(sample,candidate,finals,"a"*64)
    assert paired["paired_by_market"]["JINGCAI_WIN"]["n"]==1
    assert paired["paired_by_market"]["JINGCAI_WIN"]["shadow_brier"]<paired[
        "paired_by_market"]["JINGCAI_WIN"]["model_brier"]
    broken=deepcopy(candidate)
    broken["games"][0]["markets"]["CROWN_HANDICAP"]["signed_home_handicap"]=3.5
    try:compare_candidate(sample,broken,finals,"a"*64)
    except ValueError as exc:
        assert str(exc)=="CANDIDATE_HOME_SIGN_INVERTED"
    else:raise AssertionError("WRONG_SIDE_CROWN_ADMITTED")
    late=deepcopy(candidate)
    late["generated_at_utc"]="2026-11-03T02:00:00Z"
    try:compare_candidate(sample,late,finals,"a"*64)
    except ValueError as exc:
        assert str(exc)=="NEW_MODEL_PREDICTION_NOT_AFTER_FEATURE_AND_BEFORE_TIP"
    else:raise AssertionError("POSTTIP_MODEL_ADMITTED")
    assert compare_candidate(sample,candidate,None,"a"*64)["independent_games"]==0
    print("NBA_SHADOW_MODEL_BRIDGE_FAIL_CLOSED_SELFTEST_PASS")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--daily-root",default="reports/daily")
    parser.add_argument("--date",default="2026-11-03")
    parser.add_argument("--earlier-slot",default="1200")
    parser.add_argument("--later-slot",default="1800")
    parser.add_argument("--out",default="/tmp/nba-shadow-model-bridge")
    parser.add_argument("--candidate",help="Optional REAL pretip independent model artifact; absent remains ungraded")
    parser.add_argument("--selftest",action="store_true")
    args=parser.parse_args()
    if args.selftest:
        selftest()
    else:
        summary,_,_=run(args.daily_root,args.date,args.earlier_slot,args.later_slot,args.out)
        candidate=load(args.candidate) if args.candidate else None
        original_bridge_path=Path(args.out)/"nba_shadow_model_bridge.json"
        settlement=Path("reports/five-market-settled")/args.date/"settlement.json"
        audit=compare_candidate(
            summary,candidate,
            load(settlement) if settlement.is_file() else None,
            sha(original_bridge_path))
        (Path(args.out)/"nba_shadow_candidate_paired_grade.json").write_text(
            json.dumps(audit,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
            encoding="utf-8")
        print("NBA_SHADOW_CANDIDATE_PAIRED_REPLAY",audit["status"],
              audit["independent_games"],"NO_AUTO_PROMOTION")


if __name__=="__main__":
    main()
