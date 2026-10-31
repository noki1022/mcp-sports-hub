#!/usr/bin/env python3
"""Fail-closed official injury context; never turns injury status into untested points."""
from __future__ import annotations
import json,sys
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
BJ=ZoneInfo("Asia/Shanghai")
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from titan007_ev_analysis import NAMES

def attach(joined,official):
    matchups=(official or {}).get("matchups") or {}
    valid=(official or {}).get("report_et_date")
    try:
        stamp=datetime.fromisoformat(str(official["captured_at_utc"]).replace("Z","+00:00"))
        if stamp.tzinfo is None:raise ValueError()
    except (TypeError,KeyError,ValueError):
        stamp=None
    ambiguous={(str(x.get("matchup")),str(x.get("team"))) for x in (official or {}).get("ambiguous_player_rows",[]) if isinstance(x,dict)}
    rows=[]
    for g in joined.get("nba_cba_games",[]):
        home_data=NAMES.get(g.get("home_team"),(None,None))
        home=home_data[0]
        away_data=NAMES.get(g.get("away_team"),(None,None))
        away=away_data[0]
        key=f"{away}@{home}" if home and away else None
        teams=matchups.get(key,{})
        def side(code, fallback):
            vals=[v for k,v in teams.items() if str(k).lower()==str(fallback).lower()]
            if not vals:
                return {"report_state":"NOT_LISTED","players":[],"status_counts":{}}
            v=vals[0]
            if (key,fallback) in ambiguous:
                return {"report_state":"AMBIGUOUS_PLAYER_PARSE","players":[],"status_counts":{}}
            return {"report_state":v.get("report_state","UNKNOWN"),
                    "players":[p for p in v.get("players",[]) if p.get("status") in ("Out","Doubtful","Questionable","Probable","Available")],
                    "status_counts":v.get("status_counts",{})}
        h=side(home,home_data[1]);a=side(away,away_data[1])
        tip=None
        try:
            tip=datetime.fromisoformat(str(g.get("start_time_beijing") or g.get("tipoff_utc")).replace("Z","+00:00"))
            if tip.tzinfo is None:tip=None
        except (ValueError,TypeError):tip=None
        et_day=(tip.astimezone(ZoneInfo("America/New_York")).date().isoformat() if tip else None)
        source_date_ok=(valid==et_day)
        timestamp_ok=bool(tip and stamp and stamp<tip and stamp<=datetime.now(timezone.utc))
        unresolved=any(x["report_state"]!="PUBLISHED" for x in (h,a)) or not source_date_ok or not timestamp_ok
        affected=any(p["status"] in ("Out","Doubtful","Questionable") for x in (h,a) for p in x["players"])
        rows.append({"game_id":str(g.get("game_id")),"matchup_key":key,
          "source_report_et_date":valid,"source_captured_at_utc":stamp.isoformat() if stamp else None,
          "home":h,"away":a,"source_date_matches_tip":source_date_ok,
          "capture_before_tip_verified":timestamp_ok,"parsed_player_ambiguity":bool((key,home_data[1]) in ambiguous or (key,away_data[1]) in ambiguous),
          "quality":"UNKNOWN_OR_UNSUBMITTED" if unresolved else "PUBLISHED_AFFECTED" if affected else "PUBLISHED_LISTED",
          "player_adjustment":"DISABLED_NOT_BACKTESTED",
          "independent_model_probability_adjusted":False})
    return {"target_date":joined.get("requested_display_date"),"source":"official NBA injury PDF" if official else "NOT_PROVIDED",
            "games":rows,"player_level_impact_model":"DISABLED_NOT_BACKTESTED"}

def self_test():
    b={"requested_display_date":"2026-10-31","nba_cba_games":[{"game_id":"1","home_team":"华盛顿奇才","away_team":"夏洛特黄蜂"}]}
    r=attach(b,None)
    assert r["games"][0]["quality"]=="UNKNOWN_OR_UNSUBMITTED"
    assert r["games"][0]["independent_model_probability_adjusted"] is False
    print("NBA_INJURY_CONTEXT_FAIL_CLOSED_PASS")

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--joined");p.add_argument("--injuries");p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    if not a.joined or not a.out:raise SystemExit("--joined and --out required")
    j=json.loads(Path(a.joined).read_text())
    inj=json.loads(Path(a.injuries).read_text()) if a.injuries and Path(a.injuries).exists() else None
    o=attach(j,inj)
    Path(a.out).write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n")
    print("NBA_INJURY_CONTEXT",len(o["games"]),o["source"])
if __name__=="__main__":main()
