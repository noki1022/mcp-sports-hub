#!/usr/bin/env python3
"""Chronological shadow scorecard for 007 multi-company consensus.

Scores only frozen pretip forecasts whose exact source capture matches the
settlement lock. No fitting, no probability blending, and no post-tip quotes.
"""
from __future__ import annotations
import argparse, json, math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DIRECT_KEYS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")
MIN_SAMPLE_FOR_FUSION_REVIEW=100
MIN_DISTINCT_DAYS_FOR_FUSION_REVIEW=24


def dt(value):
    try:
        x=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return x if x.tzinfo is not None else None
    except (TypeError,ValueError):
        return None


def num(value):
    try:
        if value is None or isinstance(value,bool):return None
        x=float(value)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def _metrics(rows):
    n=len(rows)
    if not n:
        return {"sample_count":0,"distinct_days":0,"accuracy":None,"brier":None,"log_loss":None,
                "calibration_gap":None}
    eps=1e-12
    acc=sum(int((r["probability"]>=.5)==bool(r["outcome"])) for r in rows)/n
    brier=sum((r["probability"]-r["outcome"])**2 for r in rows)/n
    ll=-sum(r["outcome"]*math.log(max(eps,r["probability"]))+
            (1-r["outcome"])*math.log(max(eps,1-r["probability"])) for r in rows)/n
    gap=abs(sum(r["probability"] for r in rows)/n-
            sum(r["outcome"] for r in rows)/n)
    return {"sample_count":n,"distinct_days":len({r.get("day") for r in rows}),
            "accuracy":round(acc,6),"brier":round(brier,7),
            "log_loss":round(ll,7),"calibration_gap":round(gap,7)}


def _shadow_fusion(model_rows, market_rows):
    """Chronological model/market blend experiment; never changes production."""
    model={(x["day"],x["game_id"]):x for x in model_rows}
    market={(x["day"],x["game_id"]):x for x in market_rows}
    paired=[]
    for key in sorted(set(model)&set(market)):
        a,b=model[key],market[key]
        model_capture=dt(a.get("capture"))
        market_capture=dt(b.get("capture"))
        if model_capture is None or market_capture is None:
            continue
        capture_skew=abs((model_capture-market_capture).total_seconds())
        # Both sources are already required to be pre-tip and within 15 min
        # of the frozen report; permit small same-capture ingestion skew.
        if capture_skew>900 or int(a["outcome"])!=int(b["outcome"]):
            continue
        paired.append({"day":key[0],"game_id":key[1],
                       "model":float(a["probability"]),
                       "market":float(b["probability"]),
                       "outcome":int(a["outcome"]),
                       "capture_skew_seconds":round(capture_skew,1)})
    days=sorted({x["day"] for x in paired})
    base={"paired_events":len(paired),"distinct_days":len(days),
          "production_fusion_enabled":False,
          "promotion_policy":"DISABLED; REQUIRES CHRONOLOGICAL HOLDOUT AND SEPARATE APPROVAL"}
    if len(paired)<MIN_SAMPLE_FOR_FUSION_REVIEW or len(days)<MIN_DISTINCT_DAYS_FOR_FUSION_REVIEW:
        return {**base,"status":"BLOCKED_INSUFFICIENT_CHRONOLOGICAL_OOS",
                "required_events":MIN_SAMPLE_FOR_FUSION_REVIEW,
                "required_distinct_days":MIN_DISTINCT_DAYS_FOR_FUSION_REVIEW,
                "market_weight":None,"validation":None,"holdout":None}
    cut_train=max(1,int(len(days)*.60))
    cut_valid=max(cut_train+1,int(len(days)*.80))
    train_days=set(days[:cut_train]);valid_days=set(days[cut_train:cut_valid]);test_days=set(days[cut_valid:])
    train=[x for x in paired if x["day"] in train_days]
    valid=[x for x in paired if x["day"] in valid_days]
    test=[x for x in paired if x["day"] in test_days]
    if len(valid)<15 or len(test)<20 or not train:
        return {**base,"status":"BLOCKED_CHRONOLOGICAL_SPLIT_TOO_SMALL",
                "split":{"train":len(train),"validation":len(valid),"holdout":len(test)},
                "market_weight":None,"validation":None,"holdout":None}
    def brier(rows,weight):
        return sum((((1-weight)*x["model"]+weight*x["market"])-x["outcome"])**2
                   for x in rows)/len(rows)
    grid=[round(i/20,2) for i in range(21)]
    # Choose the market weight on validation dates only. Holdout labels remain untouched.
    weight=min(grid,key=lambda w:(brier(valid,w),w))
    def score(rows,key):
        values=[{"probability":x[key],"outcome":x["outcome"],"day":x["day"]} for x in rows]
        return _metrics(values)
    holdout_rows=[{**x,"blend":(1-weight)*x["model"]+weight*x["market"]} for x in test]
    holdout={"independent_model":score(holdout_rows,"model"),
             "multi_company_market":score(holdout_rows,"market"),
             "shadow_blend":score(holdout_rows,"blend")}
    model_brier=holdout["independent_model"]["brier"]
    blend_brier=holdout["shadow_blend"]["brier"]
    return {**base,"status":"SHADOW_HOLDOUT_SCORED",
            "split":{"train_events":len(train),"validation_events":len(valid),
                     "holdout_events":len(test),"train_end":days[cut_train-1],
                     "validation_end":days[cut_valid-1],"holdout_start":days[cut_valid]},
            "market_weight_selected_on_validation":weight,
            "validation":{"model_brier":round(brier(valid,0.0),7),
                          "market_brier":round(brier(valid,1.0),7),
                          "blend_brier":round(brier(valid,weight),7)},
            "holdout":holdout,
            "holdout_blend_improved_vs_model":(blend_brier is not None and model_brier is not None and blend_brier<model_brier),
            "holdout_blend_improved_vs_market":(blend_brier is not None and holdout["multi_company_market"]["brier"] is not None and blend_brier<holdout["multi_company_market"]["brier"])}

def evaluate(settlements, forecasts):
    forecast_index=defaultdict(list)
    for doc in forecasts:
        if doc.get("schema_version")!="nba-five-markets-v1":
            continue
        for game in doc.get("games",[]):
            forecast_index[(str(doc.get("target_date")),str(game.get("game_id")))].append((doc,game))
    direct_records={}
    consensus=defaultdict(list)
    market_price=defaultdict(list)
    model_first_side=defaultdict(list)
    rejects=Counter()
    seen_consensus=set()
    for settlement in settlements:
        day=str(settlement.get("beijing_date") or settlement.get("target_date") or "")
        for settled_game in settlement.get("games",[]):
            gid=str(settled_game.get("game_id") or "")
            actual_home=num(settled_game.get("home_points"))
            actual_away=num(settled_game.get("away_points"))
            if not gid or actual_home is None or actual_away is None:
                rejects["MISSING_SETTLEMENT_ID_OR_SCORE"]+=1
                continue
            candidates=forecast_index.get((day,gid),[])
            if not candidates:
                rejects["NO_FROZEN_INTRADAY_FORECAST"]+=1
                continue
            settled_markets=settled_game.get("markets") or {}
            matched=[]
            for doc,game in candidates:
                tip=dt(game.get("tipoff_beijing"))
                if tip is None:continue
                doc_capture=dt(doc.get("board_capture_utc"))
                if doc_capture is None or doc_capture>=tip:continue
                forecast_markets=game.get("markets") or {}
                matched_keys=[]
                for key in DIRECT_KEYS:
                    frozen=settled_markets.get(key) or {}
                    predicted=forecast_markets.get(key) or {}
                    frozen_time=dt(frozen.get("frozen_capture_utc"))
                    predicted_time=dt(predicted.get("captured_at_utc"))
                    if (frozen_time is not None and predicted_time is not None
                            and frozen_time==predicted_time and frozen_time<tip and predicted_time<tip):
                        matched_keys.append(key)
                        p=num(predicted.get("model_direction_probability"))
                        outcome=frozen.get("outcome")
                        if p is not None and 0<=p<=1 and outcome in ("HIT","MISS"):
                            record={"probability":p,"outcome":int(outcome=="HIT"),
                                "game_id":gid,"day":day,"capture":predicted_time.isoformat(),
                                "doc_capture":doc_capture}
                            record_key=(day,gid,key)
                            if record_key not in direct_records or doc_capture>direct_records[record_key]["doc_capture"]:
                                direct_records[record_key]=record
                        elif outcome not in ("PUSH","EXCLUDED_NOT_ON_SALE","UNSETTLED"):
                            rejects["DIRECT_PROBABILITY_OR_OUTCOME_MISSING"]+=1
                if matched_keys:
                    matched.append((doc,game,matched_keys,tip,doc_capture))
            if not matched:
                rejects["NO_EXACT_FROZEN_CAPTURE_MATCH"]+=1
                continue
            # Use the newest report among exact market-capture matches, still pretip.
            doc,game,matched_keys,tip,doc_capture=max(matched,key=lambda x:x[4])
            actual_margin=actual_home-actual_away
            actual_total=actual_home+actual_away
            forecast_markets=game.get("markets") or {}
            for source_key,kind in (("JINGCAI_HANDICAP","SPREAD"),("CROWN_HANDICAP","SPREAD"),
                                    ("JINGCAI_TOTAL","TOTAL"),("CROWN_TOTAL","TOTAL")):
                if source_key not in matched_keys:continue
                ctx=((forecast_markets.get(source_key) or {}).get("market_consensus") or {})
                line=num(ctx.get("consensus_line"))
                p=num(ctx.get("model_probability_at_consensus_line"))
                direction=ctx.get("model_direction_at_consensus")
                latest=dt(ctx.get("consensus_latest_source_capture_utc"))
                if line is None or p is None or not 0<=p<=1 or latest is None:
                    rejects["CONSENSUS_CONTEXT_INCOMPLETE"]+=1
                    continue
                if latest>=tip or abs((latest-doc_capture).total_seconds())>900:
                    rejects["CONSENSUS_CAPTURE_TIME_INVALID"]+=1
                    continue
                key=(day,gid,kind)
                if key in seen_consensus:continue
                if kind=="SPREAD":
                    if actual_margin==line:
                        rejects["CONSENSUS_SPREAD_PUSH"]+=1
                        seen_consensus.add(key)
                        continue
                    actual_side="HOME_COVER" if actual_margin>line else "AWAY_COVER"
                else:
                    if actual_total==line:
                        rejects["CONSENSUS_TOTAL_PUSH"]+=1
                        seen_consensus.add(key)
                        continue
                    actual_side="OVER" if actual_total>line else "UNDER"
                if direction not in (("HOME_COVER","AWAY_COVER") if kind=="SPREAD" else ("OVER","UNDER")):
                    rejects["CONSENSUS_DIRECTION_INVALID"]+=1
                    continue
                consensus["CONSENSUS_"+kind].append({
                    "probability":p,"outcome":int(direction==actual_side),
                    "game_id":gid,"day":day,"capture":latest.isoformat(),
                    "line":line,"direction":direction})
                first_side = "HOME_COVER" if kind == "SPREAD" else "OVER"
                first_side_outcome = int(actual_side == first_side)
                model_first_p = num(
                    ctx.get("model_home_cover_probability_at_consensus_line")
                    if kind == "SPREAD" else
                    ctx.get("model_over_probability_at_consensus_line"))
                if model_first_p is not None and 0 <= model_first_p <= 1:
                    model_first_side[kind].append({
                        "probability": model_first_p, "outcome": first_side_outcome,
                        "game_id": gid, "day": day, "capture": latest.isoformat()})
                else:
                    rejects["MODEL_FIRST_SIDE_PROBABILITY_MISSING"] += 1
                price = ctx.get("same_line_price_consensus") or {}
                price_line = num(price.get("reference_line"))
                price_p = num(price.get("first_side_probability"))
                price_latest = dt(price.get("latest_source_capture_utc"))
                price_count = int(price.get("company_count") or 0)
                if (price.get("status") == "AVAILABLE_SAME_LINE_MEDIAN"
                        and price_line is not None and abs(price_line-line) <= 1e-6
                        and price_p is not None and 0 <= price_p <= 1
                        and price_count >= 3 and price_latest is not None
                        and price_latest < tip
                        and abs((price_latest-doc_capture).total_seconds()) <= 900):
                    market_price[kind].append({
                        "probability": price_p, "outcome": first_side_outcome,
                        "game_id": gid, "day": day, "capture": price_latest.isoformat(),
                        "line": price_line, "company_count": price_count})
                else:
                    rejects["SAME_LINE_MARKET_PRICE_CONSENSUS_UNAVAILABLE"] += 1
                seen_consensus.add(key)
    direct=defaultdict(list)
    for (_,_,market),record in direct_records.items():
        direct[market].append({k:v for k,v in record.items() if k!="doc_capture"})
    metrics={k:_metrics(direct[k]) for k in DIRECT_KEYS}
    metrics.update({k:_metrics(consensus[k]) for k in ("CONSENSUS_SPREAD","CONSENSUS_TOTAL")})
    shadow_fusion={}
    for kind in ("SPREAD", "TOTAL"):
        metrics["MODEL_FIRST_SIDE_"+kind] = _metrics(model_first_side[kind])
        metrics["MULTI_COMPANY_PRICE_"+kind] = _metrics(market_price[kind])
        shadow_fusion[kind]=_shadow_fusion(model_first_side[kind],market_price[kind])
    return {
        "shadow_fusion_research":shadow_fusion,
        "schema_version":"nba-007-market-consensus-shadow-scorecard-v2",
        "metrics":metrics,
        "minimum_sample_for_fusion_review":MIN_SAMPLE_FOR_FUSION_REVIEW,
        "minimum_distinct_days_for_fusion_review":MIN_DISTINCT_DAYS_FOR_FUSION_REVIEW,
        "fusion_eligible":{k:(v["sample_count"]>=MIN_SAMPLE_FOR_FUSION_REVIEW
                           and v["distinct_days"]>=MIN_DISTINCT_DAYS_FOR_FUSION_REVIEW)
                           for k,v in metrics.items()},
        "probability_fusion":"DISABLED_NO_WEIGHT_FIT_OR_PRODUCTION_OVERRIDE",
        "fusion_review_policy":"AT_LEAST_100_MATCHED_EVENTS_AND_24_BEIJING_DATES; NO_AUTOMATIC_PROMOTION",
        "selection_policy":"EXACT_FROZEN_SOURCE_CAPTURE_MATCH_PRETIP_ONLY",
        "source_orientation":"USER_CONFIRMED_007_FIRST_SIDE_HOME_OR_OVER; EXACT_SAME_LINE_NO_VIG_ONLY",
        "moneyline_consensus":"NOT_AVAILABLE_NO_DIRECT_MULTI_COMPANY_H2H_FEED",
        "rejections":dict(sorted(rejects.items())),
        "not_betting_advice":True,
    }


def load_tree(root, pattern):
    out=[]
    base=Path(root)
    if not base.exists():return out
    for path in sorted(base.glob(pattern)):
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data,dict):out.append(data)
        except (OSError,ValueError,TypeError):
            continue
    return out


def self_test():
    day="2026-11-01";gid="g1";capture="2026-10-31T10:00:00+00:00"
    tip="2026-11-01T08:00:00+08:00"
    markets={}
    settled_markets={}
    for key,direction in (("JINGCAI_WIN","HOME_WIN"),("JINGCAI_HANDICAP","HOME_COVER"),
        ("JINGCAI_TOTAL","OVER"),("CROWN_HANDICAP","HOME_COVER"),("CROWN_TOTAL","OVER")):
        consensus_line = -5.5 if key.endswith("HANDICAP") else 220.5
        is_spread = key.endswith("HANDICAP")
        markets[key]={"status":"DIRECTION_ISSUED","direction":direction,
            "captured_at_utc":capture,"model_direction_probability":.7,
            "market_consensus":{"status":"CONSENSUS_AVAILABLE","consensus_line":consensus_line,
                "model_probability_at_consensus_line":.65,
                "model_direction_at_consensus":"HOME_COVER" if is_spread else "OVER",
                "model_home_cover_probability_at_consensus_line":.65 if is_spread else None,
                "model_over_probability_at_consensus_line":.65 if not is_spread else None,
                "same_line_price_consensus":{"status":"AVAILABLE_SAME_LINE_MEDIAN",
                    "reference_line":consensus_line,"first_side_probability":.55,
                    "company_count":3,"latest_source_capture_utc":capture},
                "consensus_latest_source_capture_utc":capture}}
        settled_markets[key]={"frozen_capture_utc":capture,"outcome":"HIT"}
    forecast={"schema_version":"nba-five-markets-v1","target_date":day,"board_capture_utc":capture,
        "games":[{"game_id":gid,"tipoff_beijing":tip,"markets":markets}]}
    settlement={"beijing_date":day,"games":[{"game_id":gid,"home_points":120,"away_points":100,"markets":settled_markets}]}
    out=evaluate([settlement],[forecast])
    assert out["metrics"]["JINGCAI_WIN"]["sample_count"]==1
    assert out["metrics"]["CONSENSUS_SPREAD"]["sample_count"]==1
    assert out["metrics"]["CONSENSUS_TOTAL"]["sample_count"]==1
    assert out["metrics"]["MULTI_COMPANY_PRICE_SPREAD"]["sample_count"]==1
    assert out["metrics"]["MULTI_COMPANY_PRICE_TOTAL"]["sample_count"]==1
    assert out["metrics"]["MODEL_FIRST_SIDE_SPREAD"]["sample_count"]==1
    assert out["metrics"]["MODEL_FIRST_SIDE_TOTAL"]["sample_count"]==1
    assert out["metrics"]["MULTI_COMPANY_PRICE_TOTAL"]["brier"]==0.3025
    assert out["probability_fusion"]=="DISABLED_NO_WEIGHT_FIT_OR_PRODUCTION_OVERRIDE"
    # A 30-day synthetic chronological sample validates that market weight is
    # selected only on validation dates and scored on later holdout dates.
    model_rows=[];market_rows=[]
    for day_index in range(30):
        day_value=(datetime(2026,1,1)+__import__("datetime").timedelta(days=day_index)).date().isoformat()
        for game_index in range(5):
            outcome=int(game_index<4)
            key={"day":day_value,"game_id":f"{day_index}-{game_index}","capture":capture}
            model_rows.append({**key,"probability":.60,"outcome":outcome})
            market_rows.append({**key,"probability":.80,"outcome":outcome})
    market_rows[0]["capture"]="2026-01-01T10:01:00+00:00"
    fusion=_shadow_fusion(model_rows,market_rows)
    assert fusion["paired_events"]==150
    assert fusion["status"]=="SHADOW_HOLDOUT_SCORED"
    market_rows[1]["capture"]="2026-01-01T10:16:00+00:00"
    skew_rejected=_shadow_fusion(model_rows,market_rows)
    assert skew_rejected["paired_events"]==149
    assert fusion["split"]["holdout_events"]>=20
    assert fusion["market_weight_selected_on_validation"]==1.0
    assert fusion["production_fusion_enabled"] is False
    blocked=_shadow_fusion(model_rows[:10],market_rows[:10])
    assert blocked["status"]=="BLOCKED_INSUFFICIENT_CHRONOLOGICAL_OOS"
    late=json.loads(json.dumps(forecast))
    for key in ("JINGCAI_TOTAL","CROWN_TOTAL"):
        late["games"][0]["markets"][key]["market_consensus"]["consensus_latest_source_capture_utc"]="2026-11-01T09:00:00+00:00"
    assert evaluate([settlement],[late])["metrics"]["CONSENSUS_TOTAL"]["sample_count"]==0
    print("NBA_007_MARKET_CONSENSUS_SHADOW_BACKTEST_SELFTEST_PASS")


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--intraday-root",default="reports/five-market-intraday")
    ap.add_argument("--settled-root",default="reports/five-market-settled")
    ap.add_argument("--out")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:self_test()
    else:
        forecasts=load_tree(args.intraday_root,"*/*.json")
        settlements=load_tree(args.settled_root,"*/settlement.json")
        result=evaluate(settlements,forecasts)
        payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
        if args.out:Path(args.out).write_text(payload,encoding="utf-8")
        print(json.dumps({"metrics":result["metrics"],"rejections":result["rejections"],
                          "fusion":"DISABLED"},ensure_ascii=False))
