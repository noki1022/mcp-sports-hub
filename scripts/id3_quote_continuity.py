#!/usr/bin/env python3
"""Classify temporary ID3 quote gaps from real, timestamped 007 captures.

An archived quote remains historical evidence, NEVER a current live market.
Never infer suspension/closure from a single missing response.
"""
from datetime import datetime,timezone
import argparse,json
from pathlib import Path

def utc(value):
    t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("NAIVE_CAPTURE_TIMESTAMP")
    return t.astimezone(timezone.utc)

def classify(board, archives):
    now=utc(board["captured_at_utc"])
    historical={}
    for snap in archives:
        if snap.get("requested_display_date")!=board.get("requested_display_date"):continue
        at=utc(snap["captured_at_utc"])
        if at>=now:continue
        for game in snap.get("nba_cba_games",[]):
            key=str(game.get("nba_game_id") or "")
            if not key:continue
            for market in ("full_spread","full_total"):
                point=(((game.get("markets") or {}).get(market) or {}).get("current") or {})
                if not all(isinstance(point.get(k),(float,int)) for k in ("line","first_side_water","second_side_water")):continue
                index=(key,market)
                if index not in historical or at>historical[index][0]:
                    historical[index]=(at,point,str(game.get("game_id") or ""))
    current={str(g["nba_game_id"]):g for g in board.get("nba_cba_games",[])}
    output=[]
    for f in board.get("upcoming_nba_games",[]):
        fid=str(f["nba_game_id"]);game=current.get(fid)
        result={"nba_game_id":fid,"home":f["home"],"away":f["away"],
                "game_id":str(game.get("game_id")) if game else None,
                "markets":{}}
        for market in ("full_spread","full_total"):
            p=(((game or {}).get("markets") or {}).get(market) or {}).get("current") or {}
            valid=all(isinstance(p.get(k),(float,int)) for k in ("line","first_side_water","second_side_water"))
            old=historical.get((fid,market))
            if valid:
                status="LIVE_OBSERVED_AT_CAPTURE"
            elif old:
                status="MISSING_NOW_PREVIOUS_VERIFIED_QUOTE"
            else:
                status="MISSING_NOW_NO_PRIOR_VERIFIED_QUOTE"
            row={"status":status,"observed_at_utc":board["captured_at_utc"] if valid else None,
                 "quote_is_live":valid,"closure_confirmed":False,
                 "current":p if valid else None}
            if old:
                row["previous_verified"]={"observed_at_utc":old[0].isoformat(),
                    "minutes_old":round((now-old[0]).total_seconds()/60,1),
                    "game_id":old[2],"current":old[1],"usable_as_live_odds":False}
                if game and old[2]!=str(game.get("game_id")):
                    row["previous_verified"]["identity_changed_warning"]=True
            result["markets"][market]=row
        output.append(result)
    return {"schema":"id3-quote-continuity-v1","captured_at_utc":board["captured_at_utc"],
            "target_date":board["requested_display_date"],"games":output,
            "warning":"A missing ID3 quote is NOT proof of bookmaker closure; archived prices are not live."}

def self_test():
    f={"nba_game_id":"a","home":"BOS","away":"LAL"}
    old={"requested_display_date":"2026-11-01","captured_at_utc":"2026-10-31T04:00:00Z",
         "nba_cba_games":[{"nba_game_id":"a","game_id":"1234","markets":{
         "full_spread":{"current":{"line":-3.5,"first_side_water":.92,"second_side_water":.91}}}}]}
    new={"requested_display_date":"2026-11-01","captured_at_utc":"2026-10-31T05:00:00Z",
         "upcoming_nba_games":[f],"nba_cba_games":[]}
    o=classify(new,[old]);g=o["games"][0]
    assert g["markets"]["full_spread"]["status"]=="MISSING_NOW_PREVIOUS_VERIFIED_QUOTE"
    assert g["markets"]["full_spread"]["previous_verified"]["minutes_old"]==60
    assert g["markets"]["full_spread"]["previous_verified"]["usable_as_live_odds"] is False
    assert g["markets"]["full_total"]["status"]=="MISSING_NOW_NO_PRIOR_VERIFIED_QUOTE"
    assert not g["markets"]["full_spread"]["closure_confirmed"]
    print("ID3_TEMPORARY_GAP_HISTORY_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--board");p.add_argument("--history",nargs="*",default=[])
    p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.board or not a.out:raise SystemExit("BOARD_AND_OUT_REQUIRED")
        now=json.loads(Path(a.board).read_text())
        prev=[]
        for path in a.history:
            try:prev.append(json.loads(Path(path).read_text()))
            except (OSError,ValueError):continue
        Path(a.out).write_text(json.dumps(classify(now,prev),ensure_ascii=False,indent=2)+"\n")
