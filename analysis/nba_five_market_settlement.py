#!/usr/bin/env python3
"""Chronological five-market NBA direction settlement; frozen pre-tip forecasts only.

One row per match/market. EXCLUDED or UNSETTLED do not count as misses or
numerator/denominator. PUSH excluded from directional hit rate, shown separately.
No post-game quote/model recomputation. Crown home gives (+ raw institutional
line); JC plus is home receives, so stored signed_home_handicap applies to both.
"""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
from nba_nightly_two_market_settlement import scores_for
from nba_five_markets import MARKETS

def parse(x):
    try:
        z=datetime.fromisoformat(str(x).replace("Z","+00:00"))
        return z if z.tzinfo else None
    except (ValueError,TypeError):return None

def settle(frozen,scores,target):
    if frozen.get("target_date")!=target:raise ValueError("WRONG_BEIJING_DAY")
    result=[]
    for game in frozen.get("games",[]):
        source=scores.get(str(game.get("nba_game_id"))) or {}
        final=source.get("completed") is True and isinstance(source.get("home_points"),int) and isinstance(source.get("away_points"),int)
        hp=source.get("home_points");ap=source.get("away_points")
        tip=parse(game.get("tipoff_beijing"))
        row={"game_id":game["game_id"],"nba_game_id":game.get("nba_game_id"),
             "jingcai_number":game.get("jingcai_number"),
             "home_team":game.get("home_team"),"away_team":game.get("away_team"),
             "home_points":hp if final else None,"away_points":ap if final else None,"markets":{}}
        for m in MARKETS:
            selection=(game.get("markets") or {}).get(m) or {}
            direction=selection.get("direction")
            lock=parse(selection.get("captured_at_utc"))
            status=selection.get("status")
            line=selection.get("line")
            signed=selection.get("signed_home_handicap")
            outcome="UNSETTLED"
            reason=None
            if status=="NOT_ON_SALE_USER_CONFIRMED":
                outcome="EXCLUDED_NOT_ON_SALE";reason="JINGCAI_MARKET_NOT_SOLD"
            elif status!="DIRECTION_ISSUED":
                outcome="EXCLUDED_NO_DIRECTION";reason=status or "NO_FROZEN_DIRECTION"
            elif not tip or not lock or lock>=tip:
                outcome="EXCLUDED_INVALID_PRETIP_LOCK";reason="QUOTE_NOT_FROZEN_BEFORE_TIP"
            elif not final:
                outcome="UNSETTLED";reason="OFFICIAL_FINAL_SCORE_MISSING"
            else:
                margin=hp-ap
                if m=="JINGCAI_WIN":
                    value=margin
                    if direction not in ("HOME_WIN","AWAY_WIN"):
                        outcome="EXCLUDED_NO_DIRECTION";reason="INVALID_SIDE"
                elif m in ("JINGCAI_HANDICAP","CROWN_HANDICAP"):
                    if not isinstance(signed,(int,float)) or not math.isfinite(signed) or direction not in ("HOME_COVER","AWAY_COVER"):
                        outcome="EXCLUDED_NO_DIRECTION";reason="INVALID_HANDICAP_SIDE_OR_LINE"
                    else:value=margin+signed
                else:
                    if not isinstance(line,(int,float)) or not math.isfinite(line) or direction not in ("OVER","UNDER"):
                        outcome="EXCLUDED_NO_DIRECTION";reason="INVALID_TOTAL_SIDE_OR_LINE"
                    else:value=hp+ap-line
                if outcome=="UNSETTLED" and reason is None:
                    if abs(value)<1e-8:outcome="PUSH"
                    elif (value>0)==(direction in ("HOME_WIN","HOME_COVER","OVER")):outcome="HIT"
                    else:outcome="MISS"
            row["markets"][m]={"direction":direction,"source":selection.get("source"),
                "line":line,"signed_home_handicap":signed,
                "frozen_capture_utc":selection.get("captured_at_utc"),
                "outcome":outcome,"reason":reason}
        result.append(row)
    totals={}
    for key in MARKETS:
        sub=[g["markets"][key]["outcome"] for g in result]
        hits=sub.count("HIT");misses=sub.count("MISS")
        totals[key]={"hits":hits,"misses":misses,"pushes":sub.count("PUSH"),
            "excluded":sum(x.startswith("EXCLUDED") for x in sub),
            "unsettled":sub.count("UNSETTLED"),"graded":hits+misses,
            "hit_rate":round(hits/(hits+misses),6) if hits+misses else None}
    return {"schema_version":"nba-five-market-settlement-v1",
        "beijing_date":target,"games":result,"summary":totals,
        "settlement_policy":"As-of frozen pretip directional hit rate; no odds retrofits; pushes excluded",
        "all_five_predictions_available":all(totals[k]["graded"]>0 for k in MARKETS)}

def self_test():
    five={"target_date":"2026-10-31","games":[{"game_id":"1","nba_game_id":"a",
      "jingcai_number":"周五314","home_team":"主","away_team":"客",
      "tipoff_beijing":"2026-10-31T08:00:00+08:00",
      "markets":{
        "JINGCAI_WIN":{"status":"DIRECTION_ISSUED","direction":"AWAY_WIN","captured_at_utc":"2026-10-30T14:00:00Z"},
        "JINGCAI_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"HOME_COVER","line":7.5,"signed_home_handicap":7.5,"captured_at_utc":"2026-10-30T14:00:00Z"},
        "JINGCAI_TOTAL":{"status":"DIRECTION_ISSUED","direction":"OVER","line":225.5,"captured_at_utc":"2026-10-30T14:00:00Z"},
        "CROWN_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"AWAY_COVER","line":6.5,"signed_home_handicap":-6.5,"captured_at_utc":"2026-10-30T14:00:00Z"},
        "CROWN_TOTAL":{"status":"DIRECTION_ISSUED","direction":"UNDER","line":229.5,"captured_at_utc":"2026-10-30T14:00:00Z"}}}]}
    # 108-113, total=221, margin=-5
    s=settle(five,{"a":{"completed":True,"home_points":108,"away_points":113}},"2026-10-31")
    assert [s["games"][0]["markets"][k]["outcome"] for k in MARKETS]==["HIT","HIT","MISS","HIT","HIT"]
    assert s["summary"]["JINGCAI_TOTAL"]["hit_rate"]==0
    assert s["summary"]["CROWN_TOTAL"]["hit_rate"]==1
    five["games"][0]["markets"]["JINGCAI_WIN"]={"status":"NOT_ON_SALE_USER_CONFIRMED"}
    s=settle(five,{"a":{"completed":True,"home_points":108,"away_points":113}},"2026-10-31")
    assert s["summary"]["JINGCAI_WIN"]["excluded"]==1 and s["summary"]["JINGCAI_WIN"]["graded"]==0
    five["games"][0]["markets"]["JINGCAI_HANDICAP"]["captured_at_utc"]="2026-10-31T09:00:00Z"
    s=settle(five,{"a":{"completed":True,"home_points":108,"away_points":113}},"2026-10-31")
    assert s["summary"]["JINGCAI_HANDICAP"]["excluded"]==1
    print("NBA_FIVE_MARKET_INDEPENDENT_SETTLEMENT_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--forecast");p.add_argument("--day");p.add_argument("--scores")
    p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not all((a.forecast,a.day,a.out)):raise SystemExit("FORECAST_DAY_OUT_REQUIRED")
        frozen=json.loads(Path(a.forecast).read_text(encoding="utf-8"))
        scores=json.loads(Path(a.scores).read_text(encoding="utf-8")) if a.scores else scores_for(a.day)
        output=settle(frozen,scores,a.day)
        Path(a.out).write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_FIVE_MARKET_SETTLEMENT",json.dumps(output["summary"],ensure_ascii=False))
