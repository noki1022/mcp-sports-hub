#!/usr/bin/env python3
"""Seven-stage, evidence-labelled 007 NBA SOP — deterministic, fail closed.

Cheap O(n) analysis of *already captured* artifacts. No network calls and no
model training. A missing game, outdated/after-tip quote or unreliable market
never becomes a confident recommendation. User-facing game IDs always come
from the separate JC match-label verification, not display-list position.

Current stage 7 stays RESEARCH_ONLY / NO_BET because an odds-outcome backtest
does not yet establish ROI and price-direction stability across seasons.
"""
from __future__ import annotations
import argparse, json, math, re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")
ISSUE = re.compile(r"^周[一二三四五六日天]\d{3}$")
VERSION = "nba-007-analysis-sop-v1"
STAGES = (
    "01_IDENTITY",
    "02_INDEPENDENT_MODEL",
    "03_007_INSTITUTIONS",
    "04_HOURLY_MARKET_DELTA",
    "05_JINGCAI_PRICE_AND_PROBABILITY",
    "06_INJURY_AND_CONTEXT",
    "07_RISK_DECISION",
)
MAX_QUOTE_AGE_MIN = 120
ALERT_POINT_GAP = 4.0  # Research attention only; never a validated betting edge.

def dt(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo is not None else None
    except (ValueError,TypeError):
        return None

def numeric(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):
        return None

def by_id(rows):
    result={}
    for row in rows or []:
        if not isinstance(row,dict):
            raise ValueError("NON_OBJECT_RECORD")
        gid=str(row.get("game_id") or "")
        if not gid or gid in result:
            raise ValueError("DUPLICATE_OR_MISSING_GAME_ID")
        result[gid]=row
    return result

def no_vig(current):
    a=numeric((current or {}).get("first_side"))
    b=numeric((current or {}).get("second_side"))
    if a is None or b is None or not (1<a<50 and 1<b<50):
        return None
    raw_a,raw_b=1/a,1/b
    total=raw_a+raw_b
    if total<=0:
        return None
    return {"first":round(raw_a/total,6),"second":round(raw_b/total,6),
            "overround":round(total-1,6)}

def source_age_minutes(captured,reference):
    if not captured or not reference:return None
    return (reference-captured).total_seconds()/60

def evaluate(joined,model,movement,jingcai,top10=None,injury=None,now_utc=None):
    if not isinstance(joined,dict) or not isinstance(jingcai,dict):
        raise ValueError("REQUIRED_SOURCES_INVALID")
    target=joined.get("requested_display_date")
    if not target or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",str(target)):
        raise ValueError("TARGET_BEIJING_DATE_INVALID")
    games=[g for g in joined.get("nba_cba_games",[]) if g.get("league")=="NBA"]
    if not games:
        raise ValueError("EMPTY_NBA_BOARD")
    by_id(games)  # detect duplicate IDs before attaching market prices
    model_rows=by_id((model or {}).get("games",[]))
    move_rows=by_id((movement or {}).get("games",[]))
    company_rows=by_id((top10 or {}).get("games",[]))
    injury_rows=by_id((injury or {}).get("games",[]))
    jc_snapshot=jingcai.get("jc_007_public_odds_shadow") or {}
    prices=by_id(jc_snapshot.get("games",[]))
    ids=(jingcai.get("jc_007_match_numbers") or {}).get("games") or {}
    capture=dt(joined.get("captured_at_utc"))
    lottery_capture=dt(jc_snapshot.get("captured_at_utc"))
    now=dt(now_utc) if isinstance(now_utc,str) else now_utc
    if now is None:now=datetime.now(timezone.utc)
    rows=[]
    seen_codes=set()
    for g in games:
        gid=str(g["game_id"])
        tip=dt(g.get("start_time_beijing"))
        code=ids.get(gid) or {}
        stage={}
        reasons=[]
        verified=(
            code.get("status")=="VERIFIED_JC_NUMBER" and
            ISSUE.fullmatch(str(code.get("label") or "")) is not None and
            str(code.get("match_no"))==str(code.get("label"))[-3:] and
            tip is not None and tip.astimezone(BJ).date().isoformat()==target and
            g.get("display_date")==target
        )
        label=code.get("label") if verified else None
        if verified and label in seen_codes:
            verified=False
            reasons.append("DUPLICATE_JINGCAI_MATCH_NUMBER")
        if verified:seen_codes.add(label)
        stage[STAGES[0]]="PASS" if verified else "BLOCKED"
        if not verified:
            reasons.append("UNVERIFIED_JINGCAI_NUMBER_OR_TEAM_OR_DATE")

        p=model_rows.get(gid) or {}
        quality=(p.get("data_quality") or {}).get("quality")
        model_status=p.get("model_status")
        cal=p.get("calibration") or {}
        feature_cutoff=p.get("feature_cutoff_date")
        cal_through=cal.get("calibrated_through")
        time_ok=feature_cutoff is not None and cal_through is not None and (
            str(feature_cutoff)<target and str(cal_through)<target)
        means_ok=numeric(p.get("margin_mean_home_minus_away")) is not None and numeric(p.get("total_mean")) is not None
        model_good=bool(model_status=="OK" and quality=="PASS" and means_ok and time_ok)
        stage[STAGES[1]]="PASS" if model_good else "BLOCKED"
        if not model_good:reasons.append("INDEPENDENT_MODEL_NOT_FULLY_VERIFIED")

        company=company_rows.get(gid) or {}
        spread_companies=(((company.get("markets") or {}).get("full_spread") or {}).get("company_count") or 0)
        total_companies=(((company.get("markets") or {}).get("full_total") or {}).get("company_count") or 0)
        # The report stores company counts but currently does not independently
        # prove that each odds quotation is time-synchronous or identically oriented.
        company_ready=int(spread_companies or 0)>=5 and int(total_companies or 0)>=5
        stage[STAGES[2]]="OBSERVED" if company_ready else "PARTIAL"

        move=move_rows.get(gid) or {}
        changes=(move.get("markets") or {})
        observable=any((changes.get(k) or {}).get("delta_line_previous") is not None
                       for k in ("full_spread","full_total"))
        stage[STAGES[3]]="COMPARABLE" if observable else "BASELINE_ONLY"
        if not observable:reasons.append("NO_PRIOR_MARKET_SNAPSHOT")

        prices_row=prices.get(gid) or {}
        pr_markets=prices_row.get("markets") or {}
        fresh=lottery_capture is not None and capture is not None and (
            -5<=source_age_minutes(lottery_capture,capture)<=MAX_QUOTE_AGE_MIN)
        if tip is not None and lottery_capture is not None and lottery_capture>=tip:
            fresh=False
            reasons.append("JINGCAI_QUOTE_AFTER_TIPOFF")
        if not fresh:reasons.append("JINGCAI_QUOTE_MISSING_STALE_OR_CLOCK_MISMATCH")
        quote={}
        for key,side_names in (
            ("win_lose",("主胜","客胜")),
            ("handicap",("让分主胜","让分客胜")),
            ("total",("大分","小分"))
        ):
            market=pr_markets.get(key) or {}
            status=market.get("status","NO_QUOTE_IN_007_FEED")
            if status!="OBSERVED":
                quote[key]={"status":status}
                continue
            cur=(market.get("data") or {}).get("current") or {}
            opening=(market.get("data") or {}).get("opening") or {}
            probs=no_vig(cur)
            line=numeric(cur.get("line"))
            if key!="win_lose" and line is None:
                probs=None
            quote[key]={"status":"OBSERVED" if probs else "INVALID_QUOTE",
                        "first_side_label":side_names[0],
                        "second_side_label":side_names[1],
                        "opening":opening, "current":cur, "line":line,
                        "market_no_vig":probs if fresh and verified else None}
            if not probs:reasons.append("INVALID_JINGCAI_PRICE_"+key.upper())
        count=sum(x.get("status")=="OBSERVED" for x in quote.values())
        stage[STAGES[4]]=("VALID_QUOTE" if fresh and verified and count>=1
                          else "BLOCKED" if not fresh or not verified else "NOT_ON_SALE_OR_MISSING")
        if count==0:reasons.append("NO_AVAILABLE_JINGCAI_MARKET")
        if not fresh or not verified:
            for k in quote:
                quote[k]["market_no_vig"]=None

        injury_ctx=injury_rows.get(gid) or {}
        injury_quality=injury_ctx.get("quality","UNKNOWN_OR_UNSUBMITTED")
        stage[STAGES[5]]="PUBLISHED" if injury_quality in ("PUBLISHED_LISTED","PUBLISHED_AFFECTED") else "UNKNOWN"
        if stage[STAGES[5]]=="UNKNOWN":reasons.append("INJURY_DATA_NOT_CONFIRMED")

        margin=numeric(p.get("margin_mean_home_minus_away")) if model_good else None
        total=numeric(p.get("total_mean")) if model_good else None
        # +JC spread = points awarded to home (007 screenshot definition).
        # This is a research point-gap, not a winning probability.
        sp_line=quote.get("handicap",{}).get("line") if fresh and verified else None
        tl_line=quote.get("total",{}).get("line") if fresh and verified else None
        spread_gap=round(margin+sp_line,2) if margin is not None and sp_line is not None else None
        total_gap=round(total-tl_line,2) if total is not None and tl_line is not None else None
        research_focus=[]
        if spread_gap is not None and abs(spread_gap)>=ALERT_POINT_GAP:
            research_focus.append("让分：模型与竞彩线差距较大")
        if total_gap is not None and abs(total_gap)>=ALERT_POINT_GAP:
            research_focus.append("大小分：模型与竞彩线差距较大")
        model_home_p=numeric((p.get("model_probability") or {}).get("home")) if model_good else None
        odds_home=(quote.get("win_lose") or {}).get("market_no_vig") or {}
        moneyline_gap=(round(model_home_p-odds_home["first"],4)
                       if model_home_p is not None and 0<=model_home_p<=1
                       and "first" in odds_home else None)

        stage[STAGES[6]]="RESEARCH_ONLY_NO_BET"
        if not verified or not model_good or not fresh:
            verdict="数据不足，暂不判断"
        elif research_focus:
            verdict="需要重点复核"
        else:
            verdict="常规观察"
        rows.append({"game_id":gid,"jingcai_label":label,
            "home_team":g["home_team"],"away_team":g["away_team"],
            "tipoff_beijing":g.get("start_time_beijing"),
            "stages":stage,"evidence_reasons":sorted(set(reasons)),
            "model": {"version":p.get("model_version"),"margin_home_minus_away":margin,
                      "total_mean":total,"home_win_probability":model_home_p,
                      "calibration_cutoff":cal_through,"feature_cutoff_date":feature_cutoff},
            "institution":{"spread_company_count":spread_companies,
                           "total_company_count":total_companies},
            "movement_status":move.get("status","NO_HISTORY"),
            "injury_quality":injury_quality,
            "jingcai":{"source":"007_JC_PUBLIC_ODDS","captured_at_utc":jc_snapshot.get("captured_at_utc"),
                       "fresh_for_comparison":fresh,"markets":quote,
                       "markets_observed":count},
            "research_comparison":{"spread_gap_home_points":spread_gap,
                "total_gap_points":total_gap,
                "model_minus_no_vig_market_home_probability":moneyline_gap,
                "not_validated_ev":True},
            "research_focus":research_focus,
            "assessment":verdict,"recommendation":"NO_BET"})
    return {"schema_version":VERSION,"target_beijing_date":target,
        "model_retrained_by_sop":False, "new_network_calls_by_sop":0,
        "stages":list(STAGES),"games":rows,"game_count":len(rows),
        "verified_jingcai_ids":sum(bool(x["jingcai_label"]) for x in rows),
        "model_ready":sum(x["stages"][STAGES[1]]=="PASS" for x in rows),
        "jingcai_fresh":sum(x["jingcai"]["fresh_for_comparison"] for x in rows),
        "candidate_count":0,"decision":"NO_BET",
        "policy":"Market gaps are observations only; no betting ROI or causal movement claims until chronology-backtest passes.",
        "generated_at_utc":now.astimezone(timezone.utc).isoformat()}

def self_test():
    now=datetime(2026,10,30,14,0,tzinfo=timezone.utc)
    joined={"requested_display_date":"2026-10-31",
      "captured_at_utc":"2026-10-30T13:59:00+00:00","nba_cba_games":[
        {"league":"NBA","game_id":"17","home_team":"主队","away_team":"客队",
         "display_date":"2026-10-31","start_time_beijing":"2026-10-31T07:30+08:00"}]}
    model={"games":[{"game_id":"17","model_status":"OK",
      "model_version":"v1","feature_cutoff_date":"2026-10-25",
      "calibration":{"calibrated_through":"2026-10-20"},
      "data_quality":{"quality":"PASS"},"margin_mean_home_minus_away":-6,
      "total_mean":231,"model_probability":{"home":0.36}}]}
    movement={"games":[{"game_id":"17","status":"LINE_MOVE","markets":{
      "full_total":{"delta_line_previous":2},"full_spread":{}}}]}
    price={"game_id":"17","markets":{
       "win_lose":{"status":"OBSERVED","data":{"current":{"first_side":2.95,"second_side":1.19}}},
       "handicap":{"status":"OBSERVED","data":{"current":{"first_side":1.75,"second_side":1.65,"line":7.5}}},
       "total":{"status":"OBSERVED","data":{"current":{"first_side":1.7,"second_side":1.7,"line":225.5}}}}}
    jc={"jc_007_match_numbers":{"games":{"17":{"status":"VERIFIED_JC_NUMBER",
      "label":"周五314","match_no":"314"}}},
      "jc_007_public_odds_shadow":{"captured_at_utc":"2026-10-30T13:58:00+00:00",
       "games":[price]}}
    a=evaluate(joined,model,movement,jc,now_utc=now)
    row=a["games"][0]
    assert row["jingcai_label"]=="周五314"
    assert a["model_ready"]==1 and a["jingcai_fresh"]==1
    assert row["research_comparison"]["spread_gap_home_points"]==1.5
    assert row["research_comparison"]["total_gap_points"]==5.5
    assert abs(sum(row["jingcai"]["markets"]["win_lose"]["market_no_vig"][x]
                   for x in ("first","second"))-1)<1e-5
    assert row["research_focus"]==["大小分：模型与竞彩线差距较大"]
    assert row["recommendation"]=="NO_BET"
    flipped=json.loads(json.dumps(jc))
    flipped["jc_007_match_numbers"]["games"]["17"]["status"]="UNVERIFIED"
    b=evaluate(joined,model,movement,flipped,now_utc=now)["games"][0]
    assert b["jingcai_label"] is None
    assert b["research_comparison"]["spread_gap_home_points"] is None
    assert b["jingcai"]["markets"]["win_lose"]["market_no_vig"] is None
    stale=json.loads(json.dumps(jc))
    stale["jc_007_public_odds_shadow"]["captured_at_utc"]="2026-10-29T12:00:00+00:00"
    c=evaluate(joined,model,movement,stale,now_utc=now)["games"][0]
    assert c["jingcai"]["fresh_for_comparison"] is False
    assert c["research_comparison"]["total_gap_points"] is None
    missing=json.loads(json.dumps(jc))
    missing["jc_007_public_odds_shadow"]["games"][0]["markets"]["win_lose"]={"status":"NOT_ON_SALE_USER_CONFIRMED"}
    d=evaluate(joined,model,movement,missing,now_utc=now)["games"][0]
    assert d["jingcai"]["markets"]["win_lose"]["status"]=="NOT_ON_SALE_USER_CONFIRMED"
    assert d["jingcai"]["markets"]["handicap"]["status"]=="OBSERVED"
    bad_model=json.loads(json.dumps(model))
    bad_model["games"][0]["feature_cutoff_date"]="2026-10-31"
    e=evaluate(joined,bad_model,movement,jc,now_utc=now)["games"][0]
    assert e["stages"]["02_INDEPENDENT_MODEL"]=="BLOCKED"
    assert e["research_comparison"]["model_minus_no_vig_market_home_probability"] is None
    assert a["candidate_count"]==0 and a["decision"]=="NO_BET"
    print("NBA_STRICT_SEVEN_STAGE_SOP_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--joined");p.add_argument("--model")
    p.add_argument("--movement");p.add_argument("--jingcai")
    p.add_argument("--top10");p.add_argument("--injury")
    p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:self_test()
    else:
        if not all((args.joined,args.model,args.jingcai,args.out)):
            raise SystemExit("REQUIRES_JOINED_MODEL_JINGCAI_OUTPUT")
        def load(path):
            if not path:return {}
            return json.loads(Path(path).read_text(encoding="utf-8"))
        result=evaluate(load(args.joined),load(args.model),load(args.movement),
                        load(args.jingcai),load(args.top10),load(args.injury))
        Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_SOP_STRICT_RESULT",json.dumps({"date":result["target_beijing_date"],
           "games":result["game_count"],"ids":result["verified_jingcai_ids"],
           "model_ready":result["model_ready"],"fresh_jc":result["jingcai_fresh"],
           "decision":result["decision"]},ensure_ascii=False))
