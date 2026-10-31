#!/usr/bin/env python3
"""Player log and official injury archive P0 admission audit, NEVER self-certifies impact.

No future-statistic feature may enter training. Check external raw sources in
ephemeral CI, store only provenance, no raw redistribution.
"""
import argparse,csv,hashlib,json,re,sys
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request,urlopen

PLAYER="https://raw.githubusercontent.com/xtheredshirtx/fanduel-player-data/main/NBA/csv/NBA_players_game_log_2024-25_as_of_2026-10-31.csv"
INJURY="https://raw.githubusercontent.com/Professor-Pete/2024-2025-injury_analysis/6fcf87e34c6c0bd791a1f4c0f100c0a6500ac949/data/season_rows.csv"
OUTCOME="https://raw.githubusercontent.com/Professor-Pete/2024-2025-injury_analysis/6fcf87e34c6c0bd791a1f4c0f100c0a6500ac949/data/crossref.csv"
def fetch(url,limit):
    req=Request(url,headers={"User-Agent":"NBA-Player-Impact-Audit/1.0"})
    with urlopen(req,timeout=40) as response:
        if response.status!=200:raise RuntimeError("SOURCE_NOT_200")
        data=response.read(limit+1)
    if not 100<len(data)<=limit:raise ValueError("UNBOUNDED_OR_EMPTY_DATA")
    return data
def audit():
    result={"schema_version":"nba-player-impact-source-admission-v1","sources":{},
            "historical_true_publication_time_verified":False,
            "injury_to_game_tipoff_utc_join_verified":False,
            "player_baseline_training_complete":False,
            "independent_market_holdout_complete":False,
            "promotion":"BLOCKED_REQUIRE_CHRONOLOGICAL_PAIRED_HOLDOUT"}
    raw={"players":fetch(PLAYER,4000000),"injury":fetch(INJURY,15000000),
         "outcome":fetch(OUTCOME,500000)}
    for name,data in raw.items():
        s=data.decode("utf-8-sig");lines=s.splitlines()
        reader=csv.DictReader(lines)
        columns=reader.fieldnames or []
        rows=list(reader)
        if not rows or len(columns)!=len(set(columns)):raise RuntimeError("MALFORMED_CSV_"+name)
        result["sources"][name]={"sha256":hashlib.sha256(data).hexdigest(),
             "url":(PLAYER if name=="players" else INJURY if name=="injury" else OUTCOME),
             "rows":len(rows),"columns":columns,"first":rows[0] if name=="players" else None}
        result["sources"][name]["first"]=None
        raw[name]=rows
    player_cols=set(result["sources"]["players"]["columns"])
    injury_cols=set(result["sources"]["injury"]["columns"])
    if not {"snapshot_date","snapshot_time","game_date","matchup","team","player","status"}.issubset(injury_cols):
        raise RuntimeError("INJURY_SCHEMA_MISMATCH")
    # Historical snapshots are not automatically proven published before the
    # game's actual start: official schedule tips and release proof are essential.
    counts=Counter(r["status"] for r in raw["injury"])
    result["historical_injury_status_counts"]=dict(counts)
    if not {"player","team","date","lead_status","played"}.issubset(set(result["sources"]["outcome"]["columns"])):
        raise RuntimeError("OUTCOME_SCHEMA_MISMATCH")
    result["outcome_label_count"]=len(raw["outcome"])
    result["player_schema_has_minutes"]=any("MIN"==x.upper() or "MINUTES" in x.upper() for x in player_cols)
    result["player_schema_has_identity"]=any(x.lower() in ("player","player_name","player_id","name") for x in player_cols)
    result["player_schema_has_date"]=any(x.lower() in ("date","game_date","game_date_est") for x in player_cols)
    result["player_schema_has_team"]=any(x.lower() in ("team","team_abbreviation","team_name") for x in player_cols)
    result["player_games_structurally_usable"]=all(result[k] for k in (
        "player_schema_has_minutes","player_schema_has_identity","player_schema_has_date","player_schema_has_team"))
    result["reason"]="Even with valid player minutes, no independent timestamp-proven pretip fixture alignment and fresh untouched injury-impact holdout is available"
    return result
def selftest():
    assert len({"snapshot_date","snapshot_time","game_date","matchup","team","player","status"})==7
    print("NBA_PLAYER_IMPACT_ADMISSION_SELF_TEST_PASS")
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--self-test",action="store_true")
    a.add_argument("--out",default="nba-player-impact-admission.json")
    x=a.parse_args()
    if x.self_test:selftest()
    else:
        result=audit()
        Path(x.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps({k:v for k,v in result.items() if k!="sources"},ensure_ascii=False))
        print("SOURCE_ROWS",[(k,v["rows"],v["columns"]) for k,v in result["sources"].items()])
