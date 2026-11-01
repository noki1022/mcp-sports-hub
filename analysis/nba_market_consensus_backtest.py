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
        return {"sample_count":0,"accuracy":None,"brier":None,"log_loss":None,
                "calibration_gap":None}
    eps=1e-12
    acc=sum(int((r["probability"]>=.5)==bool(r["outcome"])) for r in rows)/n
    brier=sum((r["probability"]-r["outcome"])**2 for r in rows)/n
    ll=-sum(r["outcome"]*math.log(max(eps,r["probability"]))+
            (1-r["outcome"])*math.log(max(eps,1-r["probability"])) for r in rows)/n
    gap=abs(sum(r["probability"] for r in rows)/n-
            sum(r["outcome"] for r in rows)/n)
    return {"sample_count":n,"accuracy":round(acc,6),"brier":round(brier,7),
            "log_loss":round(ll,7),"calibration_gap":round(gap,7)}


def evaluate(settlements, forecasts):
    forecast_index=defaultdict(list)
    for doc in forecasts:
        if doc.get("schema_version")!="nba-five-markets-v1":
            continue
        for game in doc.get("games",[]):
            forecast_index[(str(doc.get("target_date")),str(game.get("game_id")))].append((doc,game))
    direct=defaultdict(list)
    consensus=defaultdict(list)
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
                    if frozen_time is not None and predicted_time is not None and frozen_time==predicted_time:
                        matched_keys.append(key)
                        p=num(predicted.get("model_direction_probability"))
                        outcome=frozen.get("outcome")
                        if p is not None and 0<=p<=1 and outcome in ("HIT","MISS"):
                            direct[key].append({"probability":p,"outcome":int(outcome=="HIT"),
                                "game_id":gid,"day":day,"capture":predicted_time.isoformat()})
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
                seen_consensus.add(key)
    metrics={k:_metrics(direct[k]) for k in DIRECT_KEYS}
    metrics.update({k:_metrics(consensus[k]) for k in ("CONSENSUS_SPREAD","CONSENSUS_TOTAL")})
    return {
        "schema_version":"nba-007-market-consensus-shadow-scorecard-v1",
        "metrics":metrics,
        "minimum_sample_for_fusion_review":MIN_SAMPLE_FOR_FUSION_REVIEW,
        "fusion_eligible":{k:(v["sample_count"]>=MIN_SAMPLE_FOR_FUSION_REVIEW)
                           for k,v in metrics.items()},
        "probability_fusion":"DISABLED_NO_WEIGHT_FIT_OR_PRODUCTION_OVERRIDE",
        "selection_policy":"EXACT_FROZEN_SOURCE_CAPTURE_MATCH_PRETIP_ONLY",
        "source_orientation":"RAW_MULTI_COMPANY_WATER_SLOTS_NOT_USED_AS_HOME_AWAY_PROBABILITIES",
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
        markets[key]={"status":"DIRECTION_ISSUED","direction":direction,
            "captured_at_utc":capture,"model_direction_probability":.7,
            "market_consensus":{"status":"CONSENSUS_AVAILABLE","consensus_line":-5.5 if key.endswith("HANDICAP") else 220.5,
                "model_probability_at_consensus_line":.65,"model_direction_at_consensus":"HOME_COVER" if key.endswith("HANDICAP") else "OVER",
                "consensus_latest_source_capture_utc":capture}}
        settled_markets[key]={"frozen_capture_utc":capture,"outcome":"HIT"}
    forecast={"schema_version":"nba-five-markets-v1","target_date":day,"board_capture_utc":capture,
        "games":[{"game_id":gid,"tipoff_beijing":tip,"markets":markets}]}
    settlement={"beijing_date":day,"games":[{"game_id":gid,"home_points":120,"away_points":100,"markets":settled_markets}]}
    out=evaluate([settlement],[forecast])
    assert out["metrics"]["JINGCAI_WIN"]["sample_count"]==1
    assert out["metrics"]["CONSENSUS_SPREAD"]["sample_count"]==1
    assert out["metrics"]["CONSENSUS_TOTAL"]["sample_count"]==1
    assert out["probability_fusion"]=="DISABLED_NO_WEIGHT_FIT_OR_PRODUCTION_OVERRIDE"
    late=json.loads(json.dumps(forecast))
    late["games"][0]["markets"]["CROWN_TOTAL"]["market_consensus"]["consensus_latest_source_capture_utc"]="2026-11-01T09:00:00+00:00"
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
