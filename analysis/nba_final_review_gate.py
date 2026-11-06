#!/usr/bin/env python3
"""Readiness gate: emit a formal five-market review only after the last NBA game is FINAL.

Authority: frozen 21:30 / 06:30 pre-tip slate, verified NBA event IDs, ESPN
official completed results. Last scheduled tip time is NOT completion. Handles
cross-midnight Beijing cohorts and postponements by waiting, never by silently
excluding an unplayed event. No post-tip replacement of forecasts/odds.
"""
from __future__ import annotations
import argparse,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from nba_nightly_two_market_settlement import scores_for

BJ=ZoneInfo("Asia/Shanghai")
ACCEPTED="API_ACCEPTED_NOT_DEVICE_CONFIRMED"

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def point_in_time_valid(frozen,games):
    """Accept only a whole-board forecast whose model and quoted prices predate tip.

    For a 03:00/08:30 slate, the 06:30 run may contain early games that already
    tipped. It must never displace an earlier genuinely pre-tip full-board file.
    """
    def aware(value):
        try:
            stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        except (ValueError,TypeError):
            return None
        return stamp if stamp.tzinfo is not None else None

    board_time=aware(frozen.get("board_capture_utc"))
    if board_time is None:
        return False
    for game in games:
        tip=aware(game.get("tipoff_beijing"))
        if tip is None or board_time>=tip:
            return False
        markets=game.get("markets") or {}
        if not isinstance(markets,dict):
            return False
        for market in markets.values():
            if not isinstance(market,dict):
                return False
            if market.get("status")=="DIRECTION_ISSUED":
                quote_time=aware(market.get("captured_at_utc"))
                if quote_time is None or quote_time>=tip:
                    return False
    return True

def frozen_source(root,day):
    """ONLY canonical Beijing 21:00 frozen five-play answer can be graded.

    Never use 22:00/23:00, missing-slot fallbacks, 21:30 or next-day 06:30
    as an implicit replacement. Existing source still must predate kickoff.
    """
    file=root/"reports"/"daily"/day/"2100"/"nba_five_market_forecast.json"
    if not file.is_file():
        return None
    frozen=read_json(file)
    games=frozen_games(frozen,day)
    official=root/"reports"/"noon-cohorts"/day/"1200.json"
    if official.is_file():
        ids=set((read_json(official).get("official_games") or {}).keys())
        if not ids:raise ValueError("NOON_OFFICIAL_COHORT_EMPTY")
        if {str(g["nba_game_id"]) for g in games}!=ids:
            raise ValueError("2100_COHORT_NOT_EQUAL_TO_NOON_OFFICIAL_GAMES")
    if not point_in_time_valid(frozen,games):
        raise ValueError("2100_FROZEN_BOARD_HAS_POSTTIP_INFORMATION")
    return file

def reviewed(root,day):
    p=root/"reports"/"five-market-settled"/day/"2200.json"
    if not p.is_file():return False
    try:
        marker=read_json(p)
        folder=p.parent
        settlement=read_json(folder/"settlement.json")
        html=(folder/"report.html").read_text(encoding="utf-8")
        return (marker.get("state")==ACCEPTED and
                settlement.get("beijing_date")==day and
                bool(settlement.get("games")) and
                all(m.get("unsettled")==0 for m in settlement.get("summary",{}).values()) and
                len(settlement.get("summary",{}))==5 and
                "五玩法" in html)
    except (ValueError,OSError,KeyError,TypeError):return False

def frozen_games(frozen,day):
    if frozen.get("target_date")!=day:raise ValueError("FORECAST_DATE_MISMATCH")
    games=frozen.get("games")
    if not isinstance(games,list) or not games:raise ValueError("EMPTY_FROZEN_NBA_SLATE")
    ids=[]
    for g in games:
        eid=str(g.get("nba_game_id") or "")
        if not eid:raise ValueError("MISSING_FROZEN_NBA_GAME_ID")
        ids.append(eid)
        try:tip=datetime.fromisoformat(str(g["tipoff_beijing"]).replace("Z","+00:00"))
        except (KeyError,ValueError,TypeError):raise ValueError("INVALID_FROZEN_TIP")
        if tip.tzinfo is None or tip.astimezone(BJ).date().isoformat()!=day:
            raise ValueError("FROZEN_TIP_OUTSIDE_BEIJING_DAY")
    if len(set(ids))!=len(ids):raise ValueError("DUPLICATE_FROZEN_NBA_GAME_ID")
    return games

def completion(frozen,day,scores):
    games=frozen_games(frozen,day)
    pending=[]
    completed={}
    for game in games:
        gid=str(game["nba_game_id"])
        q=scores.get(gid) or {}
        hp,ap=q.get("home_points"),q.get("away_points")
        if q.get("completed") is True and isinstance(hp,int) and not isinstance(hp,bool) and hp>=0 and isinstance(ap,int) and not isinstance(ap,bool) and ap>=0:
            completed[gid]=q
        else:
            pending.append({"game_id":game["game_id"],"nba_game_id":gid,
                            "jingcai_number":game.get("jingcai_number"),
                            "tipoff_beijing":game["tipoff_beijing"],
                            "reason":"NOT_OFFICIALLY_FINAL_OR_SCORE_MISSING"})
    return {"complete":len(pending)==0,"total":len(games),
            "final":len(completed),"pending":pending}

def decide(root,now,day_override=None,score_fetch=scores_for):
    now=now.astimezone(BJ)
    if day_override:
        datetime.fromisoformat(day_override).date()
        days=[day_override]
    else:
        # Review yesterday's long/late slate even after local midnight; then
        # consider today's games. Never replace one day's roster with another.
        days=[(now.date()-timedelta(days=n)).isoformat() for n in range(7, -1, -1)]
    pending_days=[]
    for day in days:
        path=frozen_source(root,day)
        if path is None or reviewed(root,day):continue
        frozen=read_json(path)
        games=frozen_games(frozen,day)
        latest=max(datetime.fromisoformat(g["tipoff_beijing"].replace("Z","+00:00")).astimezone(BJ) for g in games)
        # Avoid unnecessary API calls until the final scheduled tip has begun.
        if now < latest:
            pending_days.append({"day":day,"reason":"LAST_GAME_NOT_STARTED",
                                 "latest_tip_beijing":latest.isoformat(),"count":len(games)})
            continue
        scores=score_fetch(day)
        proof=completion(frozen,day,scores)
        if not proof["complete"]:
            pending_days.append({"day":day,"reason":"WAITING_FOR_ALL_OFFICIAL_FINAL_SCORES",**proof,
                                 "latest_tip_beijing":latest.isoformat()})
            continue
        return {"state":"READY_ALL_FINAL","day":day,
                "source":str(path.relative_to(root)),
                "scores":scores,"proof":proof,
                "checked_at_beijing":now.isoformat(),
                "pending_other_days":pending_days}
    return {"state":"WAITING_OR_NO_UNREVIEWED_SCHEDULED_GAMES",
            "pending_days":pending_days,
            "checked_at_beijing":now.isoformat()}

def self_test():
    """21:00 is the only admissible grading record. Results are independent."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        target="2026-11-07"
        day=root/"reports"/"daily"/target
        early=day/"2100"/"nba_five_market_forecast.json"
        later=day/"2300"/"nba_five_market_forecast.json"
        early.parent.mkdir(parents=True)
        later.parent.mkdir(parents=True)
        now=datetime.fromisoformat("2026-11-07T23:30:00+08:00")
        fixture={"target_date":target,"board_capture_utc":"2026-11-06T21:02:00+08:00",
            "games":[{"game_id":"a","nba_game_id":"event1",
                "tipoff_beijing":"2026-11-07T09:00:00+08:00","markets":{}},
                {"game_id":"b","nba_game_id":"event2",
                "tipoff_beijing":"2026-11-07T21:00:00+08:00","markets":{}}]}
        later.write_text(json.dumps({**fixture,"board_capture_utc":"2026-11-06T23:02:00+08:00"}))
        assert frozen_source(root,target) is None,"23:00_MUST_NOT_REPLACE_MISSING_21:00"
        early.write_text(json.dumps(fixture))
        assert frozen_source(root,target)==early,"WRONG_SCORING_SLOT"
        noon=root/"reports"/"noon-cohorts"/target/"1200.json"
        noon.parent.mkdir(parents=True)
        noon.write_text(json.dumps({"official_games":{"event1":{},"event2":{}}}))
        assert frozen_source(root,target)==early
        def partial(day):return {"event1":{"completed":True,"home_points":110,"away_points":105},
                                 "event2":{"completed":False}}
        def all_final(day):return {"event1":{"completed":True,"home_points":110,"away_points":105},
                                   "event2":{"completed":True,"home_points":111,"away_points":112}}
        q=decide(root,now,score_fetch=partial)
        assert q["state"].startswith("WAITING")
        q=decide(root,now,score_fetch=all_final)
        assert q["state"]=="READY_ALL_FINAL" and q["source"]==str(early.relative_to(root))
        assert q["proof"]=={"complete":True,"total":2,"final":2,"pending":[]}
        fixture["board_capture_utc"]="2026-11-07T09:30:00+08:00"
        early.write_text(json.dumps(fixture))
        try:frozen_source(root,target)
        except ValueError as e:assert "POSTTIP" in str(e)
        else:raise AssertionError("POST_KICKOFF_2100_SNAPSHOT_SELECTED")
        fixture["board_capture_utc"]="2026-11-06T21:02:00+08:00"
        fixture["games"][0]["nba_game_id"]="duplicate"
        early.write_text(json.dumps(fixture))
        try:frozen_source(root,target)
        except ValueError as e:assert "COHORT" in str(e)
        else:raise AssertionError("COHORT_MISMATCH_ACCEPTED")
    print("NBA_ONLY_2100_VERIFIED_FROZEN_RESULT_GATE_PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=".")
    ap.add_argument("--day",default="",help="Optional explicit Beijing slate day for manual recovery")
    ap.add_argument("--status-out",default="nba_final_review_readiness.json")
    ap.add_argument("--scores-out",default="nba_final_review_scores.json")
    ap.add_argument("--github-env",default="",help="Append RUN_REPORT and REVIEW_DAY only when fully ready")
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    o=decide(Path(a.root).resolve(),datetime.now(BJ),a.day or None)
    proof=dict(o)
    scores=proof.pop("scores",None)
    Path(a.status_out).write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n")
    if o["state"]=="READY_ALL_FINAL":
        Path(a.scores_out).write_text(json.dumps(scores,ensure_ascii=False,indent=2)+"\n")
    if a.github_env:
        with open(a.github_env,"a",encoding="utf-8") as f:
            f.write("RUN_REPORT="+("true" if o["state"]=="READY_ALL_FINAL" else "false")+"\n")
            if o["state"]=="READY_ALL_FINAL":
                f.write("REVIEW_DAY="+o["day"]+"\n")
                f.write("FROZEN_FORECAST="+o["source"]+"\n")
    print("NBA_FINAL_REVIEW_GATE",o["state"],
          "DAY",o.get("day","NONE"),"DETAILS",json.dumps(o.get("proof",o.get("pending_days",[])),ensure_ascii=False))
if __name__=="__main__":main()
