#!/usr/bin/env python3
"""As-of locked two-market research choices versus verified ESPN final scores.
Runs at 22:00 Beijing for games played TODAY (not tomorrow's 21:30 slate).
"""
import argparse,json,urllib.request,urllib.parse
from pathlib import Path
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
BJ=ZoneInfo("Asia/Shanghai")
def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def scores_for(day):
    url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    games={}
    target=datetime.fromisoformat(day).date()
    for d in (target-timedelta(days=1),target):
        req=urllib.request.Request(url+"?"+urllib.parse.urlencode({"dates":d.strftime("%Y%m%d"),"limit":"100"}),
            headers={"User-Agent":"NBA-Direction-Settlement-Audit/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=18) as res:
            if res.status!=200:raise RuntimeError("SCORES_HTTP_ERROR")
            data=json.loads(res.read(2000000))
        for ev in data.get("events",[]):
            dt=datetime.fromisoformat(ev["date"].replace("Z","+00:00")).astimezone(BJ)
            if dt.date().isoformat()!=day:continue
            comp=ev.get("competitions") or []
            if len(comp)!=1:continue
            sides={r.get("homeAway"):r for r in comp[0].get("competitors",[])}
            if set(sides)!=set(("home","away")):continue
            completed=bool((ev.get("status") or {}).get("type",{}).get("completed"))
            def points(v):
                try:return int(v.get("score")) if completed else None
                except (ValueError,TypeError):return None
            games[str(ev["id"])]={"home_points":points(sides["home"]),"away_points":points(sides["away"]),
                "home_abbr":sides["home"].get("team",{}).get("abbreviation"),
                "away_abbr":sides["away"].get("team",{}).get("abbreviation"),
                "completed":completed,"tip_beijing":dt.isoformat()}
    return games

def settle(forecast,results,day):
    rows=[]
    if forecast.get("target_date")!=day:raise ValueError("WRONG_BEIJING_COHORT")
    captured=datetime.fromisoformat(forecast["captured_at_utc"].replace("Z","+00:00"))
    if captured.tzinfo is None:raise ValueError("NO_CAPTURE_TIMEZONE")
    for g in forecast.get("games",[]):
        source=results.get(str(g.get("nba_game_id")),{})
        scheduled=datetime.fromisoformat(g["beijing_tip"])
        if scheduled.tzinfo is None or captured>=scheduled.astimezone(timezone.utc):
            reason="NOT_PREGAME_OR_UNKNOWN_TIP"
        elif not source.get("completed") or source.get("home_points") is None or source.get("away_points") is None:
            reason="RESULT_UNAVAILABLE_OR_NOT_FINAL"
        else:reason=None
        h=source.get("home_points");a=source.get("away_points")
        settled={}
        for key in ("SPREAD","TOTAL"):
            x=g.get("markets",{}).get(key,{})
            line=x.get("line");side=x.get("direction")
            if reason or line is None or side not in (("HOME","AWAY") if key=="SPREAD" else ("OVER","UNDER")):
                status="UNSETTLED";delta=None
            else:
                # PROVISIONAL source home handicap sign; no claims of settled wagers.
                delta=(h-a+float(line)) if key=="SPREAD" else (h+a-float(line))
                if abs(delta)<1e-8:status="PUSH"
                elif (delta>0 and side in ("HOME","OVER")) or (delta<0 and side in ("AWAY","UNDER")):status="HIT"
                else:status="MISS"
            settled[key]={"direction":side,"line":line,"outcome":status,
                           "settlement_margin":round(delta,2) if delta is not None else None}
        rows.append({"game_id":g["game_id"],"nba_game_id":g["nba_game_id"],
            "home_team":g["home_team"],"away_team":g["away_team"],
            "home_points":h,"away_points":a,"reason":reason,"results":settled})
    sums={kind:{z:sum(r["results"][kind]["outcome"]==z for r in rows) for z in ("HIT","MISS","PUSH","UNSETTLED")} for kind in ("SPREAD","TOTAL")}
    return {"schema_version":"nba-two-market-nightly-settlement-v1","beijing_date":day,
        "forecast_capture_utc":forecast["captured_at_utc"],"forecast_source":"FROZEN_PRETIP_2130_OR_0630",
        "spread_sign_validation":"PROVISIONAL","games":rows,"summary":sums,
        "note":"Research directions as-of archived forecast; spread grading provisional until feed sign independently verified."}

def selftest():
    f={"target_date":"2026-10-30","captured_at_utc":"2026-10-29T13:30:00Z","games":[{"game_id":"7","nba_game_id":"e7",
     "home_team":"主","away_team":"客","beijing_tip":"2026-10-30T07:00:00+08:00",
     "markets":{"SPREAD":{"direction":"HOME","line":-3.5},"TOTAL":{"direction":"UNDER","line":220.5}}}]}
    out=settle(f,{"e7":{"completed":True,"home_points":112,"away_points":105}},"2026-10-30")
    assert out["summary"]["SPREAD"]["HIT"]==1
    assert out["summary"]["TOTAL"]["HIT"]==0 and out["summary"]["TOTAL"]["MISS"]==1
    f["captured_at_utc"]="2026-10-30T10:00:00Z"
    assert settle(f,{"e7":{"completed":True,"home_points":112,"away_points":105}},"2026-10-30")["summary"]["SPREAD"]["UNSETTLED"]==1
    print("NBA_NIGHTLY_ASOF_SETTLEMENT_TEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--forecast");p.add_argument("--day");p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:selftest()
    else:
        if not all((a.forecast,a.day,a.out)):raise SystemExit("MISSING_SETTLEMENT_ARGS")
        r=settle(load(a.forecast),scores_for(a.day),a.day)
        Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
        print("NBA_TWO_MARKET_SETTLEMENT",a.day,r["summary"])
