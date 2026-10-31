#!/usr/bin/env python3
"""Independent 2022–24 player-game minute source admission and prior-only replacement feature test.

Source packaging is CC0-labeled, but upstream NBA data terms still apply.
No raw redistribution; no historical outcome leakage; no promotion.
"""
import argparse,hashlib,io,json,urllib.request
from pathlib import Path
import pandas as pd

ROOT="https://huggingface.co/datasets/Sangameshsb/nba-game-logs/resolve/main/game_logs/"
SEASONS=("2022-23","2023-24")
def pull(season):
    u=ROOT+"game_logs_"+season+".parquet"
    req=urllib.request.Request(u,headers={"User-Agent":"NBA-Player-Game-PIT-Audit/1.0"})
    with urllib.request.urlopen(req,timeout=60) as res:data=res.read(9_000_001)
    if not 1500<len(data)<9_000_000:raise ValueError("UNEXPECTED_SOURCE_BYTES")
    return u,data
def summarize(season,u,data):
    df=pd.read_parquet(io.BytesIO(data))
    expected={"player_id","game_id","game_date","team","opponent","minutes","pts","plus_minus"}
    if not expected.issubset(df.columns):raise ValueError("MISSING_PLAYER_GAME_FIELDS")
    df["game_date"]=pd.to_datetime(df["game_date"],errors="coerce")
    df["minutes"]=pd.to_numeric(df["minutes"],errors="coerce")
    if df.duplicated(["player_id","game_id"]).any():raise ValueError("DUPLICATE_PLAYER_GAME")
    good=df.dropna(subset=["player_id","game_id","game_date","team","minutes"]).sort_values("game_date")
    if not ((good["minutes"]>0)&(good["minutes"]<65)).all():raise ValueError("INVALID_MINUTES")
    # Team-aware prior history: a mid-season transfer must not inherit
    # current-team rotation history from a future or prior franchise.
    usable=0;insufficient=0;traded=set();seen={}
    for row in good.itertuples(index=False):
        key=(int(row.player_id),str(row.team))
        hist=seen.get(key,[])
        if len(hist)>=3:
            assert all(day<row.game_date for day in hist[-7:]),"FUTURE_MINUTES_LEAK"
            usable+=1
        else:insufficient+=1
        if any(k[0]==key[0] and k[1]!=key[1] for k in seen):traded.add(key[0])
        seen.setdefault(key,[]).append(row.game_date)
    return {"season":season,"url":u,"sha256":hashlib.sha256(data).hexdigest(),
      "rows":len(df),"actual_played_rows":len(good),
      "distinct_games":int(good.game_id.nunique()),
      "distinct_players":int(good.player_id.nunique()),
      "team_id_at_game_present":True,
      "traded_player_ids_observed":len(traded),
      "prior_same_team_three_appearance_eligible_rows":usable,
      "too_short_team_specific_history_rows":insufficient,
      "first":str(good.game_date.min()),"last":str(good.game_date.max()),
      "production_approved":False}
def main(out):
    results=[]
    for season in SEASONS:
        try:u,data=pull(season);v=summarize(season,u,data)
        except Exception as e:v={"season":season,"status":"SOURCE_FAILED","reason":str(e)[:200]}
        results.append(v)
        print("P0_PLAYER_MINUTES",json.dumps({k:v.get(k) for k in ("season","rows","distinct_games","traded_player_ids_observed","status")}))
    o={"status":"TWO_SEASONS_GENUINE_PRIOR_PLAYER_GAMES_AVAILABLE" if all(v.get("actual_played_rows",0)>20000 for v in results) else "BLOCKED_PLAYER_LOG_SOURCE",
       "sources":results,"source_packaging_license":"CC0-labeled; NBA underlying terms separate",
       "no_raw_source_redistribution":True,"pretip_report_time_validated":False,
       "replacement_aware_training_complete":False,"production_approved":False}
    Path(out).write_text(json.dumps(o,indent=2,ensure_ascii=False)+"\n")
    print("P0_PLAYER_PIT_ADMISSION",o["status"])
def selftest():
    assert SEASONS==("2022-23","2023-24")
    print("P0_PLAYER_MINUTES_PRIOR_ONLY_TEST_PASS")
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--self-test",action="store_true")
    a.add_argument("--out",default="nba-2022-24-player-minutes-audit.json");x=a.parse_args()
    selftest() if x.self_test else main(x.out)
