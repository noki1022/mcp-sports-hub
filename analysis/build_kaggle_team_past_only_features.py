#!/usr/bin/env python3
"""Independent-score-joined, strictly past-only NBA TEAM features training candidate.

Never includes an individual game's own boxscore in its prediction features.
Requires reciprocal teams, source-score agreement and two external score records
(538/Neil + LineSheet); ZIP source content is never stored in repository.
Research-only candidate: source independence/underlying commercial rights remain
to be reviewed; no changes to existing live model or 2025-26 holdout.
"""
from __future__ import annotations
import csv,io,json,sys,math,hashlib
from pathlib import Path
from collections import defaultdict,Counter
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parent))
import kaggle_team_boxscore_strict_audit as box
from nba_538_training_source import SOURCE as SRC538,verify as verify538
from nba_2015_22_training_expansion import UPSTREAM,crossverify as verify_neil
from nba_archive_crosscheck import LINE_SHEET,bounded_fetch
import kaggle_nba_foundation_batches as foundation
import probe_kaggle_stats_remote_zip as remote
remote.MAX_TRANSFER=30_000_000

ABBR={"NJN":"BKN","BRK":"BKN","NOH":"NOP","NOK":"NOP","CHO":"CHA","PHO":"PHX","CHH":"CHA"}
KEEP=("date","home","away","home_win","home_margin","total_points",
      "home_off_last5","away_off_last5","home_def_last5","away_def_last5",
      "home_pace_last5","away_pace_last5","home_win_last5","away_win_last5",
      "home_rest_days","away_rest_days","max_feature_source_date")
def canon(x):
    x=str(x).strip().upper()
    return ABBR.get(x,x)
def refs():
    second=bounded_fetch(LINE_SHEET,limit=9_000_000)
    early,_=verify538(bounded_fetch(SRC538,limit=25_000_000),second)
    later,_=verify_neil(bounded_fetch(UPSTREAM,limit=22_000_000),second)
    allgames=early+later
    result={(r["date"],r["home"],r["away"]):(r["home_points"],r["away_points"]) for r in allgames}
    if len(result)!=len(allgames) or len(result)<18500:raise ValueError("INDEPENDENT_GAME_REFERENCE_REGRESSION")
    return result
def stream_strict_games(size,member,index,external):
    iterator=box.csv_records(size,member)
    fields=next(iterator)
    if not box.NEEDED.issubset(fields) or "team_abbreviation" not in fields:
        raise ValueError("TEAM_BOXSCORE_SOURCE_SCHEMA_CHANGED")
    accepted=defaultdict(list);rejects=Counter();source_rows=0
    for vals in iterator:
        source_rows+=1
        if len(vals)!=len(fields):
            rejects["BAD_COLUMN_COUNT"]+=1;continue
        r=dict(zip(fields,vals))
        gid=r.get("game_id","")
        g=index.get(gid)
        if not g:rejects["MISSING_INDEX"]+=1;continue
        day=r["game_date"].split("T")[0]
        if day!=g["game_date"].split("T")[0]:rejects["INDEX_DATE_CONFLICT"]+=1;continue
        if day>="2022-08-01" or day<"2007-08-01":
            rejects["OUTSIDE_PRESERVED_TRAIN_PERIOD"]+=1;continue
        home=canon(g["home"])
        away=canon(g["away"])
        if home==away or home not in boxscore_teams or away not in boxscore_teams:
            rejects["UNMAPPED_GAME_TEAMS"]+=1;continue
        key=(day,home,away)
        expected=external.get(key)
        if expected is None:
            rejects["NO_TWO_SOURCE_SCORE_MATCH"]+=1;continue
        try:
            h=box.flag(r["is_home"])
            code=canon(r["team_abbreviation"])
            if code!=(home if h else away):raise ValueError("TEAM_ABBREVIATION_MISMATCH")
            pts=box.number(r["pts"])
            if pts!=int(pts) or int(pts)!=expected[0 if h else 1]:
                raise ValueError("EXTERNAL_SCORE_DISAGREEMENT")
            if r["team_id"].strip()!=g["team_id_home" if h else "team_id_away"].strip():
                raise ValueError("TEAM_ID_DISAGREEMENT")
            off=box.number(r["off_rating"])
            defense=box.number(r["def_rating"])
            pace=box.number(r["pace"])
            poss=box.number(r["poss"])
            fga=box.number(r["fga"])
            orebs=box.number(r["oreb"])
            fta=box.number(r["fta"])
            tov=box.number(r["tov"])
            if not(50<=off<=180 and 50<=defense<=180 and 60<=pace<=160
                   and 50<=poss<=160 and 0<=orebs<=fga<=160
                   and 0<=fta<=100 and 0<=tov<=60):raise ValueError("EFFICIENCY_RANGE")
            accepted[key].append({"date":day,"team":code,"home":h,
                "points":int(pts),"off":off,"def":defense,"pace":pace})
        except (ValueError,TypeError,KeyError) as ex:
            reasons=str(ex)
            rejects[reasons if reasons.isupper() and len(reasons)<90 else "BAD_BOX_ROW"]+=1
    games=[]
    for key,pair in accepted.items():
        if len(pair)!=2 or {x["home"] for x in pair}!={True,False}:
            rejects["DUPLICATE_OR_MISSING_SIDE"]+=1;continue
        if set(x["team"] for x in pair)!={key[1],key[2]}:
            rejects["PAIR_TEAM_CONFLICT"]+=1;continue
        home=next(x for x in pair if x["home"])
        away=next(x for x in pair if not x["home"])
        games.append({"key":key,"date":key[0],"home":key[1],"away":key[2],
                      "home_pts":home["points"],"away_pts":away["points"],
                      "h":home,"a":away})
    games.sort(key=lambda g:(g["date"],g["home"],g["away"]))
    return games,rejects,source_rows

boxscore_teams=set("ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS SEA".split())

def construct(games):
    histories=defaultdict(list)
    eligible=[]
    by_date=defaultdict(list)
    for g in games:by_date[g["date"]].append(g)
    for day in sorted(by_date):
        new=[]
        for g in by_date[day]:
            h,a=histories[g["home"]][-5:],histories[g["away"]][-5:]
            if len(h)<5 or len(a)<5:continue
            if not all(x["date"]<day for x in h+a):
                raise RuntimeError("FUTURE_OR_SAME_DAY_FEATURE_LEAK")
            def mean(hist,col):return round(sum(x[col] for x in hist)/5,5)
            def rested(hist):return min(10,max(0,(date.fromisoformat(day)-date.fromisoformat(hist[-1]["date"])).days-1))
            maxday=max(x["date"] for x in h+a)
            row={"date":day,"home":g["home"],"away":g["away"],
              "home_win":int(g["home_pts"]>g["away_pts"]),
              "home_margin":g["home_pts"]-g["away_pts"],
              "total_points":g["home_pts"]+g["away_pts"],
              "home_off_last5":mean(h,"off"),"away_off_last5":mean(a,"off"),
              "home_def_last5":mean(h,"def"),"away_def_last5":mean(a,"def"),
              "home_pace_last5":mean(h,"pace"),"away_pace_last5":mean(a,"pace"),
              "home_win_last5":mean(h,"win"),"away_win_last5":mean(a,"win"),
              "home_rest_days":rested(h),"away_rest_days":rested(a),
              "max_feature_source_date":maxday}
            if set(row)!=set(KEEP) or not maxday<day:raise RuntimeError("FEATURE_WHITELIST_OR_ASOF_VIOLATION")
            eligible.append(row)
        # Same-day games are ONLY added after all game features were computed.
        for g in by_date[day]:
            for side in ("h","a"):
                x=dict(g[side])
                x["win"]=int(x["points"]>(g["away_pts"] if side=="h" else g["home_pts"]))
                histories[x["team"]].append(x)
    return eligible

def test():
    assert canon("NJN")=="BKN"
    assert canon("PHO")=="PHX"
    hist=[]
    for i in range(6):
        day=f"2020-01-{i+1:02d}"
        hist.append({"date":day,"home":"BOS","away":"NYK","home_pts":110,"away_pts":100,
           "h":{"date":day,"team":"BOS","home":True,"points":110,"off":112,"def":100,"pace":99},
           "a":{"date":day,"team":"NYK","home":False,"points":100,"off":100,"def":112,"pace":99}})
    rows=construct(hist)
    assert len(rows)==1 and rows[0]["date"]=="2020-01-06" and rows[0]["max_feature_source_date"]=="2020-01-05"
    print("NBA_STRICT_TEAM_TRAINING_FEATURE_SELF_TEST_PASS")

def main():
    if "--self-test" in sys.argv:return test()
    approved=refs()
    total,entries=foundation.archive_entries()
    index=box.parse_index(foundation.fetch_member(total,entries["csv/games_index.csv"]))
    games,rejected,source_rows=stream_strict_games(total,entries[box.FILE],index,approved)
    if len(games)<15000:raise RuntimeError("NOT_ENOUGH_THIRD_SOURCE_VERIFIED_GAMES")
    rows=construct(games)
    if len(rows)<14000:raise RuntimeError("INSUFFICIENT_PAST_ONLY_FEATURES")
    out=Path("/tmp/nba-historical-team-training")
    out.mkdir(exist_ok=True)
    file=out/"nba_team_last5_train_2007_2022.csv"
    with file.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=KEEP);writer.writeheader();writer.writerows(rows)
    digest=hashlib.sha256(file.read_bytes()).hexdigest()
    manifest={
      "status":"ISOLATED_RESEARCH_TRAINING_CANDIDATE_NOT_PRODUCTION",
      "game_score_external_crossverified":len(games),"past_only_feature_rows":len(rows),
      "original_boxscore_rows_scanned":source_rows,
      "source_rejects":dict(rejected),"file_sha256":digest,
      "time_cutoff_train_before":"2022-08-01",
      "asof_rule":"all previous features have source_date < game date; same-date batch",
      "columns":list(KEEP),
      "source_independence_unproven":True,
      "upstream_reuse_rights_unverified":True,
      "production_modified":False,"holdout_2025_26_unmodified":True
    }
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False))
    print("NBA_TEAM_FEATURE_TRAINING_CANDIDATE "+json.dumps(manifest,sort_keys=True,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
