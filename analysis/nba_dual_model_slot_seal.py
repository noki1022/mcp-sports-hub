#!/usr/bin/env python3
"""Only first pretip independently sealed forecast per date+capture slot.

Run in ARCHIVER job, never inside original model or shadow Docker inference.
The original 21:30 pushed forecast/HTML is read by ARCHIVER ONLY after
both models have independently forecast and is sealed alongside the shadow.
No results are read. Dedicated Git branch prohibits routine rewrites.
"""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from datetime import datetime,timezone,timedelta,time
from zoneinfo import ZoneInfo
BJ=ZoneInfo('Asia/Shanghai')

SCHEMA="nba-dual-model-2130-independent-seal-v1"
def dt(v):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError,TypeError):return None
def sha(b):return hashlib.sha256(b).hexdigest()
def copy(src,dst):
    data=Path(src).read_bytes()
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_bytes(data)
    return sha(data)
def load(path):return json.loads(Path(path).read_text())
def seal(source,main,root,day,slot,run_id,now):
    src=Path(source);main=Path(main);target=Path(root)/day/slot
    if target.exists():
        raise ValueError("FIRST_FREEZE_ALREADY_SEALED_NEVER_OVERWRITE")
    if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day)
            or slot not in ("1200","1400","1500","1800","2100","2130","0030","0330")
            or not str(run_id).isdigit()):
        raise ValueError("UNSUPPORTED_CAPTURE_SLOT_OR_ORIGINAL_RUN")
    original=load(src/"input_manifest.json")
    candidate=load(src/"independent_prediction.json")
    if original.get("schema_version")!="nba-independent-dual-shadow-source-only-v1":
        raise ValueError("MISSING_SOURCE_ONLY_WHITELIST_PROOF")
    if (original.get("target_date")!=day or original.get("slot")!=slot or
            original.get("original_completed_workflow_id")!=str(run_id) or
            candidate.get("target_date")!=day or candidate.get("slot")!=slot):
        raise ValueError("SHADOW_AND_ORIGINAL_SOURCE_IDENTITY_DIVERGED")
    if candidate.get("schema_version")!="nba-independent-market-only-fiveplay-v1":
        raise ValueError("SHADOW_MODEL_TYPE_INVALID")
    if candidate.get("original_model_inputs_read") is not False or (
            candidate.get("postgame_data_read") is not False):
        raise ValueError("INDEPENDENT_MODEL_CLAIM_INVALID")
    generated=dt(candidate.get("generated_at_utc"))
    collected=dt(original.get("source_captured_utc"))
    if not generated or not collected or not collected<=generated<=now:
        raise ValueError("PREDICTION_NOT_AFTER_REAL_CAPTURE_OR_AFTER_ARCHIVE")
    if slot=="2130":
        expected=datetime.fromisoformat(day).date()-timedelta(days=1)
        sg,sc=generated.astimezone(BJ),collected.astimezone(BJ)
        if not (sg.date()==sc.date()==expected and
                time(21,30)<=sc.time()<time(22,0) and
                time(21,30)<=sg.time()<time(22,0)):
            raise ValueError("NOT_ACTUAL_BEIJING_2130_FINAL_MODEL_AND_SNAPSHOT")
    if not candidate.get("games"):raise ValueError("EMPTY_PREDICTION_BOARD")
    for g in candidate["games"]:
        tip=dt(g.get("tipoff_beijing"))
        if not tip or not now<tip:
            raise ValueError("GIT_LOCK_NOT_CONFIRMED_BEFORE_ALL_MATCH_TIPS")
        if set(g.get("markets",{}))!=set(candidate["five_target_markets"]):
            raise ValueError("INCOMPLETE_INDEPENDENT_FIVE_MARKET_ANSWER")
    required=("input_manifest.json","joined.json","consensus.json","jingcai.json",
              "independent_prediction.json")
    for name in required:
        if not (src/name).is_file():raise ValueError("MISSING_SOURCE_ONLY_FROZEN_DOCUMENT:"+name)
    if (src/"previous.json").is_file():
        required+=("previous.json",)
    for key,expected in original.get("sanitized_inputs_sha256",{}).items():
        if sha((src/(key+".json")).read_bytes())!=expected:
            raise ValueError("SANITIZED_INPUT_HASH_CHANGED_AFTER_GENERATION")
    for key,expected in candidate.get("input_sha256",{}).items():
        if sha((src/(key+".json")).read_bytes())!=expected:
            raise ValueError("MODEL_INPUT_HASH_MISMATCH:"+key)
    marker=main/"reports/pushplus-sent"/day/(slot+".json")
    if not marker.is_file():
        raise ValueError("ORIGINAL_PUSHPLUS_ACCEPTANCE_NOT_ARCHIVED")
    accepted=load(marker)
    if accepted.get("state")!="API_ACCEPTED_NOT_DEVICE_CONFIRMED" or (
            str(accepted.get("run_id"))!=str(run_id)):
        raise ValueError("WRONG_OR_UNACCEPTED_ORIGINAL_PUSH_RUN")
    # Prevalidate all permanent 21:30 original evidence BEFORE creating the
    # append-once directory, so a recoverable missing input cannot poison
    # the first sealed slot path.
    if slot=="2130":
        base=main/"reports/daily"/day/"2130"
        five=base/"nba_five_market_forecast.json"
        html=base/"nba_priority_iphone.html"
        if not five.is_file() or not html.is_file():
            raise ValueError("NO_ORIGINAL_2130_SENT_FORECAST_AND_HTML")
        original_five=load(five)
        if (original_five.get("target_date")!=day or
                len(original_five.get("games",[]))!=len(candidate["games"])):
            raise ValueError("ORIGINAL_2130_EXAM_NOT_SAME_GAME_COHORT")
        co={str(g["game_id"]):g for g in candidate["games"]}
        for g in original_five["games"]:
            x=co.get(str(g["game_id"]))
            if not x or (g.get("home_team"),g.get("away_team"))!=(
                    x["home_team"],x["away_team"]):
                raise ValueError("ORIGINAL_AND_SHADOW_2130_HOME_AWAY_MISMATCH")
            if set(g.get("markets",{}))!=set(x["markets"]):
                raise ValueError("ORIGINAL_AND_SHADOW_FIVE_PLAYS_MISSING")
    target.mkdir(parents=True)
    hashes={name:copy(src/name,target/name) for name in required}
    hashes["original_pushplus_marker.json"]=copy(marker,target/"original_pushplus_marker.json")
    if slot=="2130":
        hashes["original_2130_five_market_forecast.json"]=copy(
            five,target/"original_2130_five_market_forecast.json")
        hashes["original_2130_pushed_iphone.html"]=copy(
            html,target/"original_2130_pushed_iphone.html")
    if slot!="2130":
        if any((target/x).exists() for x in (
            "original_2130_five_market_forecast.json","original_2130_pushed_iphone.html")):
            raise ValueError("NONFINAL_SLOT_CONTAINS_FINAL_EXAM")
    proof={
       "schema_version":SCHEMA,"target_date":day,"slot":slot,
       "is_authoritative_final_exam":slot=="2130",
       "original_production_push_run_id":str(run_id),
       "shadow_generated_at_utc":generated.isoformat(),
       "first_successful_archive_at_utc":now.isoformat(),
       "earliest_tipoff_utc":min(dt(g["tipoff_beijing"]) for g in candidate["games"]).isoformat(),
       "sha256":dict(sorted(hashes.items())),
       "never_reconstruct_or_retrain_from_final":True,
       "prediction_process_cannot_read_original_forecast":True,
       "both_model_answers_are_separately_frozen":slot=="2130",
       "no_outcome_field_in_this_archive":True,
       "archive_unique_per_beijing_date_slot":True,
    }
    (target/"seal.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("NBA_TWO_INDEPENDENT_MODELS_SEALED",day,slot,len(candidate["games"]),len(hashes))
    return proof
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--from-artifact",required=True)
    p.add_argument("--original-repo",default=".")
    p.add_argument("--ledger-root",default="reports/dual-model-slot-lock")
    p.add_argument("--day",required=True)
    p.add_argument("--slot",required=True)
    p.add_argument("--source-run-id",required=True)
    a=p.parse_args()
    seal(a.from_artifact,a.original_repo,a.ledger_root,a.day,a.slot,
         a.source_run_id,datetime.now(timezone.utc))
if __name__=="__main__":main()
