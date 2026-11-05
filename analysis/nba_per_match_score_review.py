#!/usr/bin/env python3
"""Official-game-covered NBA per-match-final review, research-only publishing gate.

No additional PushPlus. Only immutable latest pretip model answers are graded.
A report cannot be considered final until ALL ESPN NBA game IDs for that Beijing
calendar day have an independently sealed original prediction and verified FT.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime
import sport_match_final_grade as G
import sport_match_final_registry as R
import sport_match_final_review_html as H

VERSION="nba-per-match-scorecard-publication-gate-v1"
def review(root,day,scores,official_ids=None):
    date=datetime.strptime(day,"%Y%m%d")
    assert date.strftime("%Y%m%d")==day
    if not isinstance(scores,dict):
        raise ValueError("OFFICIAL_RESULTS_MAP_REQUIRED")
    finals=G.load_finals(root,"basketball",day)
    final_ids=[str(f.get("official_game_id") or "") for f in finals]
    if len(set(final_ids))!=len(final_ids) or any(not x for x in final_ids):
        raise ValueError("DUPLICATE_OR_EMPTY_FROZEN_OFFICIAL_NBA_GAME_ID")
    # Cross-check one independent OFFICIAL noon cohort. Do NOT infer full
    # slate coverage from a possibly partial ESPN date-window response.
    cohort_ids=set(str(x) for x in official_ids) if official_ids is not None else None
    score_ids=set(str(x) for x in scores)
    missing=sorted((cohort_ids or set())-set(final_ids))
    extra=sorted(set(final_ids)-(cohort_ids or set()))
    missing_scores=sorted((cohort_ids or set())-score_ids)
    unexpected_scores=sorted(score_ids-(cohort_ids or set()))
    if cohort_ids is None:
        reason="INDEPENDENT_NOON_OFFICIAL_SLATE_NOT_VERIFIED"
    elif not cohort_ids or not finals:
        reason="NO_VERIFIED_OFFICIAL_RESULTS_OR_NO_FROZEN_PREGAME_FINALS"
    elif missing or extra or missing_scores or unexpected_scores:
        reason="NBA_INDEPENDENT_OFFICIAL_SLATE_FORECAST_OR_RESULTS_MISMATCH"
    else:
        reason=None
    rows,counters=G.basketball_grade(finals,scores,day)
    graded=G.result("basketball",day,rows,counters)
    incomplete=sorted(str(g["nba_game_id"]) for g in rows if any(
        (x.get("outcome")=="UNSETTLED") for x in g["markets"].values()))
    if incomplete and not reason:reason="OFFICIAL_FINAL_SCORES_PENDING"
    status="READY_ONE_PER_MATCH_FINAL" if not reason else "INCOMPLETE_NOT_PUBLISHABLE"
    return {"status":status,"reason":reason,
            "source_contract":"ESPN_FINAL_BY_EVENT_ID_AND_BJ_TIP_AND_HOME_AWAY_VERIFIED",
            "same_day_official_game_ids":len(cohort_ids or set()),
            "result_source_game_ids":len(score_ids),
            "official_scores_missing":missing_scores,
            "unofficial_score_ids":unexpected_scores,
            "sealed_unique_game_ids":len(final_ids),
            "unsealed_official_ids":missing,
            "sealed_ids_not_in_official_results":extra,
            "unfinished_official_game_ids":incomplete,
            "ready_for_one_daily_review_push":status=="READY_ONE_PER_MATCH_FINAL",
            "scorecard":graded}

def write_report(root,day,scores,out,official_ids=None):
    doc=review(root,day,scores,official_ids)
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    report=doc.pop("scorecard")
    # Preview is a partial research document until the whole game-day settles.
    (dest/"review-preview.html").write_text(H.render(report),encoding="utf-8")
    if doc["ready_for_one_daily_review_push"]:
        (dest/"review.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (dest/"review.html").write_text(H.render(report),encoding="utf-8")
    doc["schema_version"]=VERSION
    doc["target_beijing_day"]=day
    doc["official_source_mapping_sha256"]=R.digest(scores)
    doc["review_sha256"]=report["review_sha256"]
    doc["no_pushplus_called"]=True
    doc["candidate_archive_completeness_checked"]=True
    doc["manifest_sha256"]=R.digest(doc)
    (dest/"manifest.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return doc

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--final-root",required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--scores",required=True)
    p.add_argument("--official-cohort",help="Independent immutable 12:00 official NBA slate; absent means no publication")
    p.add_argument("--out-dir",required=True)
    a=p.parse_args()
    scores=json.loads(Path(a.scores).read_text(encoding="utf-8"))
    ids=None
    if a.official_cohort:
        cohort=json.loads(Path(a.official_cohort).read_text(encoding="utf-8"))
        registry.require(cohort.get("schema_version")=="nba-beijing-noon-cohort-v1",
                         "INDEPENDENT_NOON_COHORT_SCHEMA_UNVERIFIED")
        registry.require(cohort.get("target_beijing_date")==datetime.strptime(a.day,"%Y%m%d").strftime("%Y-%m-%d"),
                         "OFFICIAL_NOON_COHORT_DAY_MISMATCH")
        ids=cohort.get("official_games")
        registry.require(isinstance(ids,dict) and len(ids)==cohort.get("official_count"),
                         "OFFICIAL_COHORT_ID_COUNT_MISMATCH")
        ids=set(ids)
    doc=write_report(a.final_root,a.day,scores,a.out_dir,ids)
    print("NBA_SINGLE_MATCH_REVIEW_GATE",a.day,doc["status"],
          "official",doc["same_day_official_game_ids"],
          "sealed",doc["sealed_unique_game_ids"],
          "missing",len(doc["unsealed_official_ids"]),
          "unfinished",len(doc["unfinished_official_game_ids"]))

if __name__=="__main__":main()
