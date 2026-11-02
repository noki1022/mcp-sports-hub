#!/usr/bin/env python3
"""Append-once research freeze to isolated Git evidence branch.

Invoked ONLY by a separate post-inference archive GitHub job with write
permission. No model inference or postgame scoring in this process. The first
valid frozen prediction for a Beijing game date is uniquely sealed; reruns
cannot overwrite it. Git commit SHA + independently captured source hashes
make tampering detectable, not mathematically impossible without branch rules.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import shutil

SCHEMA="nba-shadow-pretip-append-only-seal-v1"
INCLUDED=(
    "auto_run_status.json",
    "nba_shadow_model_bridge.json",
    "nba_postmarket_independent_candidate.json",
    "pretip_input_manifest.json",
)
REQUIRED_SNAPSHOTS=(
    ("1200","nba_market_consensus.json"),
    ("1800","nba_market_consensus.json"),
    ("1800","nba_dynamic_five_market_shadow.json"),
    ("1800","nba_five_market_forecast.json"),
)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def clock(value):
    if not isinstance(value,str):return None
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:return None

def seal(input_root,ledger_root,day,run_id,source_commit,now):
    src=Path(input_root)
    dest=Path(ledger_root)/day
    if dest.exists():
        raise ValueError("APPEND_ONLY_FROZEN_COHORT_ALREADY_EXISTS_NO_OVERWRITE")
    if not day or len(day)!=10 or not run_id.isdecimal() or len(source_commit)!=40:
        raise ValueError("INVALID_LEDGER_COMMIT_RUN_OR_DATE_ID")
    documents={}
    for filename in INCLUDED:
        path=src/filename
        if not path.is_file() or path.is_symlink():
            raise ValueError("FROZEN_PREDICTION_REQUIRED_INPUT_NOT_PRESENT:"+filename)
        documents[filename]=load(path)
    status=documents["auto_run_status.json"]
    bridge=documents["nba_shadow_model_bridge.json"]
    candidate=documents["nba_postmarket_independent_candidate.json"]
    manifest=documents["pretip_input_manifest.json"]
    if status.get("status")!="NEW_INDEPENDENT_SHADOW_FROZEN_PRETIP":
        raise ValueError("NO_PRETIP_PREDICTION_IS_AVAILABLE_TO_ARCHIVE")
    if any(r.get("target_date")!=day for r in (status,bridge,candidate,manifest)):
        raise ValueError("RESEARCH_FROZEN_DAY_MISMATCH")
    if (status.get("candidate_sha256")!=sha(src/"nba_postmarket_independent_candidate.json")
            or candidate.get("market_feature_source_sha256")!=sha(src/"nba_shadow_model_bridge.json")):
        raise ValueError("SHADOW_FROZEN_CANDIDATE_AND_FEATURE_HASH_CONFLICT")
    if (candidate.get("auto_promote_into_production") is not False
            or candidate.get("model_probabilities_are_frozen") is not True
            or status.get("no_original_forecast_or_push_mutation") is not True):
        raise ValueError("MODEL_ARTIFACT_NOT_INDEPENDENT_PRODUCTION_SAFE")
    if (manifest.get("schema_version")!="nba-five-play-pretip-container-allowlist-v1"
            or manifest.get("score_files_in_prediction_container") is not False
            or manifest.get("network_access_in_prediction_container") is not False):
        raise ValueError("PREDICTION_NOT_GENERATED_IN_RESULT_FREE_AIRGAP")
    if (str(status.get("original_delivery_marker_run"))!=str(
            manifest.get("accepted_original_production_run"))):
        raise ValueError("ORIGINAL_PRODUCTION_RUN_TRACE_MISMATCH")
    predicted=clock(candidate.get("generated_at_utc"))
    if not predicted or not predicted<now:
        raise ValueError("PREDICTION_TIME_NOT_BEFORE_GIT_ARCHIVE")
    for g in candidate.get("games",[]):
        tip=clock(g.get("tipoff_beijing"))
        observed=clock(g.get("market_feature_capture_utc"))
        if not tip or not observed or not observed<=predicted<tip:
            raise ValueError("PREDICTION_NOT_BEFORE_TIP_OR_FEATURE_TIME")
    if len(candidate.get("games",[]))<1:
        raise ValueError("EMPTY_NEW_FROZEN_MODEL")
    # Full source snapshots are physically archived alongside the output.
    rawpaths=[]
    for slot,name in REQUIRED_SNAPSHOTS:
        rel=f"input_snapshots/reports/daily/{day}/{slot}/{name}"
        rawpaths.append(rel)
    marker=f"input_snapshots/reports/pushplus-sent/{day}/1800.json"
    rawpaths.append(marker)
    params="input_snapshots/config/nba_shadow_three_play_params.json"
    rawpaths.append(params)
    for rel in rawpaths:
        p=src/rel
        if not p.is_file() or p.is_symlink():raise ValueError("MISSING_FROZEN_RAW_PRETIP_INPUT:"+rel)
        j=load(p)
        if any(k in j for k in ("observed_home_win","final_home_points",
                                "final_score_home","settlement","outcome_label")):
            raise ValueError("OUTCOME_LABEL_FOUND_IN_PRETIP_INPUT")
    orig_sha=manifest["real_input_file_sha256"]
    for slot,name in REQUIRED_SNAPSHOTS:
        key=f"reports/daily/{day}/{slot}/{name}"
        if orig_sha.get(key)!=sha(src/"input_snapshots"/key):
            raise ValueError("PRETIP_INPUT_CHANGED_AFTER_MODEL_RUN:"+key)
    dest.mkdir(parents=True)
    hashes={}
    for file in list(INCLUDED)+rawpaths:
        inp=src/file
        out=dest/file
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(inp.read_bytes())
        hashes[file]=sha(out)
    proof={
        "schema_version":SCHEMA,"date_beijing":day,
        "new_shadow_github_run_id":run_id,
        "original_production_run_id":status["original_delivery_marker_run"],
        "model_source_commit_sha":source_commit,
        "sealed_at_utc":now.isoformat(),
        "prediction_generated_at_utc":predicted.isoformat(),
        "original_model_forecast_sha256":bridge["source_sha256"][
            "original_five_market_forecast"],
        "frozen_blobs_sha256":dict(sorted(hashes.items())),
        "numerical_forecast_change_not_live_deployed":True,
        "no_result_or_settlement_file_in_input":True,
        "archive_is_append_only_by_game_date":True,
        "underlying_git_commit_and_branch_must_be_audited":True,
    }
    (dest/".seal.json").write_text(json.dumps(proof,indent=2,sort_keys=True)+"\n")
    print("NBA_PRETIP_GIT_APPEND_ONLY_SEALED",json.dumps({
        "day":day,"run_id":run_id,"input_and_forecast_files":len(hashes),
        "first_prediction_generated":predicted.isoformat(),
        "no_results":True},sort_keys=True))
    return proof

def selftest():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        target=Path(d)/"existing"
        target.mkdir()
        try:seal(Path(d),target.parent,"existing","42","a"*40,
                 datetime.now(timezone.utc))
        except ValueError as e:assert "ALREADY_EXISTS" in str(e)
        else:raise AssertionError("FROZEN_FORECAST_OVERWRITE_ALLOWED")
    print("NBA_PRETIP_GIT_APPEND_ONCE_SEAL_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=False)
    p.add_argument("--ledger-root",default="reports/shadow-pretip-ledger")
    p.add_argument("--day",required=False)
    p.add_argument("--github-run",required=False)
    p.add_argument("--source-commit",required=False)
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:selftest();return
    if not all((a.source,a.day,a.github_run,a.source_commit)):
        raise SystemExit("REQUIRES_REAL_FROZEN_ARTIFACT_GIT_RUN_SOURCE")
    seal(a.source,a.ledger_root,a.day,a.github_run,a.source_commit,
         datetime.now(timezone.utc))

if __name__=="__main__":main()
