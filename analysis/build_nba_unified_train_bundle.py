#!/usr/bin/env python3
"""Finalize NBA internal-research train/validation from VERIFIED score/team/player.

Runs three independently tested builders with temporary storage; merges only
identical (date,home,away) labels and historical features. Complete-case feature
rows are the fully populated high-quality set; base rows stay available via the
base training release for reduced-coverage games. No odds, injuries, game-day
boxscore, raw archive or sealed holdout data in the release.

The data remains subject to upstream reuse/publication rights and price-time
proof. This does not change production model inputs.
"""
from __future__ import annotations
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path("/tmp/nba-unified-strict-train-v1")
SOURCE_FILES={
    "base":Path("/tmp/nba-train-ready-v1"),
    "team":Path("/tmp/nba-team-stats-train-ready"),
    "player":Path("/tmp/nba-player-aggregate-research"),
}
SPLITS=("train","validation")
SOURCE_NAMES={
    "base":{"train":"train.csv","validation":"validation.csv"},
    "team":{"train":"train_team_enriched.csv","validation":"validation_team_enriched.csv"},
    "player":{"train":"train_player_agg.csv","validation":"validation_player_agg.csv"},
}
LABELS=("home_win","home_margin","final_total")
KEY=("date","home","away")
BASE_NUMERIC=("home_wins5","away_wins5","home_margin5","away_margin5","home_for5",
              "away_for5","home_against5","away_against5","home_wins10","away_wins10",
              "home_margin10","away_margin10","home_for10","away_for10",
              "home_against10","away_against10","home_rest_days","away_rest_days",
              "h2h_home_margin5","h2h_prior_games")
TEAM_STATS=("off_rating","def_rating","pace","efg_pct","tm_tov_pct","oreb_pct")
TEAM_NUMERIC=tuple(f"{side}_{stat}{n}" for side in ("home","away") for stat in TEAM_STATS for n in (5,10))
PLAYER_NUMERIC=("home_player_points5","away_player_points5","home_player_top3_share5",
                "away_player_top3_share5","home_player_active_count5","away_player_active_count5")
FEATURES=BASE_NUMERIC+TEAM_NUMERIC+PLAYER_NUMERIC
COLS=KEY+FEATURES+LABELS
TRAIN_END="2019-08-01"
VAL_END="2021-08-01"

def key(r):
    return tuple(r[c] for c in KEY)

def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path,part,source):
    if not path.is_file():raise RuntimeError(f"MISSING_VERIFIED_INPUT:{path}")
    with path.open(encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f)
        rows=list(reader)
        fields=set(reader.fieldnames or [])
    required=set(KEY+LABELS+BASE_NUMERIC)
    if source=="team":required|=set(TEAM_NUMERIC)
    if source=="player":required|=set(PLAYER_NUMERIC)
    if not required.issubset(fields):raise RuntimeError("MISSING_COLUMNS_"+source)
    mapped={}
    for r in rows:
        k=key(r)
        if k in mapped:raise RuntimeError(f"DUPLICATE_{source}_{part}:{k}")
        day=k[0]
        if not ((day<TRAIN_END) if part=="train" else (TRAIN_END<=day<VAL_END)):
            raise RuntimeError("WRONG_CHRONOLOGICAL_SPLIT")
        if not all(r.get(c) not in (None,"") for c in required):
            raise RuntimeError("MISSING_REQUIRED_VALUE_"+source)
        if int(r["home_win"])!=int(float(r["home_margin"])>0):
            raise RuntimeError("LABEL_INCONSISTENCY_"+source)
        if not 80<=float(r["final_total"])<=400:
            raise RuntimeError("INVALID_FINAL_TOTAL")
        if any(not math.isfinite(float(r[c])) for c in required-set(KEY+LABELS)):
            raise RuntimeError("NONFINITE_FEATURE_"+source)
        mapped[k]=r
    return mapped,{"rows":len(rows),"sha256":fingerprint(path),"filename":path.name}

def combine(inputs,part):
    base=inputs["base"]; team=inputs["team"]; player=inputs["player"]
    if not set(team).issubset(base) or not set(player).issubset(base):
        raise RuntimeError("NON_BASE_MATCHES_IN_ENRICHED_SOURCES")
    missing=Counter()
    result=[]
    for k in sorted(base):
        b=base[k];t=team.get(k);p=player.get(k)
        if t is None:missing["MISSING_VERIFIED_TEAM_HISTORY"]+=1
        if p is None:missing["MISSING_VERIFIED_PLAYER_HISTORY"]+=1
        if t is None or p is None:continue
        for other,tag in ((t,"team"),(p,"player")):
            for c in LABELS+BASE_NUMERIC:
                if other[c]!=b[c]:
                    raise RuntimeError(f"{tag.upper()}_LABEL_OR_BASE_FEATURE_CONFLICT_{c}")
        row={c:b[c] for c in KEY+BASE_NUMERIC}
        row.update({c:t[c] for c in TEAM_NUMERIC})
        row.update({c:p[c] for c in PLAYER_NUMERIC})
        row.update({c:b[c] for c in LABELS})
        if set(row)!=set(COLS):raise RuntimeError("SCHEMA_NOT_WHITELISTED")
        if not all(math.isfinite(float(row[c])) for c in FEATURES):
            raise RuntimeError("INVALID_FEATURE")
        result.append(row)
    if not result:raise RuntimeError("NO_COMPLETE_CASE_GAMES")
    return result,dict(missing)

def selftest():
    core={c:"100" for c in BASE_NUMERIC+LABELS}
    core["home_win"]="1";core["home_margin"]="8";core["final_total"]="210"
    core.update({"date":"2018-12-01","home":"BOS","away":"NYK"})
    team={**core,**{c:"0.51" for c in TEAM_NUMERIC}}
    player={**core,**{c:"1" for c in PLAYER_NUMERIC}}
    got,miss=combine({"base":{key(core):core},"team":{key(team):team},"player":{key(player):player}},"train")
    assert len(got)==1 and not miss
    bad=dict(team,final_total="211")
    try:
        combine({"base":{key(core):core},"team":{key(bad):bad},"player":{key(player):player}},"train")
        raise AssertionError("LABEL_MISMATCH_ACCEPTED")
    except RuntimeError as e:assert "CONFLICT" in str(e)
    assert all(c not in COLS for c in ("odds_date","moneyline_home","last_fetched","target_game_pts"))
    print("NBA_UNIFIED_STRICT_TRAIN_SELF_TEST_PASS")

def main():
    if len(sys.argv)>1 and sys.argv[1]=="--self-test":return selftest()
    if "--from-artifacts" not in sys.argv:
        for name in ("export_nba_train_ready.py","nba_team_enriched_training.py","nba_player_aggregate_training.py"):
            subprocess.run([sys.executable,str(ROOT/"analysis"/name)],check=True)
    else:
        for label,folder in SOURCE_FILES.items():
            if not folder.is_dir():raise RuntimeError("VERIFIED_ARTIFACT_NOT_AVAILABLE_"+label)
    OUT.mkdir(parents=True,exist_ok=True)
    input_files={};artifacts={};counts={};rejects={}
    for part in SPLITS:
        sources={}
        for label in SOURCE_FILES:
            path=SOURCE_FILES[label]/SOURCE_NAMES[label][part]
            sources[label],info=load(path,part,label)
            input_files[f"{label}_{part}"]=info
        rows,missing=combine(sources,part)
        if part=="train" and len(rows)<13000:raise RuntimeError("TRAIN_COVERAGE_REGRESSED")
        if part=="validation" and len(rows)<2000:raise RuntimeError("VALIDATION_COVERAGE_REGRESSED")
        path=OUT/(part+"_unified_complete.csv")
        with path.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=COLS,extrasaction="raise")
            writer.writeheader();writer.writerows(rows)
        with path.open(encoding="utf-8",newline="") as f:
            rr=list(csv.DictReader(f))
        if len(rr)!=len(rows):raise RuntimeError("OUTPUT_TRUNCATED")
        artifacts[part]={"name":path.name,"rows":len(rows),"sha256":fingerprint(path),
                         "date_first":rows[0]["date"],"date_last":rows[-1]["date"]}
        counts[part]=len(rows);rejects[part]=missing
    manifest={
        "status":"MODEL_READABLE_INTERNAL_RESEARCH_TRAIN_VALIDATION",
        "columns":list(COLS),
        "feature_columns":list(FEATURES),
        "labels":list(LABELS),
        "features_n":len(FEATURES),
        "split_boundaries":{"train_end_exclusive":TRAIN_END,"validation_end_exclusive":VAL_END,
                            "sealed_test_starts":"2021-08-01"},
        "split_counts":counts,
        "inputs":input_files,
        "feature_missing_rejection_counts":rejects,
        "artifacts":artifacts,
        "asof_policy":"historical source game date < prediction date minus 1 day; no same-day",
        "historical_publication_time_and_upstream_rights_not_fully_proven":True,
        "all_score_rows_have_three_route_match_before_feature_generation":True,
        "all_feature_stats_from_historical_complete_games":True,
        "odds_accepted":0,
        "odds_unverified_excluded":True,
        "raw_player_rows_released":False,
        "sealed_holdout_exported":False,
        "production_model_modified":False,
        "file_retention":"7 days in temporary GitHub Actions artifact",
    }
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,sort_keys=True),encoding="utf-8")
    (OUT/"README.txt").write_text(
       "NBA internal research training CSV with lagged historical score, team, player features.\n"
       "NOT bookmaker training data; no historical odds or injury history. No sealed holdout.\n"
       "The upstream reuse rights and exact original publication times have not been independently proven.\n"
       "Do not use this bundle for public redistribution or production auto-promotion.\n",encoding="utf-8")
    print("NBA_UNIFIED_FINAL_TRAIN_PACKAGE "+json.dumps(manifest,ensure_ascii=False,sort_keys=True),flush=True)
    assert len(COLS)==len(set(COLS)) and len(FEATURES)==48
if __name__=="__main__":main()
