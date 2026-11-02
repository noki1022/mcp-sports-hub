#!/usr/bin/env python3
"""Grade exactly-sealed pretip research injury-minutes model pairs after NBA finals.

Never infer a missing injury forecast from a baseline or refit on the outcome.
Consumes the original GitHub Actions artifact sha and its paired pretip records;
settles only by exact ESPN event ID, team directions and close tipoff UTC.
Research baseline here is historical team-form model, not production.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone,date
from hashlib import sha256
import json,math
from pathlib import Path
import numpy as np

import nba_multibook_asof_settled_ledger as E

def stamp(value):
    """Parse strict explicit-offset timestamps without importing data collectors."""
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:
        raise ValueError("UNZONED_FORECAST_CAPTURE")
    return d.astimezone(timezone.utc)

SCHEMA="nba-frozen-injury-minutes-pair-independent-settlement-v1"
PRETIP_SCHEMA="nba-frozen-research-injury-minutes-paired-v1"
MAX_DATES=5

def read(original,manifest):
    rows_raw=Path(original).read_bytes()
    meta_raw=Path(manifest).read_bytes()
    report=json.loads(meta_raw)
    if report.get("schema_version")!=PRETIP_SCHEMA:
        raise ValueError("UNRECOGNIZED_ORIGINAL_FORECAST_SCHEMA")
    if sha256(rows_raw).hexdigest()!=report.get("forecast_pair_sha256"):
        raise ValueError("ORIGINAL_FROZEN_FORECAST_HAS_BEEN_MODIFIED")
    if (report.get("no_edits_to_existing_production_injury_shadow") is not True
        or report.get("production_promotion_allowed") is not False
        or report.get("official_original_http_publication_utc_verified") is not False):
        raise ValueError("SOURCE_CLAIMS_NOT_AUTHENTICATED")
    rows=[json.loads(s) for s in rows_raw.splitlines()]
    if not rows or len(rows)!=report["future_games"]:
        raise ValueError("SOURCE_FORECAST_COUNT_CHANGED")
    if sum(r["status"]=="PAIRED_RESEARCH_FORECAST_FROZEN" for r in rows)!=report["research_pairs"]:
        raise ValueError("SOURCE_PAIRED_GAME_COUNT_CHANGED")
    captured=stamp(report["captured_utc"])
    ids=set()
    for r in rows:
        eid=str(r["nba_game_id"])
        tip=stamp(r["tipoff_utc"])
        before=stamp(r["paired_forecast_capture_utc"])
        original_capture=stamp(r["original_injury_capture_utc"])
        if (not eid.isdecimal() or eid in ids or not original_capture<=before<=captured
            or before>=tip or not r.get("research_only")
            or r.get("existing_production_model_changed") is not False
            or r.get("own_team_form_vs_injury_model_only") is not True):
            raise ValueError("NOT_A_GENUINE_PRETIP_UNMODIFIED_PAIR")
        ids.add(eid)
        if r["status"]=="PAIRED_RESEARCH_FORECAST_FROZEN":
            if (r.get("not_the_existing_production_probability") is not True
                or r.get("feature_schema")!=
                "status_weighted_PRIOR_SAME_TEAM_minutes_home_minus_away_over_40"):
                raise ValueError("RESEARCH_MODEL_MISATTRIBUTED")
            for name in ("team_form_only_home_probability","injury_minutes_home_probability"):
                p=r.get(name)
                if not isinstance(p,(int,float)) or not math.isfinite(p) or not 0<p<1:
                    raise ValueError("UNSEALED_PREDICTION_PROBABILITY")
            if any(p.get("last_prior_game_date")>=tip.date().isoformat()
                   for p in r["players_with_provenance"]):
                raise ValueError("TARGET_GAME_PLAYER_LOG_LEAK")
        else:
            if ("team_form_only_home_probability" in r or
                "injury_minutes_home_probability" in r or
                "block_reason" not in r):
                raise ValueError("MISSING_INJURY_SIGNAL_SILENTLY_IMPUTED")
    return rows,report

def grade(rows,now=None,fetch=E.fetch_espn_day):
    now=now or datetime.now(timezone.utc)
    paired=[r for r in rows if r["status"]=="PAIRED_RESEARCH_FORECAST_FROZEN"]
    # ESPN scoreboard takes American Eastern game dates, not UTC:
    from zoneinfo import ZoneInfo
    eastern=ZoneInfo("America/New_York")
    days=sorted({stamp(r["tipoff_utc"]).astimezone(eastern).date() for r in paired})
    if len(days)>MAX_DATES:
        raise RuntimeError("TOO_MANY_DISTINCT_PROSPECTIVE_DATE_REQUESTS")
    finals={}
    duplicates=set()
    failures=[]
    evidence=[]
    for d in days:
        try:
            url,doc,digest=fetch(d)
            events,invalid=E.parse_espn(doc,url,now.isoformat().replace("+00:00","Z"))
            evidence.append({"eastern_game_day":str(d),"url":url,
                             "sha256":digest,"finals":len(events),
                             "excluded":dict(invalid)})
            for x in events:
                eid=str(x["espn_event_id"])
                if eid in finals:duplicates.add(eid)
                else:finals[eid]=x
        except (KeyError,TimeoutError,ValueError,OSError,TypeError) as exc:
            failures.append({"game_day_eastern":str(d),"error_type":type(exc).__name__})
    for eid in duplicates:finals.pop(eid,None)
    outcomes=[];count=Counter()
    for r in rows:
        item={"nba_game_id":r["nba_game_id"],"home":r["home"],"away":r["away"],
              "tipoff_utc":r["tipoff_utc"],
              "original_pretip_capture_utc":r["paired_forecast_capture_utc"],
              "original_forecast_status":r["status"],
              "preexisting_block_reason":r.get("block_reason"),
              "team_form_only_probability":r.get("team_form_only_home_probability"),
              "injury_minutes_probability":r.get("injury_minutes_home_probability")}
        if r["status"]!="PAIRED_RESEARCH_FORECAST_FROZEN":
            item["grade_status"]="NO_PRETIP_INJURY_PAIRED_FORECAST"
        elif now<stamp(r["tipoff_utc"])+timedelta(minutes=120):
            item["grade_status"]="PENDING_GAME_NOT_COMPLETED"
        else:
            final=finals.get(str(r["nba_game_id"]))
            if final is None:
                item["grade_status"]="FINAL_NOT_IN_ESPN"
            elif (final["home"]!=r["home"] or final["away"]!=r["away"]
                  or abs((stamp(final["score_tip_utc"])-
                          stamp(r["tipoff_utc"])).total_seconds())>10800):
                item["grade_status"]="ESPN_EVENT_OR_HOME_AWAY_CONFLICT"
            else:
                y=int(final["home_points"]>final["away_points"])
                p0=float(r["team_form_only_home_probability"])
                p1=float(r["injury_minutes_home_probability"])
                item.update({
                    "grade_status":"OFFICIAL_FINAL_PAIR_GRADED",
                    "final_score_home":final["home_points"],
                    "final_score_away":final["away_points"],
                    "home_win":y,
                    "baseline_correct":int((p0>=.5)==bool(y)),
                    "injury_correct":int((p1>=.5)==bool(y)),
                    "baseline_brier":(p0-y)**2,
                    "injury_brier":(p1-y)**2,
                    "injury_minus_baseline_brier":(p1-y)**2-(p0-y)**2,
                    "baseline_logloss":-math.log(p0 if y else 1-p0),
                    "injury_logloss":-math.log(p1 if y else 1-p1),
                    "original_probabilities_not_recomputed":True,
                    "official_final_collected_utc":final["score_collected_utc"],
                })
        count[item["grade_status"]]+=1
        outcomes.append(item)
    valid=[r for r in outcomes if r["grade_status"]=="OFFICIAL_FINAL_PAIR_GRADED"]
    mean=lambda name:float(np.mean([r[name] for r in valid])) if valid else None
    return outcomes,{
        "schema_version":SCHEMA,
        "graded_at_utc":now.isoformat().replace("+00:00","Z"),
        "original_future_games":len(rows),
        "original_research_paired_games":len(paired),
        "actually_scored_paired_games":len(valid),
        "status_counts":dict(sorted(count.items())),
        "baseline_home_win_accuracy":mean("baseline_correct"),
        "injury_minutes_home_win_accuracy":mean("injury_correct"),
        "baseline_home_win_brier":mean("baseline_brier"),
        "injury_minutes_home_win_brier":mean("injury_brier"),
        "injury_minus_baseline_brier":mean("injury_minus_baseline_brier"),
        "baseline_logloss":mean("baseline_logloss"),
        "injury_minutes_logloss":mean("injury_logloss"),
        "espn_final_sources":evidence,
        "espn_final_source_failures":failures,
        "not_the_deployed_production_model_comparison":True,
        "does_not_prove_independent_holdout_profit":True,
        "no_auto_promotion":True,
        "production_pipeline_modified":False,
    }

def run(predictions,manifest,out):
    rows,proof=read(predictions,manifest)
    graded,result=grade(rows)
    result["original_pretip_sha256"]=proof["forecast_pair_sha256"]
    dst=Path(out);dst.mkdir(parents=True,exist_ok=True)
    (dst/"injury_minutes_pair_scorecard.json").write_text(
        json.dumps({"summary":result,"per_game":graded},indent=2,
                   ensure_ascii=False,allow_nan=False)+"\n")
    print("NBA_GENUINE_PREGAME_INJURY_PAIR_RESULTS",json.dumps({
        "frozen_pairs":result["original_research_paired_games"],
        "scored_pairs":result["actually_scored_paired_games"],
        "base_Brier":result["baseline_home_win_brier"],
        "injury_Brier":result["injury_minutes_home_win_brier"],
        "status":result["status_counts"],"production_changed":False
    },ensure_ascii=False))
    return result

def selftest():
    import tempfile
    candidate={
        "nba_game_id":"401888888","home":"BOS","away":"LAL",
        "tipoff_utc":"2026-11-03T00:00:00Z",
        "original_injury_capture_utc":"2026-11-02T04:00:00Z",
        "paired_forecast_capture_utc":"2026-11-02T04:10:00Z",
        "status":"PAIRED_RESEARCH_FORECAST_FROZEN","research_only":True,
        "existing_production_model_changed":False,
        "own_team_form_vs_injury_model_only":True,
        "not_the_existing_production_probability":True,
        "feature_schema":"status_weighted_PRIOR_SAME_TEAM_minutes_home_minus_away_over_40",
        "team_form_only_home_probability":.55,
        "injury_minutes_home_probability":.60,
        "players_with_provenance":[{"last_prior_game_date":"2026-10-30"}],
    }
    blocked={
        "nba_game_id":"401888889","home":"ORL","away":"UTA",
        "tipoff_utc":"2026-11-03T01:00:00Z",
        "original_injury_capture_utc":"2026-11-02T04:00:00Z",
        "paired_forecast_capture_utc":"2026-11-02T04:10:00Z",
        "status":"BLOCKED","block_reason":"MISSING_IDENTITY",
        "research_only":True,
        "existing_production_model_changed":False,
        "own_team_form_vs_injury_model_only":True,
    }
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        data=(json.dumps(candidate)+"\n"+json.dumps(blocked)+"\n").encode()
        file=root/"original.jsonl";file.write_bytes(data)
        doc=root/"original_meta.json"
        origin={"schema_version":PRETIP_SCHEMA,
                "forecast_pair_sha256":sha256(data).hexdigest(),
                "no_edits_to_existing_production_injury_shadow":True,
                "production_promotion_allowed":False,
                "official_original_http_publication_utc_verified":False,
                "captured_utc":"2026-11-02T04:11:00Z",
                "future_games":2,"research_pairs":1}
        doc.write_text(json.dumps(origin))
        original,_=read(file,doc)
        file.write_bytes(data+b" ")
        try:read(file,doc)
        except ValueError as exc:
            assert str(exc)=="ORIGINAL_FROZEN_FORECAST_HAS_BEEN_MODIFIED"
        else:raise AssertionError("TAMPERED_SOURCE_UNDETECTED")
    now=datetime(2026,11,3,18,tzinfo=timezone.utc)
    def provider(_day):
        return "https://example.invalid",{"events":[{
          "id":"401888888","date":"2026-11-03T00:00:00Z",
          "status":{"type":{"completed":True}},
          "competitions":[{"competitors":[
            {"homeAway":"home","team":{"displayName":"Boston Celtics"},"score":"112"},
            {"homeAway":"away","team":{"displayName":"Los Angeles Lakers"},"score":"101"}
          ]}]
        }]},"testsource"
    graded,report=grade(original,now,provider)
    assert report["original_future_games"]==2
    assert report["actually_scored_paired_games"]==1
    assert graded[0]["grade_status"]=="OFFICIAL_FINAL_PAIR_GRADED"
    assert graded[1]["grade_status"]=="NO_PRETIP_INJURY_PAIRED_FORECAST"
    assert report["injury_minus_baseline_brier"]<0
    wrong=[{**candidate,"away":"UTA"}]
    grade_rows,report=grade(wrong,now,provider)
    assert report["actually_scored_paired_games"]==0
    assert grade_rows[0]["grade_status"]=="ESPN_EVENT_OR_HOME_AWAY_CONFLICT"
    print("NBA_INJURY_GENUINE_PAIR_FINAL_SCORECARD_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--predictions")
    p.add_argument("--manifest")
    p.add_argument("--out",default="/tmp/nba-frozen-injury-pair-grading")
    p.add_argument("--selftest",action="store_true")
    x=p.parse_args()
    if x.selftest:selftest()
    elif not x.predictions or not x.manifest:
        p.error("--predictions and --manifest required")
    else:run(x.predictions,x.manifest,x.out)
