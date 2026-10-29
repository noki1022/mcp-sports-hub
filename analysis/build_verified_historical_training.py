#!/usr/bin/env python3
"""Build reproducible quarantined NBA historical score-only training artifact.

No odds, post-game Elo, individual-game feature leakage or current holdout.
A train-*candidate* dataset, not automatically promoted into production.
"""
import csv,hashlib,json,sys
from collections import Counter
from pathlib import Path
from datetime import date
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analysis"))
from nba_538_training_source import bounded_fetch as fetch, SOURCE as SOURCE538, LINE_SHEET,verify as verify_538
from nba_2015_22_training_expansion import UPSTREAM, crossverify as verify_new

EXPECTED=("date","home","away","home_points","away_points","playoffs")
def main():
    out=Path("/tmp/nba-historical-training-candidate")
    out.mkdir(exist_ok=True)
    ref=fetch(LINE_SHEET,limit=9_000_000)
    a,am=verify_538(fetch(SOURCE538,limit=25_000_000),ref)
    b,bm=verify_new(fetch(UPSTREAM,limit=22_000_000),ref)
    counts={"2007_2015":len(a),"2015_2022":len(b)}
    if len(a)<9800 or len(b)<8600:raise RuntimeError("SOURCE_COVERAGE_REGRESSED")
    allgames=a+b
    keys=[(x["date"],x["home"],x["away"]) for x in allgames]
    if len(set(keys))!=len(keys):raise RuntimeError("DUPLICATE_BETWEEN_SOURCES")
    for row in allgames:
        if set(row)!=set(EXPECTED):raise RuntimeError("UNAPPROVED_FEATURE_COLUMN")
        if row["date"]>="2022-08-01":raise RuntimeError("TRAIN_HOLDOUT_CONTAMINATION")
        if row["date"]<"2007-08-01":raise RuntimeError("OUTSIDE_APPROVED_PERIOD")
        if row["home"]==row["away"] or row["home_points"]==row["away_points"]:
            raise RuntimeError("INVALID_NBA_GAME")
    allgames.sort(key=lambda x:(x["date"],x["home"],x["away"]))
    name=out/"nba_verified_scores_2007_2022.csv"
    with name.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=EXPECTED)
        w.writeheader()
        w.writerows(allgames)
    digest=hashlib.sha256(name.read_bytes()).hexdigest()
    if len(list(csv.DictReader(name.open(encoding="utf-8"))))!=len(allgames):
        raise RuntimeError("OUTPUT_ROW_COUNT_MISMATCH")
    manifest={
       "status":"REPRODUCIBLE_RESEARCH_TRAINING_CANDIDATE",
       "dataset_filename":name.name,"sha256":digest,"games":len(allgames),
       "batches":counts,
       "source_538_sha256":am["source_sha256"],
       "source_neil_sha256":bm["source_sha256"],
       "reference_sha256":am["reference_sha256"],
       "source_license_note":"538 CC BY 4.0 and Neil repository MIT with underlying upstream rights review required",
       "source_independence_verified":False,
       "columns":list(EXPECTED),
       "time_rule":"Use historical completed games ONLY when game date < prediction date; same-day batch",
       "postgame_elo_forbidden":True,"odds_columns_forbidden":True,
       "production_model_unchanged":True,
       "not_authorized_for_promotion_to_live_odds_model":True,
    }
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    print("HISTORICAL_TRAINING_CANDIDATE_READY "+json.dumps(manifest,sort_keys=True,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
