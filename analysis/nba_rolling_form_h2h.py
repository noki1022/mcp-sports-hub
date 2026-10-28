#!/usr/bin/env python3
"""NBA rolling form, offensive/defensive efficiency and five most recent H2H games.

Data: public season-by-season, team-by-game CSV files. All information is
strictly dated before the *target game date*, and paired home/away entries
must agree before being counted. No invented recent matches or H2H.
"""
from __future__ import annotations
import argparse,csv,io,json,math,re,sys,urllib.request,urllib.error,urllib.robotparser
from collections import defaultdict
from datetime import date,datetime,timezone,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analysis"))
from titan007_ev_analysis import NAMES

BASE="https://boxscorelab.com"
PREFIX=BASE+"/downloads/"
UA="NBAFreeFormResearch/1.0 (bounded public CSV query)"
SEASONS=("2026-27","2025-26","2024-25","2023-24","2022-23")
REQUIRED={"season","team","game_date","opponent","home","result","points","opponent_points",
          "field_goal_attempts","free_throw_attempts","offensive_rebounds","turnovers"}

def checked_download(url,limit=500000):
    with urllib.request.urlopen(urllib.request.Request(BASE+"/robots.txt",headers={"User-Agent":UA}),timeout=12) as r:
        rules=r.read(100001).decode("utf-8","replace")
    if len(rules)>100000:raise RuntimeError("Unbounded robots file")
    rp=urllib.robotparser.RobotFileParser()
    rp.parse(rules.splitlines())
    if not rp.can_fetch(UA,url):raise RuntimeError("Robots policy blocks "+url)
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=15) as r:
        raw=r.read(limit+1);ctype=r.headers.get("Content-Type","")
        if r.status!=200:raise RuntimeError(f"HTTP {r.status}")
    if len(raw)>limit:raise RuntimeError("CSV exceeds size limit")
    text=raw.decode("utf-8-sig","replace")
    if "<html" in text[:300].lower():raise ValueError("HTML masquerading as CSV")
    return text

def parse(text,season,cutoff):
    rd=csv.DictReader(io.StringIO(text))
    if not REQUIRED.issubset(set(rd.fieldnames or [])):
        raise ValueError("CSV schema changed; required fields missing")
    out=[]
    for i,x in enumerate(rd):
        if x["season"]!=season:raise ValueError(f"unexpected season {x['season']}")
        day=date.fromisoformat(x["game_date"])
        if day>=cutoff:continue
        team=x["team"].strip().upper()
        opp=x["opponent"].strip().upper()
        if not re.fullmatch(r"[A-Z]{2,4}",team) or not re.fullmatch(r"[A-Z]{2,4}",opp) or team==opp:continue
        if x["home"].strip().lower() not in ("true","false"):continue
        home=x["home"].strip().lower()=="true"
        def dec(key):return float(x[key])
        fields={k:dec(k) for k in ("points","opponent_points","field_goal_attempts",
                                 "free_throw_attempts","offensive_rebounds","turnovers")}
        if not all(math.isfinite(v) for v in fields.values()):continue
        if any(v<0 for v in fields.values()):continue
        # Possible team-specific estimated possessions, not official NBA poss.
        poss=fields["field_goal_attempts"]-fields["offensive_rebounds"]+fields["turnovers"]+0.44*fields["free_throw_attempts"]
        if not 55<poss<160:continue
        points,against=fields["points"],fields["opponent_points"]
        if abs(points-round(points))>1e-9 or abs(against-round(against))>1e-9:continue
        if x["result"].upper() not in ("W","L"):continue
        if (points>against)!=(x["result"].upper()=="W"):continue
        out.append({"date":day.isoformat(),"season":season,"team":team,"opponent":opp,"home":home,
                    "points":int(points),"against":int(against),"result":x["result"].upper(),
                    "possessions_est":round(poss,5),"fga":fields["field_goal_attempts"],
                    "fta":fields["free_throw_attempts"],"oreb":fields["offensive_rebounds"],"tov":fields["turnovers"]})
    return out

def unique_games(rows):
    by=defaultdict(list)
    for r in rows:
        # same two clubs and date: unambiguous pair unless duplicate game listed
        key=(r["date"],*sorted((r["team"],r["opponent"])))
        by[key].append(r)
    good=[];skipped=[]
    for key,entries in by.items():
        home=[r for r in entries if r["home"]]
        away=[r for r in entries if not r["home"]]
        if len(home)!=1 or len(away)!=1:
            skipped.append({"key":key,"reason":"missing_or_duplicate_team_side","rows":len(entries)})
            continue
        h,a=home[0],away[0]
        if not (h["team"]==a["opponent"] and a["team"]==h["opponent"] and
                h["points"]==a["against"] and a["points"]==h["against"] and
                h["result"]!=a["result"]):
            skipped.append({"key":key,"reason":"reciprocal_team_data_inconsistent"})
            continue
        good.append({"date":h["date"],"season":h["season"],"home":h["team"],
                     "away":a["team"],"home_points":h["points"],"away_points":a["points"],
                     "total":h["points"]+a["points"],"margin_home":h["points"]-a["points"],
                     "home_possessions_est":h["possessions_est"],"away_possessions_est":a["possessions_est"],
                     "pace_est":round((h["possessions_est"]+a["possessions_est"])/2,3)})
    return good,skipped

def stats_team(team,rows,asof,limit=5):
    data=sorted((x for x in rows if x["team"]==team and x["date"]<asof),key=lambda x:x["date"],reverse=True)[:limit]
    if not data:return {"sample_games":0,"last_five":[],"reason":"NO_VERIFIED_RESULTS_BEFORE_TIP"}
    n=len(data)
    asofgames=[x for x in rows if x["team"]==team and x["season"]==f"{int(asof[:4]) if int(asof[5:7])>=7 else int(asof[:4])-1}-{(int(asof[:4])+1 if int(asof[5:7])>=7 else int(asof[:4]))%100:02d}"]
    season_games=len(asofgames)
    avg=lambda field:sum(x[field] for x in data)/n
    total_poss=sum(x["possessions_est"] for x in data)
    off=100*sum(x["points"] for x in data)/total_poss
    # Team points conceded divided by estimated own possessions, proxy not official def rating
    defensive=100*sum(x["against"] for x in data)/total_poss
    return {"sample_games":n,"current_season_completed_games":season_games,
            "wins_last_five":sum(x["result"]=="W" for x in data),
            "points_per_game":round(avg("points"),2),
            "opponent_points_per_game":round(avg("against"),2),
            "average_point_difference":round(avg("points")-avg("against"),2),
            "possessions_per_game_est":round(avg("possessions_est"),2),
            "off_rating_100pos_est":round(off,2),"def_rating_100pos_est":round(defensive,2),
            "net_rating_100pos_est":round(off-defensive,2),
            "last_game_date":data[0]["date"],
            "last_five":[{"date":x["date"],"opponent":x["opponent"],"site":"HOME" if x["home"] else "AWAY",
                          "result":x["result"],"points":x["points"],"opp_points":x["against"],
                          "season":x["season"]} for x in data]}

def head_to_head(home,away,games,cutoff):
    data=sorted((g for g in games if g["date"]<cutoff.isoformat() and set((g["home"],g["away"]))==set((home,away))),
                key=lambda g:g["date"],reverse=True)
    five=data[:5]
    return {"verified_h2h_games":len(five),"h2h_available_total":len(data),
            "home_team_past_wins":sum((g["home_points"]>g["away_points"]) if g["home"]==home
                                      else (g["away_points"]>g["home_points"]) for g in five),
            "recent_five":[{
                "date":g["date"],"season":g["season"],"home":g["home"],"away":g["away"],
                "score":f"{g['home_points']}-{g['away_points']}",
                "total":g["total"],"margin_from_requested_home":g["home_points"]-g["away_points"] if g["home"]==home else g["away_points"]-g["home_points"]
            } for g in five],
            "history_is_complete":len(five)==5,
            "note":"Historical results are context only; rosters and coaching may have changed."}

def build(target,joined):
    cutoff=date.fromisoformat(target)
    raw=[];source_rows={};allerrors=[]
    for season in SEASONS:
        url=f"{PREFIX}{season}-team-game-results.csv"
        text=checked_download(url)
        seasonrows=parse(text,season,cutoff)
        raw+=seasonrows
        source_rows[season]={"url":url,"eligible_rows":len(seasonrows)}
    verified,errors=unique_games(raw)
    if len(verified)<15:raise RuntimeError("Incomplete public history: fewer than 15 verified games")
    # Only verified reciprocal matches are valid for both recent form and H2H.
    verified_keys={(g["date"],g["home"],g["away"]) for g in verified}
    good_rows=[x for x in raw if (x["date"],x["team"],x["opponent"]) in verified_keys or (x["date"],x["opponent"],x["team"]) in verified_keys]
    games=[]
    for m in joined.get("nba_cba_games",[]):
        if m.get("league")!="NBA":continue
        h=NAMES.get(m.get("home_team"));a=NAMES.get(m.get("away_team"))
        if not h or not a:
            games.append({"game_id":m["game_id"],"status":"UNMAPPED_TEAM","home":m.get("home_team"),"away":m.get("away_team")})
            continue
        hcode,acode=h[0],a[0]
        hf=stats_team(hcode,good_rows,target)
        af=stats_team(acode,good_rows,target)
        h2h=head_to_head(hcode,acode,verified,cutoff)
        latest=max((x for x in [hf.get("last_game_date"),af.get("last_game_date")] if x),default=None)
        stale=not latest or (cutoff-date.fromisoformat(latest)).days>10
        games.append({"game_id":m["game_id"],"league":"NBA","home":h[1],"away":a[1],"home_code":hcode,"away_code":acode,
            "home_recent":hf,"away_recent":af,"head_to_head":h2h,
            "status":"HISTORICAL_CONTEXT_STALE" if stale else "FORM_AND_H2H_AVAILABLE",
            "h2h_note":"<5 H2H games means no extra games were invented."})
    return {"created_at_utc":datetime.now(timezone.utc).isoformat(),"target_date":target,
            "as_of_cutoff":"strictly before "+target+" (site display date; date timezone verified separately)",
            "sources":source_rows,"verified_distinct_games":len(verified),
            "unpaired_or_invalid_games":len(errors),"quality_examples":errors[:5],
            "nba_games":games,
            "notes":["Team efficiencies are estimates using FGA-OREB+TO+0.44*FTA; no minutes or overtime adjustment.",
                     "Latest five are across available regular-season dataset, spanning season boundaries early in season.",
                     "Recent form and H2H are descriptive. Independent odds EV requires calibrated modeling and confirmed injuries.",
                     "CSV mirrors publicly available season data; provider update frequency not guaranteed."]}

def test():
    sample="season,team,game_date,matchup,opponent,home,result,points,opponent_points,field_goal_attempts,free_throw_attempts,offensive_rebounds,turnovers\n"
    one=sample+"2026-27,ATL,2026-10-26,ATL vs. MIA,MIA,True,W,110,100,80,20,10,12\n2026-27,MIA,2026-10-26,MIA @ ATL,ATL,False,L,100,110,80,20,9,13\n2026-27,MIA,2026-10-29,MIA vs. ATL,ATL,True,W,115,101,85,15,12,11\n"
    rows=parse(one,"2026-27",date(2026,10,29))
    g,sk=unique_games(rows)
    assert len(g)==1 and not sk
    assert stats_team("ATL",rows,"2026-10-29")["wins_last_five"]==1
    h=head_to_head("ATL","MIA",g,date(2026,10,29))
    assert h["verified_h2h_games"]==1 and h["home_team_past_wins"]==1
    assert h["recent_five"][0]["margin_from_requested_home"]==10
    assert parse(one,"2026-27",date(2026,10,26))==[]
    print("NBA_FORM_H2H_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--joined",default="titan007_joined_nba_cba.json")
    p.add_argument("--date",default="2026-10-29")
    p.add_argument("--out",default="nba_recent_form_h2h.json")
    a=p.parse_args()
    if a.self_test:test();raise SystemExit()
    board=json.loads(Path(a.joined).read_text(encoding="utf-8"))
    obj=build(a.date,board)
    Path(a.out).write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"date":obj["target_date"],"verified_games":obj["verified_distinct_games"],"nba_matches":len(obj["nba_games"]),
        "sources":obj["sources"],"sample":[{"id":x["game_id"],"home":x.get("home"),"away":x.get("away"),
        "home_last_n":x.get("home_recent",{}).get("sample_games"),"away_last_n":x.get("away_recent",{}).get("sample_games"),
        "h2h_last_n":x.get("head_to_head",{}).get("verified_h2h_games"),"status":x.get("status")} for x in obj["nba_games"][:6]]},indent=2,ensure_ascii=False))
