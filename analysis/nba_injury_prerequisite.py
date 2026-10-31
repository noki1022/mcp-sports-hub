#!/usr/bin/env python3
"""Require explicit per-game official injury review before final five-market status.

Unknown injury data never silently becomes healthy; model probabilities remain
unadjusted until a separately validated player-impact model exists.
"""
import argparse,json
from pathlib import Path

def gate(forecast,context):
    by_id={str(x.get("game_id")):x for x in (context or {}).get("games",[])}
    if len(by_id)!=len((context or {}).get("games",[])):
        raise ValueError("DUPLICATE_INJURY_GAME_ID")
    for game in forecast.get("games",[]):
        injury=by_id.get(str(game.get("game_id"))) or {}
        home=injury.get("home") or {}
        away=injury.get("away") or {}
        published=all(x.get("report_state")=="PUBLISHED" for x in (home,away))
        quality=injury.get("quality")
        verified=(published and quality in ("PUBLISHED_AFFECTED","PUBLISHED_LISTED")
                  and bool(injury.get("source_captured_at_utc"))
                  and (context or {}).get("source")=="official NBA injury PDF")
        adjusted=injury.get("independent_model_probability_adjusted") is True
        game["injury_review"]={
            "quality":quality or "NOT_PROVIDED",
            "home":home,"away":away,
            "official_source_verified":verified,
            "source_captured_at_utc":injury.get("source_captured_at_utc"),
            "model_probability_adjusted":adjusted,
            "status":("REVIEWED_UNADJUSTED" if verified and not adjusted else
                      "REVIEWED_ADJUSTED" if verified else "PENDING_OFFICIAL_INJURY"),
        }
        game["final_signal_status"]=(
            "FINAL_INJURY_VERIFIED" if verified and adjusted else
            "PROVISIONAL_INJURY_UNADJUSTED" if verified else
            "PROVISIONAL_INJURY_UNVERIFIED")
        for market in (game.get("markets") or {}).values():
            if isinstance(market,dict):
                market["injury_gate"]=game["final_signal_status"]
                market["is_final_recommendation"]=bool(verified and adjusted and market.get("status")=="DIRECTION_ISSUED")
    forecast["injury_gate_version"]="official-injury-precondition-v1"
    forecast["final_signal_games"]=sum(x["final_signal_status"]=="FINAL_INJURY_VERIFIED" for x in forecast.get("games",[]))
    return forecast

def self_test():
    base={"games":[{"game_id":"1","markets":{"JINGCAI_WIN":{"status":"DIRECTION_ISSUED","direction":"HOME_WIN"}}}]}
    from copy import deepcopy
    a=gate(deepcopy(base),None)
    assert a["games"][0]["final_signal_status"]=="PROVISIONAL_INJURY_UNVERIFIED"
    ctx={"source":"official NBA injury PDF","games":[{"game_id":"1","quality":"PUBLISHED_AFFECTED",
         "source_captured_at_utc":"2026-10-31T07:00:00+00:00",
         "home":{"report_state":"PUBLISHED","players":[{"name":"A","status":"Out"}]},
         "away":{"report_state":"PUBLISHED","players":[]},
         "independent_model_probability_adjusted":False}]}
    b=gate(deepcopy(base),ctx)
    assert b["games"][0]["final_signal_status"]=="PROVISIONAL_INJURY_UNADJUSTED"
    assert not b["games"][0]["markets"]["JINGCAI_WIN"]["is_final_recommendation"]
    ctx["games"][0]["independent_model_probability_adjusted"]=True
    c=gate(deepcopy(base),ctx)
    assert c["games"][0]["final_signal_status"]=="FINAL_INJURY_VERIFIED"
    print("INJURY_PREREQUISITE_GATE_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--five");p.add_argument("--injury");p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        obj=json.loads(Path(a.five).read_text())
        context=json.loads(Path(a.injury).read_text()) if a.injury and Path(a.injury).exists() else None
        Path(a.out).write_text(json.dumps(gate(obj,context),ensure_ascii=False,indent=2)+"\n")
