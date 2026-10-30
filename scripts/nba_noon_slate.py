#!/usr/bin/env python3
"""Immutable 12:00 Beijing official NBA slate for ALL captures through next 06:30.

The official NBA event identity (not the volatile 007 odds coverage) defines
the cohort. New market quotes for *already locked* games are allowed. Changes
to official game IDs, team identities or UTC tipoff are fail-closed. Missing
quotes never result in fabricated prices, and must be reported explicitly.
"""
from __future__ import annotations
import argparse,json
from datetime import datetime,date,timedelta,time
from pathlib import Path
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")
VERSION="nba-beijing-noon-cohort-v1"

def abort(reason):
    raise ValueError("NBA_NOON_SLATE_"+reason)

def aware(stamp):
    try:
        t=datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
        if t.tzinfo is None:abort("NAIVE_TIMESTAMP")
        return t.astimezone(BJ)
    except (ValueError,TypeError) as exc:
        abort("INVALID_TIMESTAMP_"+str(exc))

def official_identity(board):
    day=str(board.get("requested_display_date") or "")
    try:date.fromisoformat(day)
    except ValueError:abort("INVALID_BEIJING_DATE")
    source=board.get("upcoming_nba_games") or []
    if not isinstance(source,list):abort("OFFICIAL_SCHEDULE_NOT_LIST")
    result={}
    for fixture in source:
        fid=str(fixture.get("nba_game_id") or "")
        home=str(fixture.get("home") or "").strip()
        away=str(fixture.get("away") or "").strip()
        tip=str(fixture.get("utc_tip") or "")
        if not fid or fid in result:abort("DUPLICATE_OR_MISSING_OFFICIAL_ID")
        if not home or not away or home==away:abort("INVALID_MATCHUP")
        if str(fixture.get("beijing_date"))!=day:abort("WRONG_BEIJING_FIXTURE_DATE")
        if aware(tip).date().isoformat()!=day:abort("UTC_TIP_DATE_NOT_BEIJING_DATE")
        result[fid]={"nba_game_id":fid,"home":home,"away":away,"utc_tip":tip,
                     "beijing_date":day}
    if not result:abort("NO_OFFICIAL_NBA_GAMES")
    if board.get("official_schedule_count")!=len(result):
        abort("OFFICIAL_COUNT_NOT_VERIFIED")
    return result

def market_identity(board,official):
    found={}
    for g in board.get("nba_cba_games",[]):
        if g.get("league")!="NBA":abort("NON_NBA_IN_LOCKED_BOARD")
        fid=str(g.get("nba_game_id") or "")
        if fid not in official or fid in found:abort("EXTRA_OR_DUPLICATE_MARKET_GAME")
        if g.get("display_date")!=board.get("requested_display_date"):
            abort("MARKET_WRONG_BEIJING_DATE")
        if not str(g.get("game_id") or "").isdigit():abort("INVALID_007_ID")
        if aware(g.get("start_time_beijing")).date().isoformat()!=board["requested_display_date"]:
            abort("MARKET_TIP_WRONG_DATE")
        found[fid]=str(g["game_id"])
    if len(set(found.values()))!=len(found):abort("REUSED_007_MARKET_ID")
    return found

def freeze(board):
    cap=aware(board["captured_at_utc"])
    game_date=date.fromisoformat(board["requested_display_date"])
    if cap.date()!=game_date-timedelta(days=1) or not time(12,0)<=cap.time().replace(tzinfo=None)<time(13,0):
        abort("NOON_CAPTURE_OUTSIDE_12_CLOCK_WINDOW")
    fixture=official_identity(board)
    prices=market_identity(board,fixture)
    return {"schema_version":VERSION,"target_beijing_date":str(game_date),
            "baseline_slot":"1200","captured_at_utc":board["captured_at_utc"],
            "official_games":fixture,"first_available_007":prices,
            "official_count":len(fixture),"baseline_quote_count":len(prices),
            "rule":"SAME_OFFICIAL_EVENT_IDS_AND_TEAMS_ALL_SLOTS"}

def recover(archive,target):
    """Create an immutable cohort from a genuine, timestamped archived noon report.
    Its actual capture time is recorded; no imaginary 12:00 observation is made.
    """
    if archive.get("requested_display_date")!=target:abort("ARCHIVE_DATE_MISMATCH")
    cap=aware(archive["captured_at_utc"])
    if cap.date()!=date.fromisoformat(target)-timedelta(days=1):
        abort("ARCHIVE_NOT_PREVIOUS_DAY")
    if not time(12,0)<=cap.time().replace(tzinfo=None)<time(14,0):
        abort("ARCHIVE_NOT_NOON_RECOVERY_WINDOW")
    result=freeze(archive) if cap.hour==12 else {
        "schema_version":VERSION,"target_beijing_date":target,"baseline_slot":"1200",
        "captured_at_utc":archive["captured_at_utc"],
        "official_games":official_identity(archive),
        "first_available_007":market_identity(archive,official_identity(archive)),
        "recovery_source":"ARCHIVED_NOON_SLOT_ACTUAL_CAPTURE_TIMESTAMP",
        "noon_on_time":False}
    return result

def enforce(board,locked):
    if locked.get("schema_version")!=VERSION or locked.get("baseline_slot")!="1200":
        abort("MISSING_VALID_NOON_LOCK")
    target=str(board.get("requested_display_date") or "")
    if locked.get("target_beijing_date")!=target:abort("TARGET_DAY_CHANGED")
    first=aware(locked["captured_at_utc"])
    now=aware(board["captured_at_utc"])
    if not first<now:abort("NOT_AFTER_NOON_BASELINE")
    if now.date() not in (first.date(),first.date()+timedelta(days=1)):
        abort("OUTSIDE_ONE_OVERNIGHT_PERIOD")
    frozen=locked.get("official_games")
    current=official_identity(board)
    if current!=frozen:abort("OFFICIAL_GAME_LIST_OR_TIP_CHANGED")
    fresh=market_identity(board,current)
    prior=locked.get("first_available_007") or {}
    changed={k for k,v in prior.items() if k in fresh and fresh[k]!=v}
    if changed:abort("PRIOR_007_ID_CHANGED_"+",".join(sorted(changed)))
    official_ids=set(frozen)
    observed=set(fresh)
    result={**board,"nba_noon_cohort":{
        "schema_version":VERSION,"state":"SAME_NOON_OFFICIAL_SLATE_VERIFIED",
        "anchor_slot":"1200","anchor_timestamp_utc":locked["captured_at_utc"],
        "target_beijing_date":target,"official_count":len(official_ids),
        "priced_games":len(observed),"missing_price_game_ids":sorted(official_ids-observed),
        "newly_priced_since_noon":sorted(observed-set(prior)),
        "same_official_game_ids":True,"no_betting_signal":"NO_BET"}}
    # Same batch is the OFFICIAL games, not the variable subset with odds.
    # Preserve the official fixture list and flag absent prices per game.
    result["nba_noon_cohort"]["games"]=[
        {"nba_game_id":fid,**frozen[fid],
         "quote_status":"PRICED" if fid in observed else "QUOTE_UNAVAILABLE",
         "titan007_id":fresh.get(fid)}
        for fid in sorted(frozen)]
    return result

def self_test():
    from copy import deepcopy
    day="2026-10-31"
    fixtures=[
        {"nba_game_id":"a","home":"BOS","away":"NYK","beijing_date":day,
         "utc_tip":"2026-10-30T23:00:00+00:00"},
        {"nba_game_id":"b","home":"GSW","away":"LAL","beijing_date":day,
         "utc_tip":"2026-10-31T02:00:00+00:00"}]
    g={"nba_game_id":"a","game_id":"12345","league":"NBA",
       "display_date":day,"start_time_beijing":day+"T07:00+08:00"}
    base={"requested_display_date":day,"captured_at_utc":"2026-10-30T04:01:00Z",
          "upcoming_nba_games":fixtures,"official_schedule_count":2,
          "nba_cba_games":[g]}
    lock=freeze(base)
    assert lock["official_count"]==2 and lock["baseline_quote_count"]==1
    for capture in ("2026-10-30T06:00:00Z", "2026-10-30T07:00:00Z",
                    "2026-10-30T10:00:00Z","2026-10-30T13:00:00Z",
                    "2026-10-30T13:30:00Z","2026-10-30T22:30:00Z"):
        b={**base,"captured_at_utc":capture,
           "nba_cba_games":[g,{**g,"nba_game_id":"b","game_id":"78910",
                               "start_time_beijing":day+"T10:00+08:00"}]}
        out=enforce(b,lock)
        assert out["nba_noon_cohort"]["state"]=="SAME_NOON_OFFICIAL_SLATE_VERIFIED"
        assert out["nba_noon_cohort"]["newly_priced_since_noon"]==["b"]
    morning={**base,"captured_at_utc":"2026-10-30T22:30:00Z",
             "nba_cba_games":[g]}
    assert enforce(morning,lock)["nba_noon_cohort"]["missing_price_game_ids"]==["b"]
    for label,mutate in [
        ("swapped",lambda z:z["upcoming_nba_games"][0].update(home="MIA")),
        ("extra",lambda z:z["nba_cba_games"].append({**g,"nba_game_id":"c","game_id":"00009"})),
        ("wrongday",lambda z:z.update(requested_display_date="2026-11-01")),
        ("idchanged",lambda z:z["nba_cba_games"][0].update(game_id="22222")),
    ]:
        x=deepcopy(morning);mutate(x)
        try:enforce(x,lock)
        except ValueError:pass
        else:raise AssertionError("UNLOCKED_SLATE_ACCEPTED_"+label)
    print("NBA_NOON_TO_0630_IMMUTABLE_OFFICIAL_SLATE_SELF_TEST_PASS")

def cli():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("freeze","enforce","recover","self-test"))
    p.add_argument("--joined");p.add_argument("--lock");p.add_argument("--out");p.add_argument("--archive")
    a=p.parse_args()
    if a.mode=="self-test":return self_test()
    if not a.out:raise SystemExit("OUT_REQUIRED")
    if a.mode=="recover":
        if not a.archive or not a.joined:raise SystemExit("ARCHIVE_AND_JOINED_REQUIRED")
        board=json.loads(Path(a.joined).read_text(encoding="utf-8"))
        archived=json.loads(Path(a.archive).read_text(encoding="utf-8"))
        result=recover(archived,board["requested_display_date"])
        dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():abort("ALREADY_LOCKED_NO_OVERWRITE")
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("NBA_NOON_ARCHIVE_RECOVERED",result["captured_at_utc"])
        return
    if not a.joined:raise SystemExit("JOINED_REQUIRED")
    board=json.loads(Path(a.joined).read_text(encoding="utf-8"))
    dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
    if a.mode=="freeze":
        result=freeze(board)
        if dest.exists():
            old=json.loads(dest.read_text(encoding="utf-8"))
            if old.get("official_games")!=result["official_games"] or old.get("target_beijing_date")!=result["target_beijing_date"]:
                abort("EXISTING_NOON_LOCK_CONFLICT")
            # Preserve original baseline timestamp and 007 coverage on retries.
            result=old
    else:
        if not a.lock or not Path(a.lock).is_file():abort("NO_PRIOR_NOON_LOCK_AVAILABLE")
        result=enforce(board,json.loads(Path(a.lock).read_text(encoding="utf-8")))
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_NOON_SLATE_"+a.mode.upper(),"target",board["requested_display_date"],
          "official",len(result.get("official_games",result.get("nba_noon_cohort",{}).get("games",[]))))
if __name__=="__main__":cli()
