#!/usr/bin/env python3
"""Does multi-book spread movement add genuine information to NBA moneyline?

Research-only, exact historical OPEN/CLOSE stage (not quote-update timestamps).
Chronologically train spread->ML response and test incremental ML calibration
versus market-only; NEVER assume -7.5 to -9.5 automatically adds fixed win pp.
No production probabilities, wagers, cron, 007 or injury changes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import random
from pathlib import Path
import statistics

import nba_historical_market_benchmark as B
import nba_hf_open_close_crosscheck as HF

SCHEMA = "nba-spread-move-to-ml-crossmarket-shadow-v1"
STRENGTH = 80.0
MIN_GAIN = 0.0005
SCALE = 2.0  # A movement of home -7.5 -> -9.5 gives positive x=+1.
WEIGHTS = (0.0, 0.25, 0.50, 1.0)


def logit(p):
    p = min(0.999999, max(0.000001, p))
    return math.log(p / (1 - p))


def logistic(z):
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def brier(rows, key):
    return sum((r[key] - r["y"]) ** 2 for r in rows) / len(rows)


def loss(rows, key):
    return sum(-r["y"] * math.log(max(1e-8, r[key]))
               - (1-r["y"]) * math.log(max(1e-8, 1-r[key]))
               for r in rows) / len(rows)


def prepare(games):
    rows, rejected, ids = [], Counter(), set()
    for r in games:
        gid = str(r.get("external_game_id") or "")
        if not gid or gid in ids:
            rejected["DUPLICATE_OR_MISSING_GAME_ID"] += 1
            continue
        ids.add(gid)
        if (r.get("cross_source_score_verified") is not True
                or r.get("research_open_close_benchmark_eligible") is not True
                or r.get("production_fusion_eligible") is not False
                or r.get("exact_pregame_capture_time_eligible") is not False):
            rejected["INCOMPLETE_SOURCE_STAGE_PROVENANCE"] += 1
            continue
        op, cp = r.get("market_open_p_home_no_vig"), r.get("market_close_p_home_no_vig")
        old, new = r.get("market_open_spread_home"), r.get("market_close_spread_home")
        date, y = r.get("date_et"), r.get("observed_home_win")
        if (not isinstance(op, (int,float)) or not isinstance(cp, (int,float))
                or not 0.005 <= op <= 0.995 or not 0.005 <= cp <= 0.995
                or not isinstance(old,(int,float)) or not isinstance(new,(int,float))
                or any(not math.isfinite(x) for x in (op, cp, old, new))
                or abs(old) > 40 or abs(new) > 40
                or not isinstance(date,str) or len(date)!=10 or y not in (0,1)):
            rejected["INVALID_PROBABILITY_LINE_OR_SCORE"] += 1
            continue
        if old == new:
            rejected["UNCHANGED_SPREAD_IS_VALID_ZERO_SIGNAL"] += 1
        movement = float(old - new)  # signed HOME handicap: -7.5 -> -9.5 => +2
        if abs(movement) > 15:
            rejected["EXTREME_MOVEMENT_QUARANTINE"] += 1
            continue
        rows.append({
            "id":gid,"day":date,"y":int(y),
            "open_p":float(op),"close_p":float(cp),
            "opening_home_handicap":float(old),"closing_home_handicap":float(new),
            "home_favorable_spread_move":movement,"x":max(-6.0,min(6.0,movement/SCALE)),
            "ml_log_odds_move":logit(float(cp)) - logit(float(op)),
        })
    return rows,dict(sorted(rejected.items()))


def chronological(rows):
    # One date only in one partition, so same-game and same-day market data
    # can never be split across train/validation/retrospective-later scores.
    dates = sorted(set(r["day"] for r in rows))
    counts = Counter(r["day"] for r in rows)
    total = len(rows)
    edges = []
    seen = 0
    for day in dates:
        if len(edges)==0 and seen >= int(total*.46):
            edges.append(day)
        elif len(edges)==1 and seen >= int(total*.71):
            edges.append(day)
        seen += counts[day]
    if len(edges)!=2 or not edges[0]<edges[1]:
        raise ValueError("NOT_ENOUGH_INDEPENDENT_CHRONOLOGICAL_DATES")
    parts = {
        "earlier_fit":[r for r in rows if r["day"]<edges[0]],
        "validation":[r for r in rows if edges[0]<=r["day"]<edges[1]],
        "previously_explored_evaluation":[r for r in rows if r["day"]>=edges[1]],
    }
    if (len(parts["earlier_fit"])<450 or len(parts["validation"])<220
            or len(parts["previously_explored_evaluation"])<280):
        raise ValueError("INSUFFICIENT_DATE_GROUPED_PARTITIONS")
    assert not (set(x["id"] for x in parts["earlier_fit"]) &
                set(x["id"] for x in parts["validation"]+parts["previously_explored_evaluation"]))
    return parts


def price_response_fit(train):
    """How many LOGIT ML points per +2 of spread movement? Prices only, earlier dates."""
    numer = sum(r["x"]*r["ml_log_odds_move"] for r in train)
    denom = STRENGTH + sum(r["x"]**2 for r in train)
    return max(0.0,min(1.0,numer/denom))


def residual_fit(train):
    """Can spread movement correct CLOSING ML probability after its own repricing?

    Strong ridge to zero, one coefficient, pure earlier-game labels.
    This may be NEGATIVE. Selection must never force a positive result.
    """
    beta=0.0
    for _ in range(25):
        gradient=STRENGTH*beta
        curvature=STRENGTH
        for r in train:
            p=logistic(logit(r["close_p"])+beta*r["x"])
            gradient += r["x"]*(p-r["y"])
            curvature += r["x"]**2 * p*(1-p)
        step=gradient/curvature
        beta=max(-1.0,min(1.0,beta-step))
        if abs(step)<1e-10:
            break
    return beta


def add_predictions(rows, response, beta, weight):
    return [{
        **r,
        "open_plus_spread_bridge_p":logistic(logit(r["open_p"])+response*r["x"]),
        "close_plus_spread_residual_p":logistic(logit(r["close_p"])+beta*weight*r["x"]),
    } for r in rows]


def paired_day_bootstrap(rows, repetitions=800):
    """Later-period paired Brier correction minus plain closing market.

    Sample whole dates (not games), keep the prior-selected correction frozen,
    and never tune on this interval. The CI is exploratory and does not
    establish a blind prospective market advantage.
    """
    day_map={}
    for r in rows:
        day_map.setdefault(r["day"],[]).append(r)
    dates=sorted(day_map)
    if len(dates)<12:
        return {"date_clusters":len(dates),"delta_brier":None,"ci95":None,
                "proof_of_stable_lift":False}
    delta=sum(((r["close_plus_spread_residual_p"]-r["y"])**2 -
               (r["close_p"]-r["y"])**2) for r in rows)/len(rows)
    rng=random.Random(20261102)
    draws=[]
    for _ in range(repetitions):
        sampled=[rng.choice(dates) for _ in dates]
        game_rows=[r for day in sampled for r in day_map[day]]
        draws.append(sum(((r["close_plus_spread_residual_p"]-r["y"])**2 -
                          (r["close_p"]-r["y"])**2) for r in game_rows)/len(game_rows))
    draws.sort()
    bounds=[round(draws[int((len(draws)-1)*.025)],8),
            round(draws[int((len(draws)-1)*.975)],8)]
    return {"date_clusters":len(dates),"delta_brier":round(delta,8),
            "ci95":bounds,"proof_of_stable_lift":bool(bounds[1]<0),
            "research_previous_season_evaluation_not_new_holdout":True}


def summary(rows):
    assert rows
    moved=[r for r in rows if abs(r["x"])>1e-9]
    sign_agree=[r for r in moved if abs(r["ml_log_odds_move"])>1e-8]
    hom=[r for r in rows if r["home_favorable_spread_move"]>=1.5]
    awy=[r for r in rows if r["home_favorable_spread_move"]<=-1.5]
    def group_stats(group):
        return {"n":len(group),
                "mean_open_home_win_prob":round(statistics.mean(r["open_p"] for r in group),6) if group else None,
                "mean_close_home_win_prob":round(statistics.mean(r["close_p"] for r in group),6) if group else None,
                "actual_home_win_rate":round(statistics.mean(r["y"] for r in group),6) if group else None}
    return {
        "n_games":len(rows),"distinct_days":len({r["day"] for r in rows}),
        "date_start":min(r["day"] for r in rows),"date_end":max(r["day"] for r in rows),
        "spread_moved_games":len(moved),
        "market_price_direction_agreement": {
            "n_nonzero_spread_and_ml_moves":len(sign_agree),
            "same_direction":sum(r["x"]*r["ml_log_odds_move"]>0 for r in sign_agree),
            "same_direction_fraction":round(sum(r["x"]*r["ml_log_odds_move"]>0 for r in sign_agree)/len(sign_agree),6) if sign_agree else None,
        },
        "home_spread_improved_at_least_1_5pts":group_stats(hom),
        "away_spread_improved_at_least_1_5pts":group_stats(awy),
        "brier":{"opening_market":round(brier(rows,"open_p"),7),
                 "closing_market":round(brier(rows,"close_p"),7),
                 "opening_plus_spread_bridge":round(brier(rows,"open_plus_spread_bridge_p"),7),
                 "closing_plus_residual":round(brier(rows,"close_plus_spread_residual_p"),7)},
        "logloss":{"opening_market":round(loss(rows,"open_p"),7),
                   "closing_market":round(loss(rows,"close_p"),7),
                   "closing_plus_residual":round(loss(rows,"close_plus_spread_residual_p"),7)},
    }


def experiment(original):
    rows,rejections=prepare(original)
    if len(rows) < 1100:
        raise ValueError("TOO_FEW_REAL_CROSSCHECKED_LINE_GAMES")
    parts=chronological(rows)
    earlier,valid,later=(parts[k] for k in (
        "earlier_fit","validation","previously_explored_evaluation"))
    response=price_response_fit(earlier)
    residual=residual_fit(earlier)
    valid_candidates = {}
    for w in WEIGHTS:
        predicted=add_predictions(valid,response,residual,w)
        valid_candidates[str(w)]={
            "brier":round(brier(predicted,"close_plus_spread_residual_p"),8),
            "logloss":round(loss(predicted,"close_plus_spread_residual_p"),8),
        }
    market_ref=valid_candidates["0.0"]
    eligible=[w for w in WEIGHTS if (
        w == 0 or (
            market_ref["brier"]-valid_candidates[str(w)]["brier"]>=MIN_GAIN and
            valid_candidates[str(w)]["logloss"]<=market_ref["logloss"]+0.001
        )
    )]
    weight=min(eligible,key=lambda w:(valid_candidates[str(w)]["brier"],w))
    later_pred=add_predictions(later,response,residual,weight)
    all_with_predictions=add_predictions(rows,response,residual,weight)
    observed_example=logistic(logit(.80)+response*(2/SCALE))
    return {
        "schema_version":SCHEMA,
        "history_input_games":len(original),"eligible_games":len(rows),
        "source_rejections":rejections,
        "date_grouped_splits":{k:summary(add_predictions(v,response,residual,weight))
                               for k,v in parts.items()},
        "trained_on_earlier_dates_only":True,
        "model_parameters":{
            "home_favorable_movement_definition":"open_signed_home_handicap_minus_close_signed_home_handicap",
            "example_open_home_minus_7_5_to_close_home_minus_9_5_move_points":2.0,
            "price_response_logit_per_2pts":round(response,8),
            "close_ml_residual_logit_per_2pts":round(residual,8),
            "residual_weight_selected_on_prior_validation":weight,
            "validation_prespecified_min_brier_gain":MIN_GAIN,
            "validation_alternative_scores":valid_candidates,
            "example_80pct_open_ml_plus_2pt_spread_move_price_bridge":round(observed_example,6),
            "example_is_research_stage_price_bridge_not_live_certified_win_probability":True,
        },
        "later_evaluation":summary(later_pred),
        "later_paired_brier_delta_bootstrap":paired_day_bootstrap(later_pred),
        "later_evaluation_current_results_not_blind":True,
        "closing_ml_already_includes_market_information":True,
        "no_authorized_live_ml_probability_adjustment":True,
        "exact_original_historical_open_close_quote_update_timestamps_verified":False,
        "historical_bookmakers_are_crossbook_consensus_not_verified_007":True,
        "prediction_validation_against_actual_scores_not_only_close_ml_prices":True,
        "train_validation_evaluation_disjoint_by_date":True,
        "no_prod_model_push_schedule_crown_jingcai_changes":True,
        "not_a_live_betting_edge_or_approved_five_market_fusion":True,
    }


def selftest():
    # Market HOME signed convention is the actual spread plus/minus applied to score.
    assert -7.5-(-9.5)==2.0
    assert logit(.8)<logit(.9)
    a={"id":"a","day":"2024-01-01","x":1.0,
       "open_p":.8,"close_p":.83,"y":1,"ml_log_odds_move":logit(.83)-logit(.8)}
    b={**a,"id":"b","x":-1.0,"close_p":.77,"y":0,
       "ml_log_odds_move":logit(.77)-logit(.8)}
    response=price_response_fit([a,b])
    assert response>0
    t=add_predictions([a,b],response,0,0)
    assert t[0]["open_plus_spread_bridge_p"]>.8
    assert t[1]["open_plus_spread_bridge_p"]<.8
    assert t[0]["close_plus_spread_residual_p"]==a["close_p"] or abs(
        t[0]["close_plus_spread_residual_p"]-a["close_p"])<1e-12
    assert residual_fit([a,b])==residual_fit([a,b])
    invalid, rejected=prepare([{"external_game_id":"g","cross_source_score_verified":True,
                                "research_open_close_benchmark_eligible":True,
                                "production_fusion_eligible":True,
                                "exact_pregame_capture_time_eligible":True}])
    assert not invalid and rejected["INCOMPLETE_SOURCE_STAGE_PROVENANCE"]==1
    print("NBA_SPREAD_MOVEMENT_TO_MONEYLINE_SHADOW_SELFTEST_PASS")


def run(out):
    scores,score_info=B.transform(B.fetch())
    source=HF.fetch()
    verified,manifest=HF.transform(source,scores)
    result=experiment(verified)
    result["source_sha256"]=hashlib.sha256(source).hexdigest()
    result["independently_crosschecked_score_source_sha256"]=score_info["source_sha256"]
    result["source_metadata"]={"verified_n":manifest["crosschecked_games"],
                               "original_quote_update_times_available":False}
    Path(out).write_text(json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True)+"\n",
                         encoding="utf-8")
    s=result["later_evaluation"]
    print("NBA_SPREAD_TO_ML_REAL_CROSSMARKET_RESEARCH",json.dumps({
        "games":result["eligible_games"],
        "beta_price_response_per_2pts":result["model_parameters"]["price_response_logit_per_2pts"],
        "beta_residual_per_2pts":result["model_parameters"]["close_ml_residual_logit_per_2pts"],
        "selected_weight":result["model_parameters"]["residual_weight_selected_on_prior_validation"],
        "later_evaluation":s,
        "later_delta_ci":result["later_paired_brier_delta_bootstrap"],
        "no_live_adjustment":True
    },ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="/tmp/nba-spread-to-ml-shadow.json")
    ap.add_argument("--selftest",action="store_true")
    opts=ap.parse_args()
    if opts.selftest:selftest()
    else:run(opts.out)


if __name__=="__main__":
    main()
