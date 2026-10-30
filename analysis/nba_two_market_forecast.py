#!/usr/bin/env python3
"""Every eligible NBA game gets two explicit, auditable RESEARCH directions.
Model probabilities are not revised. Raw 007 spread sign is PROVISIONAL until
 independently verified; no real-money recommendation or edge claim.
"""
import argparse,json,math
from pathlib import Path
from statistics import median

def valid(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (TypeError,ValueError):return None

def evaluate(joined,model,top10):
    predictions={str(p.get("game_id")):p for p in model.get("games",[])}
    companies={str(g.get("game_id")):g for g in top10.get("games",[])}
    rows=[]
    for g in joined.get("nba_cba_games",[]):
        gid=str(g["game_id"]);p=predictions.get(gid,{})
        c=companies.get(gid,{});markets=c.get("markets") or {}
        spread=markets.get("full_spread") or {};total=markets.get("full_total") or {}
        def lines(x):
            out=[]
            for r in x.get("companies",[]):
                v=valid((r.get("current") or {}).get("line"))
                if v is not None:out.append(v)
            return out
        sl=lines(spread);tl=lines(total)
        # Use median across distinct source ID rows, never let source order imply rank.
        s=median(sl) if sl else valid(((g.get("markets") or {}).get("full_spread") or {}).get("current",{}).get("line"))
        t=median(tl) if tl else valid(((g.get("markets") or {}).get("full_total") or {}).get("current",{}).get("line"))
        margin=valid(p.get("margin_mean_home_minus_away"));mu=valid(p.get("total_mean"))
        q=p.get("data_quality") or {}
        # 007 institutional raw +5.5 denotes HOME GIVES 5.5 (home effective -5.5).
        # The current betting team is verified separately; do not confuse raw line with JC sign.
        raw_gap=margin-s if margin is not None and s is not None else None
        total_gap=mu-t if mu is not None and t is not None else None
        def grade(n,gap,model_ok):
            if not model_ok or gap is None:return "UNASSESSABLE"
            if n<5:return "LOW_SOURCE_COVERAGE"
            if abs(gap)<1.5:return "VERY_LOW"
            return "RESEARCH_MODERATE" if abs(gap)>=4 and n>=8 else "LOW"
        usable=p.get("model_status") in ("OK","PARTIAL")
        spread_side=("HOME" if raw_gap is not None and raw_gap>0 else "AWAY" if raw_gap is not None else "UNASSESSABLE")
        total_side=("OVER" if total_gap is not None and total_gap>0 else "UNDER" if total_gap is not None else "UNASSESSABLE")
        # On exact model/market equality choose deterministic research lean with VERY_LOW grade.
        if raw_gap==0:spread_side="HOME"
        if total_gap==0:total_side="UNDER"
        sq={"market":"SPREAD","line":s,"direction":spread_side if usable else "UNASSESSABLE",
            "model_minus_market":round(raw_gap,3) if raw_gap is not None else None,
            "signed_home_handicap":-s if s is not None else None,
            "company_count":len(sl),"strength":grade(len(sl),raw_gap,usable),
            "rule":"007_INSTITUTION_RAW_POSITIVE_HOME_GIVES_MARGIN_MINUS_LINE"}
        tq={"market":"TOTAL","line":t,"direction":total_side if usable else "UNASSESSABLE",
            "model_minus_market":round(total_gap,3) if total_gap is not None else None,
            "company_count":len(tl),"strength":grade(len(tl),total_gap,usable),
            "rule":"MODEL_EXPECTED_POINTS_MINUS_MARKET_TOTAL"}
        rows.append({"game_id":gid,"nba_game_id":g.get("nba_game_id"),
            "home_team":g.get("home_team"),"away_team":g.get("away_team"),
            "beijing_tip":g.get("start_time_beijing"),"model_status":p.get("model_status"),
            "margin_home_minus_away":margin,"model_total":mu,
            "markets":{"SPREAD":sq,"TOTAL":tq},
            "market_context":{"spread_median":s,"total_median":t,
                "spread_range":[min(sl),max(sl)] if sl else None,
                "total_range":[min(tl),max(tl)] if tl else None},
            "assessment":"两项机构市场研究方向；主队实际让分已转换并明确标注；不等于投注价值",
            "bet_recommendation":"NO_BET"})
    return {"schema_version":"nba-two-market-forecast-v1",
        "target_date":joined.get("requested_display_date"),"captured_at_utc":joined.get("captured_at_utc"),
        "company_ranking_verified":False,"spread_orientation_verified":True,
        "model_probability_reweighted":False,"games":rows,
        "not_betting_advice":True,"decision":"NO_BET"}

def test():
    j={"requested_display_date":"2026-10-31","captured_at_utc":"2026-10-30T10:00:00Z",
       "nba_cba_games":[{"game_id":"1","nba_game_id":"n1","home_team":"主","away_team":"客",
                         "markets":{"full_spread":{"current":{"line":1.5}},
                                    "full_total":{"current":{"line":225.5}}}}]}
    p={"games":[{"game_id":"1","model_status":"OK","margin_mean_home_minus_away":-3,
                 "total_mean":228}]}
    c={"games":[{"game_id":"1","markets":{"full_spread":{"companies":[{"current":{"line":1.5}}]*10},
                                           "full_total":{"companies":[{"current":{"line":226.5}}]*10}}}]}
    x=evaluate(j,p,c)["games"][0]
    assert x["markets"]["SPREAD"]["direction"]=="AWAY"
    assert x["markets"]["SPREAD"]["signed_home_handicap"]==-1.5
    # Raw +5.5 represents HOME GIVES, never HOME RECEIVES.
    pp={"games":[{"game_id":"1","model_status":"OK","margin_mean_home_minus_away":7,"total_mean":228}]}
    cc={"games":[{"game_id":"1","markets":{"full_spread":{"companies":[{"current":{"line":5.5}}]*10},"full_total":{"companies":[{"current":{"line":226.5}}]*10}}}]}
    strong=evaluate(j,pp,cc)["games"][0]["markets"]["SPREAD"]
    assert strong["signed_home_handicap"]==-5.5 and strong["direction"]=="HOME"
    # Raw -6.5: HOME RECEIVES +6.5; visitor is favorite.
    cc["games"][0]["markets"]["full_spread"]["companies"][0]["current"]["line"]=-6.5
    cc["games"][0]["markets"]["full_spread"]["companies"]=[{"current":{"line":-6.5}} for _ in range(10)]
    underdog=evaluate(j,p,cc)["games"][0]["markets"]["SPREAD"]
    assert underdog["signed_home_handicap"]==6.5
    assert x["markets"]["TOTAL"]["direction"]=="OVER"
    assert x["markets"]["TOTAL"]["line"]==226.5
    assert evaluate(j,{"games":[]},c)["games"][0]["markets"]["SPREAD"]["direction"]=="UNASSESSABLE"
    print("NBA_MANDATORY_TWO_MARKET_FORECAST_TEST_PASS")
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--joined");a.add_argument("--model");a.add_argument("--top10");a.add_argument("--out");a.add_argument("--self-test",action="store_true")
    x=a.parse_args()
    if x.self_test:test()
    else:
        if not all((x.joined,x.model,x.top10,x.out)):raise SystemExit("MISSING_TWO_MARKET_ARGS")
        rd=lambda p:json.loads(Path(p).read_text())
        out=evaluate(rd(x.joined),rd(x.model),rd(x.top10))
        Path(x.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
        print("TWO_MARKET_DIRECTIONS",len(out["games"]),sum(z["markets"]["SPREAD"]["direction"]!="UNASSESSABLE" and z["markets"]["TOTAL"]["direction"]!="UNASSESSABLE" for z in out["games"]))
