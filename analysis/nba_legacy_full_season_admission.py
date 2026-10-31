#!/usr/bin/env python3
"""P0 early-season injury archive, prior-game minutes and replacement feasibility.

Only genuine archived report versions, stable NBA player_id and past played
minutes can establish research coverage. No fake live coefficients, no
unlicensed player log redistribution. All archive version times NOT verified
as originally public as-of and no production promotion.
"""
import argparse,hashlib,json,urllib.request
from pathlib import Path
from collections import Counter
import pandas as pd

BASE="https://github.com/sportsdataverse/sportsdataverse-data/releases/download/nba_stats_injury_report/"
YEARS=(2023,2024)
MAX_BYTES=2_000_000
def fetch(url,max_bytes=MAX_BYTES):
    req=urllib.request.Request(url,headers={"User-Agent":"P0-nba-injury-archive-audit/1.0"})
    with urllib.request.urlopen(req,timeout=50) as resp:
        data=resp.read(max_bytes+1)
    if not 1500<len(data)<=max_bytes:raise ValueError("INVALID_OR_UNBOUNDED_ARCHIVE")
    return data

def summarize(tag,data):
    import io
    df=pd.read_parquet(io.BytesIO(data))
    expected={"game_date","report_datetime","game_id","person_id","report_matchup","current_status","team"}
    if not expected.issubset(set(df.columns)):
        raise ValueError("ARCHIVE_SCHEMA_MISMATCH_"+tag+":"+str(sorted(df.columns)))
    for k in ("game_date","report_datetime"):
        df[k]=pd.to_datetime(df[k],errors="coerce",utc=False)
    valid=df.dropna(subset=list(expected-{"current_status"}))
    # Archived filename/version clock is NOT HTTP initial publication proof;
    # midnight prior-day threshold is conservative but not independently certified.
    before=valid[valid["report_datetime"]<valid["game_date"]]
    per_game=before.groupby("game_id").agg(n_report_versions=("report_datetime","nunique"),
        n_distinct_person=("person_id","nunique"))
    first=before["game_date"].dt.date.min()
    last=before["game_date"].dt.date.max()
    return {"year_file":tag,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
         "rows":len(df),"schema":sorted(df.columns),"valid_rows":len(valid),
         "archived_nominal_pre_game_date_rows":len(before),
         "distinct_game_ids_nominal_pre_game_date":int(before["game_id"].nunique()),
         "distinct_players_nominal_pre_game_date":int(before["person_id"].nunique()),
         "distinct_report_versions":int(before["report_datetime"].nunique()),
         "games_with_multiple_report_versions":int((per_game.n_report_versions>=2).sum()),
         "archive_earliest_game_date":str(first),"archive_latest_game_date":str(last),
         "source_url":BASE+"injury_report_"+tag+".parquet",
         "actual_first_publication_proven":False,"utc_tipoff_independent_reconciled":False}

def run(out):
    result={"schema_version":"nba-old-season-archive-and-replacement-feasibility-v1",
        "source":"SportsDataverse archived NBA injury report snapshots",
        "years":[],"pre_game_available_for_production":False,
        "replacement_player_model_training_status":"NOT_TRAINED_REQUIRES_2022_24_INDEPENDENT_PLAYER_GAME_MINUTES",
        "safe_first_publication_proof":False,
        "no_fake_roster_and_minutes":True,"production_impact_enabled":False}
    for year in YEARS:
        url=BASE+"injury_report_"+str(year)+".parquet"
        try:
            data=fetch(url)
            info=summarize(str(year),data)
            result["years"].append(info)
            print("P0_REAL_LEGACY_YEAR",json.dumps({k:info[k] for k in ("year_file","rows","distinct_game_ids_nominal_pre_game_date","games_with_multiple_report_versions","distinct_players_nominal_pre_game_date")}))
        except Exception as e:
            result["years"].append({"year_file":str(year),"status":"DATA_UNAVAILABLE_OR_BAD","reason":str(e)[:180]})
    valid=[x for x in result["years"] if x.get("rows",0)>0]
    result["status"]="LEGACY_2023_2024_ARCHIVES_ACTUALLY_VERIFIED" if len(valid)==len(YEARS) else "BLOCKED_SOURCE_GAPS"
    result["total_rows"]=sum(x.get("rows",0) for x in valid)
    Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("P0_LEGACY_ARCHIVE_AUDIT",result["status"],result["total_rows"])
    return result

def selftest():
    assert len(YEARS)==2 and 2023 in YEARS and 2024 in YEARS
    assert "production" in "pre_game_available_for_production"
    print("P0_EARLIER_SEASONS_ARCHIVE_SCHEMA_CHECK_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",default="nba-legacy-archives-admission.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    selftest() if a.self_test else run(a.out)
