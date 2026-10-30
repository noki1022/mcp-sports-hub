#!/usr/bin/env python3
"""Fail-closed 21:30/06:30 NBA slate lock: no silent game substitutions."""
import argparse,json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
BJ=ZoneInfo("Asia/Shanghai")
VERSION="nba-overnight-cohort-v1"
def abort(reason):raise ValueError("OVERNIGHT_COHORT_"+reason)
def local(t):return datetime.fromisoformat(t.replace("Z","+00:00")).astimezone(BJ)
def fixtures(board):
    target=board["requested_display_date"]
    out={}
    for g in board.get("upcoming_nba_games",[]):
        k=str(g["nba_game_id"])
        if k in out or g["beijing_date"]!=target:abort("DUPLICATE_OR_WRONG_DAY")
        out[k]={"id":k,"home":g["home"],"away":g["away"],"date":target,"tip":g["beijing_tip"]}
    if not out or len(out)!=board.get("official_schedule_count"):abort("OFFICIAL_SLATE_INCOMPLETE")
    return out
def matched(board,official):
    out={}
    for g in board.get("nba_cba_games",[]):
        if g.get("league")!="NBA":continue
        k=str(g["nba_game_id"])
        if k not in official or k in out or g["display_date"]!=board["requested_display_date"]:abort("BAD_007_GAME")
        out[k]=str(g["game_id"])
    return out
def lock(board):
    day=board["requested_display_date"]
    t=local(board["captured_at_utc"])
    if (t.date()+timedelta(days=1)).isoformat()!=day or not 21<=t.hour<22:
        abort("NOT_EVENING_BEFORE_TARGET")
    off=fixtures(board);sites=matched(board,off)
    if not sites:abort("NO_PRICED_GAMES")
    return {"schema_version":VERSION,"target_date":day,"source_slot":"2130",
            "captured_at_utc":board["captured_at_utc"],"official_games":off,
            "priced_nba_to_007":sites}
def enforce(board,frozen,phase):
    if frozen.get("schema_version")!=VERSION or frozen.get("source_slot")!="2130":abort("NO_VALID_2130_LOCK")
    if board["requested_display_date"]!=frozen["target_date"]:abort("OVERNIGHT_DATE_CHANGED")
    t=local(board["captured_at_utc"])
    day=t.date().isoformat()
    if phase=="morning" and (day!=frozen["target_date"] or not 6<=t.hour<7):
        abort("WRONG_MORNING")
    if local(board["captured_at_utc"])<=local(frozen["captured_at_utc"]):abort("NONINCREASING_CAPTURE_TIME")
    current=fixtures(board)
    if current!=frozen["official_games"]:abort("OFFICIAL_SLATE_CHANGED")
    sites=matched(board,current);old=frozen["priced_nba_to_007"]
    if any(k not in sites for k in old):abort("LOCKED_GAME_MISSING")
    if any(sites[k]!=v for k,v in old.items()):abort("007_ID_CHANGED")
    games={str(g["nba_game_id"]):g for g in board["nba_cba_games"] if g.get("league")=="NBA"}
    selected=[games[k] for k in old]
    missing=set(current)-set(old)
    return {**board,"nba_cba_games":selected,
        "nba_cba_joined_for_date":len(selected),"markets_joined_for_date":len(selected),
        "nba_markets_missing":len(missing),
        "overnight_cohort":{"status":"EXACT_2130_SLATE_MATCH","target_date":frozen["target_date"],
            "official_count":len(current),"priced_count":len(old),
            "extra_market_games_excluded":sorted(set(sites)-set(old)),
            "unpriced_from_2130":sorted(missing)}}
def self_test():
    from copy import deepcopy
    b={"requested_display_date":"2026-10-31","captured_at_utc":"2026-10-30T13:31:00+00:00",
       "official_schedule_count":2,"upcoming_nba_games":[
        {"nba_game_id":"1","home":"BOS","away":"NYK","beijing_date":"2026-10-31","beijing_tip":"2026-10-31T07:30+08:00"},
        {"nba_game_id":"2","home":"LAL","away":"GSW","beijing_date":"2026-10-31","beijing_tip":"2026-10-31T08:00+08:00"}],
       "nba_cba_games":[{"nba_game_id":"1","game_id":"54321","league":"NBA","display_date":"2026-10-31"}]}
    f=lock(b);morning=deepcopy(b);morning["captured_at_utc"]="2026-10-30T22:31:00+00:00"
    morning["nba_cba_games"].append({"nba_game_id":"2","game_id":"67890","league":"NBA","display_date":"2026-10-31"})
    good=enforce(morning,f,"morning")
    assert len(good["nba_cba_games"])==1 and good["overnight_cohort"]["extra_market_games_excluded"]==["2"]
    for change in ("missing","switched","new_day","official"):
        bad=deepcopy(morning)
        if change=="missing":bad["nba_cba_games"]=bad["nba_cba_games"][1:]
        if change=="switched":bad["nba_cba_games"][0]["game_id"]="99999"
        if change=="new_day":bad["requested_display_date"]="2026-11-01"
        if change=="official":bad["upcoming_nba_games"][0]["home"]="MIA"
        try:enforce(bad,f,"morning")
        except ValueError:pass
        else:raise AssertionError("INVALID_SAME_SLATE_ACCEPTED_"+change)
    print("OVERNIGHT_2130_0630_SAME_SLATE_TEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=("lock","enforce","self-test"))
    p.add_argument("--joined");p.add_argument("--cohort");p.add_argument("--out");p.add_argument("--phase",default="morning")
    a=p.parse_args()
    if a.command=="self-test":self_test()
    else:
        if not a.joined or not a.out:raise SystemExit("REQUIRED_INPUTS_MISSING")
        board=json.loads(Path(a.joined).read_text())
        if a.command=="lock":
            result=lock(board)
            dest=Path(a.out)
            if dest.exists():
                previous=json.loads(dest.read_text())
                if (previous.get("target_date")!=result["target_date"] or
                    previous.get("official_games")!=result["official_games"] or
                    previous.get("priced_nba_to_007")!=result["priced_nba_to_007"]):
                    abort("LOCK_IDENTITY_CHANGED")
                print("OVERNIGHT_2130_LOCK_REUSED",dest)
                result=previous
        else:
            if not a.cohort or not Path(a.cohort).is_file():abort("NO_PRIOR_2130_LOCK")
            result=enforce(board,json.loads(Path(a.cohort).read_text()),a.phase)
        dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("OVERNIGHT_COHORT_"+a.command.upper(),len(result.get("nba_cba_games",[])))
