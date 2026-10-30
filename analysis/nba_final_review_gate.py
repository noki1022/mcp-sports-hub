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

def frozen_source(root,day):
    # 06:30 takes priority: closer to tip, and was already locked pre-tip.
    for slot in ("0630","2130"):
        p=root/"reports"/"daily"/day/slot/"nba_five_market_forecast.json"
        if p.is_file():return p
    return None

def reviewed(root,day):
    p=root/"reports"/"five-market-settled"/day/"2200.json"
    if not p.is_file():return False
    try:return read_json(p).get("state")==ACCEPTED
    except (ValueError,OSError):return False

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
        days=[(now.date()-timedelta(days=1)).isoformat(),now.date().isoformat()]
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
    import tempfile
    now=datetime.fromisoformat("2026-10-31T23:15:00+08:00")
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        target="2026-10-31"
        src=root/"reports"/"daily"/target/"0630"/"nba_five_market_forecast.json"
        src.parent.mkdir(parents=True)
        f={"target_date":target,"games":[
            {"game_id":"a","nba_game_id":"event1","tipoff_beijing":"2026-10-31T09:00:00+08:00"},
            {"game_id":"b","nba_game_id":"event2","tipoff_beijing":"2026-10-31T21:00:00+08:00"}]}
        src.write_text(json.dumps(f))
        def partial(day):return {"event1":{"completed":True,"home_points":110,"away_points":105},
                                  "event2":{"completed":False,"home_points":None,"away_points":None}}
        q=decide(root,now,score_fetch=partial)
        assert q["state"].startswith("WAITING") and q["pending_days"][0]["final"]==1
        def all_final(day):return {"event1":{"completed":True,"home_points":110,"away_points":105},
                                   "event2":{"completed":True,"home_points":111,"away_points":112}}
        q=decide(root,now,score_fetch=all_final)
        assert q["state"]=="READY_ALL_FINAL" and q["proof"]=={"complete":True,"total":2,"final":2,"pending":[]}
        assert decide(root,datetime.fromisoformat("2026-10-31T20:00:00+08:00"),score_fetch=all_final)["state"].startswith("WAITING")
        assert decide(root,datetime.fromisoformat("2026-11-01T00:10:00+08:00"),score_fetch=all_final)["day"]==target
        marker=root/"reports"/"five-market-settled"/target/"2200.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"state":ACCEPTED}))
        assert decide(root,now,score_fetch=all_final)["state"].startswith("WAITING")
        marker.write_text(json.dumps({"state":"DRY_RUN_NOT_SENT"}))
        assert decide(root,now,score_fetch=all_final)["state"]=="READY_ALL_FINAL"
        f["games"][1]["nba_game_id"]="event1"
        src.write_text(json.dumps(f))
        try:decide(root,now,score_fetch=all_final)
        except ValueError as e:assert "DUPLICATE" in str(e)
        else:raise AssertionError("Duplicate game IDs accepted")
    print("NBA_LAST_OFFICIAL_FINAL_GATE_SELF_TEST_PASS")

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
