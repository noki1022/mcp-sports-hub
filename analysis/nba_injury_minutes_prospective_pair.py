#!/usr/bin/env python3
"""Research-only genuine pretip injury-minutes vs same trained team-form comparator.

Reuses original historical NBA paired-study minutes definition exactly:
  team_status_minutes = sum((.90 - archived_status_weight)*prior_same_team_minutes)
  injury_feature = (home_team_status_minutes-away_team_status_minutes)/40

The original study is retrospectively evaluated and publication time unverified.
An actually frozen prospective *new* event forecast can test transferability,
but NEVER calls it a qualified original-production model adjustment, 007 price
edge, or approved causal player impact.
"""
from __future__ import annotations
import argparse
from collections import defaultdict,Counter
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json,math
from pathlib import Path
import numpy as np

import nba_early_injury_replacement_study as H
import nba_injury_cross_season_effect_coefficients as E
import nba_prospective_score_shadow as S
from nba_injury_live_roster_feature_freeze import stamp

SCHEMA="nba-frozen-research-injury-minutes-paired-v1"
REQUIRED_FEATURE="status_weighted_PRIOR_SAME_TEAM_minutes_home_minus_away_over_40"
TOLERANCE=1e-9

def capture_constraints(row,evidence,now):
    """Never silently treat a missing injured player as zero minutes."""
    tip=stamp(row["tipoff_utc"])
    frozen=stamp(row["research_capture_utc"])
    if not (now<tip-timedelta(minutes=10) and frozen<=now):
        return "TIPOFF_OR_CAPTURE_TIME_INVALID"
    if not row.get("official_both_teams_published"):
        return "BOTH_OFFICIAL_TEAM_REPORTS_NOT_PUBLISHED"
    if not row.get("identity_coverage_complete"):
        return "NOT_ALL_OFFICIAL_PLAYER_IDS_AND_SAME_TEAM_MINUTES_VERIFIED"
    if not row.get("injured_players"):
        return "NO_VERIFIABLE_OFFICIAL_PLAYER_ROWS"
    if row.get("injury_adjusted_probability") is not None:
        return "UNEXPECTED_PREEXISTING_NUMERIC_ADJUSTMENT"
    if row.get("candidate_coefficients") is not None:
        return "UNEXPECTED_PREEXISTING_MODEL_COEFFICIENTS"
    if stamp(row["official_pdf_capture_utc"])>now or stamp(row["official_pdf_capture_utc"])>=tip:
        return "LATE_OR_UNVERIFIED_OFFICIAL_CAPTURE"
    if stamp(evidence["capture_end_utc"])>now:
        return "RESEARCH_SNAPSHOT_CAPTURE_FROM_FUTURE"
    if (not row.get("official_pdf_sha256") or
        row["official_pdf_sha256"]!=evidence["official_report"]["sha256"]):
        return "OFFICIAL_REPORT_SHA_MISMATCH"
    by_team={x["team"]:x for x in evidence["roster_sources"]}
    for side in ("home","away"):
        team=row[side]
        current=by_team.get(team)
        if not current or stamp(current["captured_utc"])>now or stamp(current["captured_utc"])>=tip:
            return "ROSTER_MISSING_OR_NOT_PREGAME"
    day=tip.astimezone(S.ET).date().isoformat()
    if row.get("official_report_et_date")!=day:
        return "OFFICIAL_REPORT_GAME_DATE_MISMATCH"
    unique=set()
    for player in row["injured_players"]:
        if player.get("side") not in ("home","away") or player.get("team")!=row[player["side"]]:
            return "INJURED_PLAYER_TEAM_OR_SIDE_MISMATCH"
        if player.get("status") not in H.STATUS:
            return "UNRECOGNIZED_INJURY_STATUS"
        if player.get("identity")!="ID_TEAM_AND_PAST_MINUTES_VALIDATED":
            return "INJURY_ID_NOT_VALIDATED"
        eid=player.get("espn_roster_athlete_id")
        pid=player.get("nba_log_person_id")
        mins=player.get("prior_team_minutes")
        if not str(eid).isdecimal() or not str(pid).isdecimal():
            return "MISSING_DISTINCT_PLAYER_IDS"
        if not isinstance(mins,(int,float)) or not math.isfinite(mins) or not 0<mins<=65:
            return "INVALID_PRIOR_MINUTES"
        if not player.get("last_prior_game_date") or player["last_prior_game_date"]>=day:
            return "FUTURE_PLAYER_GAME_MINUTES"
        if (player["side"],str(pid)) in unique:
            return "DUPLICATE_PLAYER"
        unique.add((player["side"],str(pid)))
    return None

def exact_prior_minutes_feature(row):
    """Historical 2022-24 proxy -- no bench or prior points invented."""
    by_side=defaultdict(float)
    source=[]
    for player in row["injured_players"]:
        signed=(.90-H.STATUS[player["status"]])*float(player["prior_team_minutes"])
        by_side[player["side"]]+=signed
        source.append({"nba_log_person_id":str(player["nba_log_person_id"]),
                       "espn_roster_athlete_id":str(player["espn_roster_athlete_id"]),
                       "team":player["team"],"side":player["side"],
                       "status":player["status"],
                       "prior_same_team_minutes":player["prior_team_minutes"],
                       "signed_status_weighted_minutes":round(signed,6),
                       "last_prior_game_date":player["last_prior_game_date"],
                       "report_pre_tip_verified_by_fetch_clock":True})
    return float((by_side["home"]-by_side["away"])/40.),source

def prior_team_form(past,home,away,fixture_day):
    history=defaultdict(list)
    seen=set()
    for game in sorted(past,key=lambda r:(r["date"],r["home"],r["away"])):
        if game["date"]>=fixture_day:
            continue
        ident=(game["date"],game["home"],game["away"])
        if ident in seen:
            raise RuntimeError("DUPLICATE_COMPLETED_SCORE_GAME")
        seen.add(ident)
        margin=float(game["home_points"]-game["away_points"])
        history[game["home"]].append((game["date"],margin))
        history[game["away"]].append((game["date"],-margin))
    for side in (home,away):
        if len(history[side])<3:
            return None
    return [
        float(np.mean([m for day,m in history[home][-7:]])),
        float(np.mean([m for day,m in history[away][-7:]])),
    ]

def historical_candidate(research_output):
    originals,meta,upstream=H.main(str(Path(research_output).with_suffix(".upstream.json")),
                                  return_paired=True)
    parts,status=E.split(originals)
    if status!="OK":
        raise RuntimeError("HISTORICAL_MINUTES_SOURCE_PARTITION_BLOCKED_"+status)
    baseline=E.fit(parts["fit"],"no_injury_team_form")
    injured=E.fit(parts["fit"],"injury_prior_minutes")
    a=E.metrics(parts["validation"],baseline)
    b=E.metrics(parts["validation"],injured)
    # Selection is based solely on earlier validation, NOT 2025-26 results.
    passed=(b["Brier_ML"]<a["Brier_ML"]-E.MIN_VALIDATION_BRIER_GAIN
            and b["MAE_margin"]<=a["MAE_margin"]+E.MAX_VALIDATION_MAE_REGRESSION)
    # Historical study's 2025-26 has been seen elsewhere; descriptive only.
    outcome={
        "source_unique_games":len(originals),
        "fit_games":len(parts["fit"]),
        "validation_games":len(parts["validation"]),
        "previously_explored_evaluation_games":len(parts["previously_explored_evaluation"]),
        "historical_validation_baseline":a,
        "historical_validation_injury_minutes":b,
        "historical_later_baseline":E.metrics(parts["previously_explored_evaluation"],baseline),
        "historical_later_injury_minutes":E.metrics(parts["previously_explored_evaluation"],injured),
        "minutes_candidate_selected_on_validation_only":bool(passed),
        "historical_report_original_publication_verified":False,
        "feature_used":REQUIRED_FEATURE,
        "historical_archive_sources":upstream["source_hashes"],
        "training_coefficients_frozen_at_this_execution":True,
        "historical_evaluation_previously_explored":True,
        "eligible_for_production":False,
    }
    return baseline,injured,outcome

def fit_record(model):
    return {"name":model["name"],"model_coefficients":[float(x) for x in model["beta"]],
            "feature_mean":[float(x) for x in model["mean"]],
            "feature_scale":[float(x) for x in model["scale"]],
            "margin_sigma":model["train_residual_sigma"],
            "trained_games":model["train_games"]}

def predict_pair(team,injury,base_model,injured_model):
    # Never add full independent model strength to the running production model:
    # this is a separately trained, fully *paired* shadow vs its own baseline.
    baseline_record=("PREGAME",0.,list(team),list(team))
    candidate_record=("PREGAME",0.,list(team),list(team)+[float(injury)])
    base_mu=float(E.predict([baseline_record],base_model)[0])
    injury_mu=float(E.predict([candidate_record],injured_model)[0])
    pb=float(E.probs([base_mu],base_model["train_residual_sigma"])[0])
    pi=float(E.probs([injury_mu],injured_model["train_residual_sigma"])[0])
    return {"team_form_only_margin_mean":round(base_mu,6),
            "team_form_only_home_probability":round(pb,8),
            "injury_minutes_margin_mean":round(injury_mu,6),
            "injury_minutes_home_probability":round(pi,8),
            "injury_minus_own_baseline_margin":round(injury_mu-base_mu,6),
            "compared_on_same_exact_pregame_fixture":True,
            "not_the_existing_production_probability":True}

def seal(features,manifest,past,baseline,injury_model,historical,now):
    if not features:
        raise RuntimeError("EMPTY_OFFICIAL_PREGAME_RESEARCH_INPUT")
    frozen=[]
    used=set()
    counts=Counter()
    for row in features:
        gameid=str(row["game_id"])
        if gameid in used:
            raise RuntimeError("DUPLICATE_FUTURE_EVENT_ID")
        used.add(gameid)
        result={"nba_game_id":gameid,
                "tipoff_utc":row["tipoff_utc"],
                "beijing_tipoff":row["beijing_tipoff"],
                "home":row["home"],"away":row["away"],
                "original_injury_capture_utc":row["research_capture_utc"],
                "paired_forecast_capture_utc":now.isoformat().replace("+00:00","Z"),
                "official_source_sha256":row["official_pdf_sha256"],
                "model_schema":SCHEMA,
                "research_only":True,
                "existing_production_model_changed":False,
                "own_team_form_vs_injury_model_only":True,
                "status":"BLOCKED"}
        reason=capture_constraints(row,manifest,now)
        if reason is None and not historical["minutes_candidate_selected_on_validation_only"]:
            reason="HISTORICAL_MINUTES_CANDIDATE_DID_NOT_PASS_VALIDATION"
        if reason is None:
            day=stamp(row["tipoff_utc"]).astimezone(S.ET).date().isoformat()
            if row["home"]==row["away"]:reason="INVALID_FIXTURE_IDENTITY"
            else:
                team=prior_team_form(past,row["home"],row["away"],day)
                if team is None:
                    reason="INSUFFICIENT_DATE_PRIOR_TEAM_FORM"
        if reason is None:
            value,players=exact_prior_minutes_feature(row)
            result["feature_schema"]=REQUIRED_FEATURE
            result["prior_team_margin_last7"]=team
            result["status_weighted_minutes_delta_home_minus_away_over40"]=round(value,8)
            result["players_with_provenance"]=players
            result.update(predict_pair(team,value,baseline,injury_model))
            result["status"]="PAIRED_RESEARCH_FORECAST_FROZEN"
        else:
            result["block_reason"]=reason
        frozen.append(result)
        counts[result["status"] if result["status"]!="BLOCKED" else result["block_reason"]]+=1
    return frozen,dict(sorted(counts.items()))

def run(features_path,audit_path,out):
    now=datetime.now(timezone.utc)
    raw=Path(features_path).read_bytes()
    saved=Path(audit_path).read_bytes()
    manifest=json.loads(saved)
    if manifest["schema_version"]!="nba-live-injury-roster-strict-prior-minutes-v1":
        raise RuntimeError("INCOMPATIBLE_LIVE_REPORT_SCHEMA")
    if sha256(raw).hexdigest()!=manifest["frozen_jsonl_sha256"]:
        raise RuntimeError("LIVE_SNAPSHOT_SHA256_CHANGED")
    feature_rows=[json.loads(line) for line in raw.decode().splitlines() if line]
    if len(feature_rows)!=manifest["future_games"]:
        raise RuntimeError("LIVE_SNAPSHOT_ROW_COUNT_CHANGED")
    b,i,historical=historical_candidate(Path(out)/"historic_injury_study.json")
    past,score_source=S.load_verified_asof(now)
    eligible,counts=seal(feature_rows,manifest,past,b,i,historical,datetime.now(timezone.utc))
    target=Path(out)
    target.mkdir(parents=True,exist_ok=True)
    fp=target/"frozen_independent_injury_pair.jsonl"
    fp.write_text("".join(json.dumps(row,sort_keys=True,ensure_ascii=False)+"\n" for row in eligible),
                  encoding="utf-8")
    details={
        "schema_version":SCHEMA,
        "source_live_injury_snapshot_sha256":sha256(raw).hexdigest(),
        "source_live_injury_manifest_sha256":sha256(saved).hexdigest(),
        "forecast_pair_sha256":sha256(fp.read_bytes()).hexdigest(),
        "captured_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "historical_candidate":historical,
        "baseline_fit":fit_record(b),
        "injury_minutes_fit":fit_record(i),
        "score_source":score_source,
        "future_games":len(eligible),
        "research_pairs":sum(x["status"]=="PAIRED_RESEARCH_FORECAST_FROZEN" for x in eligible),
        "blocked_reasons":counts,
        "no_generation_of_production_player_catalog":True,
        "no_edits_to_existing_production_injury_shadow":True,
        "no_new_scheduled_jobs":True,
        "official_original_http_publication_utc_verified":False,
        "independent_same_007_line_history_available":False,
        "production_promotion_allowed":False,
    }
    (target/"manifest.json").write_text(json.dumps(details,sort_keys=True,
                                        indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("NBA_GENUINELY_FROZEN_INJURY_MINUTES_RESEARCH_PAIR",json.dumps({
        "future_games":details["future_games"],
        "pairs":details["research_pairs"],"blocked":counts,
        "historical_training_games":historical["fit_games"],
        "historical_validation":historical["historical_validation_injury_minutes"],
        "production_changed":False,
    },ensure_ascii=False))
    return details

def selftest():
    from datetime import timezone
    now=datetime(2026,11,2,5,tzinfo=timezone.utc)
    template={
        "game_id":"401777777","home":"BOS","away":"LAL",
        "tipoff_utc":"2026-11-03T00:00:00Z",
        "beijing_tipoff":"2026-11-03T08:00:00+08:00",
        "research_capture_utc":"2026-11-02T04:00:00Z",
        "official_pdf_capture_utc":"2026-11-02T04:00:00Z",
        "official_pdf_sha256":"test-source",
        "official_report_et_date":"2026-11-02",
        "official_both_teams_published":True,
        "identity_coverage_complete":True,
        "candidate_coefficients":None,"injury_adjusted_probability":None,
        "injured_players":[{
            "team":"BOS","side":"home",
            "status":"Out","identity":"ID_TEAM_AND_PAST_MINUTES_VALIDATED",
            "espn_roster_athlete_id":"1","nba_log_person_id":"2",
            "prior_team_minutes":30.,
            "last_prior_game_date":"2026-10-30"}]}
    manifest={"capture_end_utc":"2026-11-02T04:01:00Z",
              "official_report":{"sha256":"test-source"},
              "roster_sources":[
                {"team":"BOS","captured_utc":"2026-11-02T04:00:00Z"},
                {"team":"LAL","captured_utc":"2026-11-02T04:00:00Z"}]}
    assert capture_constraints(template,manifest,now) is None
    v,players=exact_prior_minutes_feature(template)
    assert abs(v-.675)<1e-9 and len(players)==1
    assert capture_constraints({**template,"injured_players":[{
        **template["injured_players"][0],"last_prior_game_date":"2026-11-02"}]},manifest,now
    )=="FUTURE_PLAYER_GAME_MINUTES"
    assert capture_constraints({**template,"identity_coverage_complete":False},manifest,now
    )=="NOT_ALL_OFFICIAL_PLAYER_IDS_AND_SAME_TEAM_MINUTES_VERIFIED"
    assert capture_constraints({**template,"official_both_teams_published":False},manifest,now
    )=="BOTH_OFFICIAL_TEAM_REPORTS_NOT_PUBLISHED"
    past=[]
    for n in range(4):
        day=f"2026-10-{n+11:02d}"
        past.append({"date":day,"home":"BOS","away":"LAL",
                     "home_points":115+n,"away_points":105+n})
    assert prior_team_form(past,"BOS","LAL","2026-11-02")==[10.,-10.]
    m=E.fit([("2024-01-01",1.,[2.,-1.],[2.,-1.,1.,0.,0.]),
             ("2024-01-02",-1.,[-2.,1.],[-2.,1.,0.,0.,0.]),
             ("2024-01-03",6.,[5.,1.],[5.,1.,1.,0.,0.])],"injury_prior_minutes")
    b=E.fit([("2024-01-01",1.,[2.,-1.],[2.,-1.,1.,0.,0.]),
             ("2024-01-02",-1.,[-2.,1.],[-2.,1.,0.,0.,0.]),
             ("2024-01-03",6.,[5.,1.],[5.,1.,1.,0.,0.])],"no_injury_team_form")
    p=predict_pair([10.,-10.],.675,b,m)
    assert 0<p["injury_minutes_home_probability"]<1
    assert 0<p["team_form_only_home_probability"]<1
    print("NBA_REAL_INJURY_MINUTES_PROSPECTIVE_PAIR_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--features")
    parser.add_argument("--audit")
    parser.add_argument("--out",default="/tmp/nba-frozen-injury-research-pair")
    parser.add_argument("--selftest",action="store_true")
    opts=parser.parse_args()
    if opts.selftest:selftest()
    else:
        if not opts.features or not opts.audit:
            parser.error("--features and --audit are required")
        run(opts.features,opts.audit,opts.out)
