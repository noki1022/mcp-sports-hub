#!/usr/bin/env python3
"""Stage an actual pre-tip five-play model in a closed input allowlist.

Host-side script only copies source snapshots, frozen original model and
whitelisted inference code into an isolated directory. The prediction process
itself runs in a separate NETWORK-DISABLED, read-only Docker container.
The source tree, postgame labels, training records, git repository, secrets
and GitHub token are not mounted into that Docker process.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile

import nba_shadow_postmarket_runner as RUN

SCHEMA="nba-five-play-pretip-container-allowlist-v1"
ALLOWED_SOURCES=(
    "analysis/nba_shadow_postmarket_runner.py",
    "analysis/nba_shadow_model_integration.py",
    "analysis/nba_postcapture_crossplay_shadow.py",
    "analysis/nba_shadow_three_play_train.py",
    "analysis/nba_three_play_direction_shadow.py",
    "config/nba_shadow_three_play_params.json",
)
DENY_EXACT_FIELDS={
    "home_points","away_points","home_score","away_score",
    "final_home_points","final_away_points",
    "final_score_home","final_score_away",
    "actual_home_points","actual_away_points",
    "observed_home_win","observed_home_cover_open","observed_over_open",
    "settlement","settlement_result","winning_side",
    "score_observed_at_utc","score_observed_utc","finalized_at",
    "postgame_label","outcome_label","actual_winner",
}
DENY_FILES={
    "settlement.json","results.json","final_scores.json",
    "nba_shadow_direction_scorecard.json",
    "nba_shadow_candidate_paired_grade.json",
}
SOURCE_PAIRS=(
    ("1200","nba_market_consensus.json"),
    ("1800","nba_market_consensus.json"),
    ("1800","nba_dynamic_five_market_shadow.json"),
    ("1800","nba_five_market_forecast.json"),
)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def scan_no_result_labels(obj,path="$",depth=0):
    if depth>40:
        raise ValueError("SOURCE_DATA_NESTING_TOO_DEEP")
    if isinstance(obj,dict):
        for k,v in obj.items():
            if str(k).lower() in DENY_EXACT_FIELDS:
                raise ValueError("POSTGAME_OUTCOME_FIELD_IN_MODEL_INPUT:"+path+"."+str(k))
            scan_no_result_labels(v,path+"."+str(k),depth+1)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):
            scan_no_result_labels(v,path+"["+str(i)+"]",depth+1)

def stage(repo,daily_root,sent_root,stage_root,status_root,trigger_run=None,now=None):
    now=now or datetime.now(timezone.utc)
    base=Path(repo).resolve()
    target=Path(stage_root).resolve()
    if target==base or base in target.parents:
        raise ValueError("ISOLATED_PREDICTION_DIRECTORY_INSIDE_PRODUCTION_REPO")
    out=Path(status_root)
    out.mkdir(parents=True,exist_ok=True)
    state=RUN.gate(base/daily_root,base/sent_root,now,trigger_run)
    (out/"stage_status.json").write_text(json.dumps({
        **state,"schema_version":SCHEMA,"no_results_loaded":True,
        "production_model_changed":False},sort_keys=True,indent=2)+"\n")
    if state["status"]!="READY":
        print("NBA_PRETIP_AIRGAP_STAGE_SKIPPED",state["status"])
        return state
    if target.exists() and any(target.iterdir()):
        raise ValueError("ISOLATED_PREDICTION_DIRECTORY_MUST_BE_EMPTY")
    target.mkdir(parents=True,exist_ok=True)
    originals=list(ALLOWED_SOURCES)
    day=state["target_date"]
    for slot,filename in SOURCE_PAIRS:
        originals.append(str(Path(daily_root)/day/slot/filename))
    originals.append(str(Path(sent_root)/day/"1800.json"))
    digests={}
    for original in originals:
        source=(base/original)
        if source.is_symlink() or not source.is_file():
            raise ValueError("INPUT_SOURCE_MISSING_OR_SYMLINK:"+original)
        if source.stat().st_size>12_000_000:
            raise ValueError("UNBOUNDED_SHADOW_SOURCE_FILE:"+original)
        dest=target/original
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            raise ValueError("STAGE_PATH_COLLISION:"+original)
        dest.write_bytes(source.read_bytes())
        if original.endswith(".json"):
            parsed=json.loads(dest.read_text(encoding="utf-8"))
            scan_no_result_labels(parsed)
        digests[original]=sha(source)
        if sha(source)!=sha(dest):
            raise ValueError("INPUT_MUTATED_DURING_STAGE:"+original)
        dest.chmod(stat.S_IRUSR|stat.S_IRGRP|stat.S_IROTH)
    manifest={
        "schema_version":SCHEMA,
        "target_date":day,
        "accepted_original_production_run":state["original_delivery_marker_run"],
        "real_input_file_sha256":dict(sorted(digests.items())),
        "stage_created_utc":now.isoformat(),
        "network_access_in_prediction_container":False,
        "score_files_in_prediction_container":False,
        "history_training_datasets_in_prediction_container":False,
        "original_repository_not_mounted_in_prediction_container":True,
        "model_outputs_only_to_separate_mount":True,
        "denylisted_outcome_fields_in_input":sorted(DENY_EXACT_FIELDS),
    }
    f=target/"pretip_input_manifest.json"
    f.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    f.chmod(stat.S_IRUSR|stat.S_IRGRP|stat.S_IROTH)
    print("NBA_PRETIP_AIRGAP_STAGE_READY",json.dumps({
        "day":day,"source_file_count":len(originals),
        "original_run":state["original_delivery_marker_run"],
        "no_result_files":True,"input_manifest_sha256":sha(f)
    },ensure_ascii=False))
    return state

def selftest():
    from tempfile import TemporaryDirectory
    scan_no_result_labels({"games":[{"home_team":"A","final_signal_status":"PRETIP"}]})
    for data in ({"settlement":"HOME_WIN"},{"games":[{"final_home_points":115}]},
                 {"observed_home_win":1},{"score_observed_at_utc":"2026-11-03"}):
        try:scan_no_result_labels(data)
        except ValueError as ex:
            assert "POSTGAME_OUTCOME_FIELD_IN_MODEL_INPUT" in str(ex)
        else:raise AssertionError("OUTCOME_LABEL_ENTERED_PREDICTION")
    with TemporaryDirectory() as tmp:
        r=Path(tmp)
        (r/"repo").mkdir()
        try:stage(r/"repo","reports/daily","reports/pushplus-sent",
                  r/"repo"/"inside",r/"out")
        except ValueError as ex:assert "INSIDE_PRODUCTION" in str(ex)
        else:raise AssertionError("UNISOLATED_STAGE_ACCEPTED")
    print("NBA_PREDICTION_AIRGAP_ALLOWLIST_AND_LABEL_EXCLUSION_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo",default=".")
    p.add_argument("--daily-root",default="reports/daily")
    p.add_argument("--sent-root",default="reports/pushplus-sent")
    p.add_argument("--stage",default="/tmp/nba-shadow-airgap/stage")
    p.add_argument("--status-out",default="/tmp/nba-shadow-airgap/control")
    p.add_argument("--trigger-run",default=None)
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:selftest()
    else:stage(a.repo,a.daily_root,a.sent_root,a.stage,a.status_out,a.trigger_run)

if __name__=="__main__":main()
