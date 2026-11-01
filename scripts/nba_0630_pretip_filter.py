#!/usr/bin/env python3
"""Filter verified Beijing-day NBA fixtures to genuinely pre-tip games."""
from __future__ import annotations
import argparse,json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")
def select(board,now,min_lead=5):
    current=now.astimezone(BJ)
    selected=[];excluded=[]
    for g in board.get("nba_cba_games",[]):
        if g.get("league")!="NBA":
            excluded.append({"game_id":g.get("game_id"),"reason":"NOT_NBA"});continue
        try:
            tip=datetime.fromisoformat(g["start_time_beijing"]).astimezone(BJ)
            if tip.date()!=current.date():raise ValueError("DATE_NOT_TODAY")
            minutes=(tip-current).total_seconds()/60
            if minutes<min_lead:
                excluded.append({"game_id":g.get("game_id"),"reason":"ALREADY_STARTED_OR_TOO_CLOSE"});continue
        except (TypeError,KeyError,ValueError) as exc:
            excluded.append({"game_id":g.get("game_id"),"reason":str(exc)[:90]});continue
        selected.append(g)
    out={**board,"nba_cba_games":selected,"nba_cba_joined_for_date":len(selected),
         "morning_pre_tip_filter":{"checked_at_beijing":current.isoformat(),
                                  "minimum_lead_minutes":min_lead,
                                  "excluded":excluded,"included":len(selected)}}
    return out

def self_test():
    base={"requested_display_date":"2026-10-31","nba_cba_games":[
      {"game_id":"1","league":"NBA","start_time_beijing":"2026-10-31T07:00:00+08:00"},
      {"game_id":"2","league":"NBA","start_time_beijing":"2026-10-31T06:25:00+08:00"},
      {"game_id":"3","league":"NBA","start_time_beijing":"2026-11-01T07:00:00+08:00"}]}
    o=select(base,datetime.fromisoformat("2026-10-31T06:30:00+08:00"))
    assert [x["game_id"] for x in o["nba_cba_games"]]==["1"]
    assert len(o["morning_pre_tip_filter"]["excluded"])==2
    print("NBA_0630_PRETIP_GAME_FILTER_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--joined")
    p.add_argument("--out");p.add_argument("--min-lead",type=float,default=5.0);p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.joined or not a.out:raise SystemExit("JOINED_AND_OUT_REQUIRED")
        o=select(json.loads(Path(a.joined).read_text(encoding="utf-8")),datetime.now(BJ),min_lead=a.min_lead)
        if not o["nba_cba_games"]:raise SystemExit("NO_PRETIP_NBA_GAMES_WITH_REQUIRED_LEAD_NO_PUSH")
        Path(a.out).write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_0630_PRETIP_VERIFIED",len(o["nba_cba_games"]))
