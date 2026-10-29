#!/usr/bin/env python3
"""Build model-readable NBA TRAIN + VALIDATION files from verified historical scores.

This is an internal/offline research training dataset with source attribution.
It does not certify vendor odds rights or authorize external redistribution.
Validation is only used for evaluation, never feature scaling/fitting.
2021-22 sealed holdout is neither exported nor read by the consumer.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from collections import Counter
from datetime import date,timedelta
from pathlib import Path
from nba_chronological_feature_gate import (
    assemble,produce,OUT_FEATURES,OUT_COLS,TRAIN_END,VALID_END,
    HOLDOUT_END,EMBARGO_DAYS,add_day,split_for
)

OUTDIR=Path("/tmp/nba-train-ready-v1")
EXPECTED_LABELS={"home_win","home_margin","final_total"}
INPUT_COLUMNS=["date","home","away",*OUT_FEATURES]
MODEL_COLUMNS=INPUT_COLUMNS+["home_win","home_margin","final_total"]
ALL_ALLOWED=set(OUT_COLS)
ATTRIBUTION={
  "five_thirty_eight":"https://github.com/fivethirtyeight/data/tree/master/nba-elo",
  "five_thirty_eight_license":"CC BY 4.0 (data, per repository README)",
  "neil_paine":"https://github.com/Neil-Paine-1/NBA-elo",
  "neil_paine_license":"MIT repository; based on FiveThirtyEight; carry source attribution",
  "validation_only":"NBA Line Sheet + Kaggle NBA Stats game index, not redistributed",
  "scope":"private/internal model research; upstream author independence and third-party redistribution rights not certified"
}
def hash_file(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def clean(rows):
    counts=Counter()
    keys=set()
    groups={"train":[],"validation":[],"sealed_holdout":[]}
    for r in rows:
        assert set(r)==ALL_ALLOWED
        day=r["date"]
        key=(day,r["home"],r["away"])
        if key in keys:raise ValueError("DUPLICATE_GAME_ACROSS_SPLITS")
        keys.add(key)
        group=split_for(day)
        if r["split"]!=group:raise ValueError("DATE_SPLIT_MISMATCH")
        if not r["feature_latest_source_date"] < add_day(day,-EMBARGO_DAYS):
            raise ValueError("TARGET_OR_SAME_DAY_LEAKAGE")
        if (r["home_win"] not in (0,1) or
            int(r["home_win"])!=int(r["home_margin"]>0) or
            r["home_margin"]==0 or r["final_total"]<80 or r["final_total"]>400):
            raise ValueError("LABEL_CONTRADICTION")
        for keyname in OUT_FEATURES:
            x=float(r[keyname])
            if not math.isfinite(x):raise ValueError("NONFINITE_FEATURE")
        for k in ("home_wins5","away_wins5","home_wins10","away_wins10"):
            if not 0<=float(r[k])<=1:raise ValueError("WIN_RATE_OUT_OF_RANGE")
        if r["home_rest_days"]<2 or r["away_rest_days"]<2:raise ValueError("DATE_EMBARGO_REST_VIOLATION")
        if r["h2h_prior_games"]>5 or r["h2h_prior_games"]<0:raise ValueError("H2H_RANGE")
        counts[group]+=1
        groups[group].append({k:r[k] for k in MODEL_COLUMNS})
    assert sum(counts.values())==len(rows)
    return groups,counts

def write_rows(path,rows):
    with path.open("w",encoding="utf-8",newline="") as out:
        w=csv.DictWriter(out,fieldnames=MODEL_COLUMNS,extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
    with path.open(newline="",encoding="utf-8") as inp:
        reader=csv.DictReader(inp)
        if reader.fieldnames!=MODEL_COLUMNS:raise RuntimeError("HEADER_MISMATCH")
        rec=list(reader)
    if len(rec)!=len(rows):raise RuntimeError("POSTWRITE_COUNT_MISMATCH")
    return {"filename":path.name,"sha256":hash_file(path),"rows":len(rec),
            "date_min":min(x["date"] for x in rec),"date_max":max(x["date"] for x in rec)}

def selftest():
    row={"date":"2019-01-15","home":"BOS","away":"NYK",
         **{k:0.5 for k in OUT_FEATURES},
         "home_rest_days":3,"away_rest_days":3,"h2h_prior_games":0,
         "home_win":1,"home_margin":5,"final_total":205,"split":"train",
         "feature_latest_source_date":"2019-01-12",
         "feature_embargo_days":1}
    groups,counts=clean([row])
    assert counts["train"]==1
    for key,value in (("feature_latest_source_date","2019-01-14"),
                       ("home_win",0),("home_rest_days",1)):
        test=dict(row,**{key:value})
        try:clean([test]);raise AssertionError("INVALID_ROW_WAS_ALLOWED:"+key)
        except ValueError:pass
    assert "feature_latest_source_date" not in MODEL_COLUMNS
    assert "split" not in MODEL_COLUMNS
    assert "playoffs" not in MODEL_COLUMNS
    print("NBA_TRAIN_READY_EXPORT_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return selftest()
    games,original_rejections,third_hash=assemble()
    rows,cold_start_rejections=produce(games)
    groups,counts=clean(rows)
    if not (14500<=counts["train"]<=15000 and
            2000<=counts["validation"]<=2300 and
            1200<=counts["sealed_holdout"]<=1400):
        raise RuntimeError("DATA_COUNTS_REGRESSED")
    OUTDIR.mkdir(parents=True,exist_ok=True)
    artifacts={
        "train":write_rows(OUTDIR/"train.csv",groups["train"]),
        "validation":write_rows(OUTDIR/"validation.csv",groups["validation"])
    }
    # NEVER materialize the sealed holdout rows into this artifact.
    manifest={
      "release_type":"PRIVATE_INTERNAL_HISTORICAL_TRAIN_READY_V1",
      "production_automatically_modified":False,
      "model_fitted_with_sealed_holdout":False,
      "holdout_rows_exported":False,
      "sample_counts":dict(counts),
      "train_and_validation_rows_written":counts["train"]+counts["validation"],
      "schema":MODEL_COLUMNS,
      "numeric_feature_columns":OUT_FEATURES,
      "labels":["home_win","home_margin","final_total"],
      "split_calendar":{"train_end_exclusive":TRAIN_END,
          "validation_end_exclusive":VALID_END,"sealed_holdout_end_exclusive":HOLDOUT_END},
      "feature_rule":"Only result dates strictly earlier than prediction date minus 1-day embargo; same-day batches",
      "source_publication_timestamp_verified":False,
      "market_odds_included":False,"injuries_included":False,
      "attribution":ATTRIBUTION,
      "sample_rejections":original_rejections,
      "cold_start_rejections":cold_start_rejections,
      "third_route_game_index_sha256":third_hash,
      "artifacts":artifacts
    }
    manifest_path=OUTDIR/"manifest.json"
    manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True,ensure_ascii=False),encoding="utf-8")
    (OUTDIR/"NOTICE.txt").write_text(
        "INTERNAL RESEARCH TRAINING CANDIDATE\n"
        "Historical NBA scores provided by FiveThirtyEight (data CC BY 4.0), "
        "Neil Paine (MIT repository, derived from FiveThirtyEight). "
        "See manifest.json for exact source URLs. "
        "Scores crosschecked against Line Sheet and Kaggle NBA Stats index; "
        "upstream independence and redistribution permissions not certified.\n"
        "No proprietary bookmaker quotes are included.\n",encoding="utf-8")
    print("NBA_TRAIN_READY_V1 "+json.dumps(manifest,ensure_ascii=False,sort_keys=True),flush=True)

if __name__=="__main__":main()
