#!/usr/bin/env python3
"""Fail-closed official injury context; never turns injury status into untested points."""
from __future__ import annotations
import json,sys
from datetime import datetime,timezone
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
            return {"report_state":v.get("report_state","UNKNOWN"),
                    "players":[p for p in v.get("players",[]) if p.get("status") in ("Out","Doubtful","Questionable","Probable","Available")],
                    "status_counts":v.get("status_counts",{})}
        h=side(home,home_data[1]);a=side(away,away_data[1])
        unresolved=any(x["report_state"]!="PUBLISHED" for x in (h,a))
        affected=any(p["status"] in ("Out","Doubtful","Questionable") for x in (h,a) for p in x["players"])
        rows.append({"game_id":str(g.get("game_id")),"matchup_key":key,
          "source_report_et_date":valid,"source_captured_at_utc":stamp.isoformat() if stamp else None,
          "home":h,"away":a,
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
