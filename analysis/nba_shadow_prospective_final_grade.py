#!/usr/bin/env python3
"""Score the EARLIEST authenticated main-branch postmarket shadow (research).

GitHub artifacts are immutable frozen evidence: never reconstruct yesterday's
shadow after the outcome. This module verifies original workflow provenance,
timestamps, original capture input hashes, asof pretip source and official FINAL
before matching exact JC/Crown game/line for five-play Brier and hit rates.
NO PushPlus, NO write to main and NO promotion.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
from urllib.parse import quote
from urllib.request import Request,urlopen
from zipfile import ZipFile

import nba_shadow_model_integration as I

SCHEMA="nba-prospective-five-play-shadow-versus-original-v1"
MAX_BYTES=7_000_000
ARTIFACT_PREFIX="nba-new-prospective-five-play-shadow-"

def api(url,token,as_json=True):
    req=Request(url,headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"NBA-Genuine-Prospective-Shadow-Five-Play-Audit/1.0",
    })
    with urlopen(req,timeout=20) as r:
        data=r.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:raise ValueError("REMOTE_GITHUB_RESPONSE_TOO_LARGE")
    return json.loads(data) if as_json else data

def artifact_candidates(repo,token,day):
    url="https://api.github.com/repos/"+repo+"/actions/artifacts?per_page=100&name="+quote(
        ARTIFACT_PREFIX+day)
    result=api(url,token)
    rows=result.get("artifacts") or []
    if result.get("total_count",0)>100:
        raise ValueError("TOO_MANY_DUPLICATE_SHADOW_FREEZES")
    return sorted([r for r in rows if (
        r.get("name")==ARTIFACT_PREFIX+day and r.get("expired") is False)],
        key=lambda r:(r.get("created_at") or "",int(r.get("id",0))))

def decode_zip(blob):
    with ZipFile(BytesIO(blob)) as z:
        names=z.namelist()
        if len(names)>24 or sum(x.file_size for x in z.infolist())>MAX_BYTES:
            raise ValueError("SHADOW_ARTIFACT_ARCHIVE_OVERSIZED")
        files={}
        for name in ("auto_run_status.json","nba_shadow_model_bridge.json",
                     "nba_postmarket_independent_candidate.json"):
            members=[m for m in names if m==name or m.endswith("/"+name)]
            if len(members)!=1:
                raise ValueError("MISSING_OR_DUPLICATE_REQUIRED_SHADOW_EVIDENCE")
            files[name]=z.read(members[0])
        return files

def verify(meta,files,run,repo,day,ledger_root,now):
    status=json.loads(files["auto_run_status.json"])
    bridge=json.loads(files["nba_shadow_model_bridge.json"])
    candidate=json.loads(files["nba_postmarket_independent_candidate.json"])
    created=I.D.clock(meta.get("created_at"))
    predicted=I.D.clock(candidate.get("generated_at_utc"))
    started=I.D.clock(run.get("run_started_at") or run.get("created_at"))
    finished=I.D.clock(run.get("updated_at"))
    if (run.get("head_branch")!="main" or run.get("conclusion")!="success"
            or not str(run.get("path","")).startswith(
                ".github/workflows/nba-postmarket-shadow-auto.yml")
            or run.get("event") not in ("workflow_run","workflow_dispatch")):
        raise ValueError("UNTRUSTED_OR_NOT_COMPLETED_MAIN_SHADOW_JOB")
    if (not created or not predicted or not started or not finished or
            not started<=predicted<=finished or not predicted<=created):
        raise ValueError("SHADOW_GENERATION_TIMESTAMP_OUTSIDE_REAL_GITHUB_WORKFLOW")
    if status.get("status")!="NEW_INDEPENDENT_SHADOW_FROZEN_PRETIP":
        raise ValueError("SHADOW_ARCHIVE_IS_NOT_A_REAL_FROZEN_PREDICTION")
    if status.get("target_date")!=day or candidate.get("target_date")!=day or (
        bridge.get("target_date")!=day):
        raise ValueError("SHADOW_ORIGINAL_TARGET_DATE_MISMATCH")
    if not status.get("no_original_forecast_or_push_mutation") or (
        candidate.get("auto_promote_into_production") is not False):
        raise ValueError("SHADOW_HAS_LIVE_FUSION_OR_DELIVERY_SIDE_EFFECT")
    bridge_hash=hashlib.sha256(files["nba_shadow_model_bridge.json"]).hexdigest()
    candidate_hash=hashlib.sha256(files["nba_postmarket_independent_candidate.json"]).hexdigest()
    if (candidate.get("market_feature_source_sha256")!=bridge_hash or
            status.get("candidate_sha256")!=candidate_hash):
        raise ValueError("ORIGINAL_IMMUTABLE_ARTIFACT_HASH_MISMATCH")
    if candidate.get("model_probabilities_are_frozen") is not True:
        raise ValueError("UNFROZEN_PROSPECTIVE_CANDIDATE")
    # Never grade an artifact unless its original EXACT source inputs and
    # output were sealed in the independent append-only research Git branch.
    # This is a second, distinct proof of pretip existence (independent of
    # short-lived 90-day GitHub Action artifacts).
    root=Path(ledger_root)/day
    proof_path=root/".seal.json"
    if not proof_path.is_file():
        raise ValueError("NO_PERMANENT_PRETIP_GIT_LEDGER_SEAL_FOR_DAY")
    proof=json.loads(proof_path.read_text())
    if (proof.get("schema_version")!="nba-shadow-pretip-append-only-seal-v1"
            or proof.get("date_beijing")!=day
            or str(proof.get("new_shadow_github_run_id"))!=str(run["id"])):
        raise ValueError("LEDGER_SEAL_IS_NOT_FOR_THIS_FIRST_GITHUB_RUN")
    hashes=proof.get("frozen_blobs_sha256",{})
    for name,payload in files.items():
        if hashlib.sha256(payload).hexdigest()!=hashes.get(name):
            raise ValueError("LEDGER_OUTPUT_SHA256_DIFFERS_FROM_ARCHIVED_ARTIFACT:"+name)
        if not (root/name).is_file() or hashlib.sha256((root/name).read_bytes()).hexdigest()!=hashes[name]:
            raise ValueError("PERMANENT_FROZEN_FORECAST_FILE_TAMPERED:"+name)
    source_base=root/"input_snapshots/reports/daily"/day
    original_paths={
        "earlier_consensus":source_base/"1200"/"nba_market_consensus.json",
        "later_consensus":source_base/"1800"/"nba_market_consensus.json",
        "original_dynamic_five_market":source_base/"1800"/"nba_dynamic_five_market_shadow.json",
        "original_five_market_forecast":source_base/"1800"/"nba_five_market_forecast.json",
    }
    for key,path in original_paths.items():
        relative=str(path.relative_to(root))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=hashes.get(relative):
            raise ValueError("SEALED_SOURCE_SNAPSHOT_TAMPERED:"+key)
        if bridge.get("source_sha256",{}).get(key)!=hashes[relative]:
            raise ValueError("SEALED_SOURCE_DIFFERS_FROM_MODEL_FEATURES:"+key)
    marker_path=root/"input_snapshots/reports/pushplus-sent"/day/"1800.json"
    marker_hash=hashes.get(str(marker_path.relative_to(root)))
    if not marker_path.is_file() or hashlib.sha256(marker_path.read_bytes()).hexdigest()!=marker_hash:
        raise ValueError("ARCHIVED_REAL_PRODUCTION_ACCEPTANCE_MARKER_TAMPERED")
    marker=json.loads(marker_path.read_text())
    if (str(marker.get("run_id"))!=str(status.get("original_delivery_marker_run"))
            or str(marker.get("run_id"))!=str(proof.get("original_production_run_id"))
            or marker.get("state")!="API_ACCEPTED_NOT_DEVICE_CONFIRMED"):
        raise ValueError("INCORRECT_SUCCESSFUL_MAIN_CHAIN_SOURCE_RUN")
    sealed=I.D.clock(proof.get("sealed_at_utc"))
    earliest_tip=min((I.D.clock(g.get("tipoff_beijing")) for g in candidate.get("games",[])),
                    default=None)
    if not sealed or not earliest_tip or not sealed<earliest_tip:
        raise ValueError("GIT_LEDGER_WAS_WRITTEN_AFTER_NBA_GAME_START")
    if (proof.get("prediction_generated_at_utc")!=predicted.isoformat()
            or proof.get("original_model_forecast_sha256")!=bridge[
                "source_sha256"]["original_five_market_forecast"]):
        raise ValueError("SEALED_SOURCE_OR_MODEL_CLOCK_IDENTITY_CONFLICT")
    # Original frozen target board and newly calculated next model are checked
    # again in the grade path after scores are independently available.
    return bridge,candidate,{"github_run_id":run["id"],
                              "artifact_id":meta["id"],
                              "frozen_candidate_generated_at":predicted.isoformat(),
                              "artifact_created_utc":created.isoformat(),
                              "original_delivery_run_id":marker["run_id"],
                              "candidate_sha256":candidate_hash,
                              "bridge_sha256":bridge_hash}

def grade_day(repo,token,day,ledger_root,settled,now):
    settlement=Path(settled)/day/"settlement.json"
    if not settlement.is_file():
        return {"status":"SKIPPED_NO_OFFICIAL_COMPLETED_SETTLEMENT"}
    truth=json.loads(settlement.read_text())
    if truth.get("schema_version")!="nba-five-market-settlement-v1" or truth.get("beijing_date")!=day:
        raise ValueError("NOT_AN_INDEPENDENT_FIVE_PLAY_OFFICIAL_FINAL")
    candidates=artifact_candidates(repo,token,day)
    if not candidates:
        return {"status":"SKIPPED_NO_PRETIP_PROSPECTIVE_SHADOW_CAPTURE"}
    # Precommit EARLIEST genuine freeze of this game cohort, not an ex-post
    # selected best candidate or last model re-trained on outcomes.
    artifact=candidates[0]
    run_id=int(artifact.get("workflow_run",{}).get("id") or 0)
    if not run_id:raise ValueError("ORIGINAL_SHADOW_WORKFLOW_RUN_ID_MISSING")
    run=api("https://api.github.com/repos/"+repo+"/actions/runs/"+str(run_id),token)
    files=decode_zip(api(
        "https://api.github.com/repos/"+repo+"/actions/artifacts/"+str(artifact["id"])+"/zip",
        token,as_json=False))
    bridge,candidate,source=verify(artifact,files,run,repo,day,ledger_root,now)
    report=I.compare_candidate(
        bridge,candidate,truth,
        hashlib.sha256(files["nba_shadow_model_bridge.json"]).hexdigest())
    if report.get("independent_games",0)<1:
        return {"status":"SKIPPED_NO_SAME_GAME_INDEPENDENT_SCORE_PAIRS",
                "evidence":source,"paired_by_market":report.get("paired_by_market",{})}
    return {
        "schema_version":SCHEMA,"status":"FROZEN_TRUE_PROSPECTIVE_SHADOW_SCORED",
        "target_date":day,"from_authenticated_main_branch_github_workflow":True,
        "precommitted_selection":"EARLIEST_ARTIFACT_NO_OUTCOME_SELECTION",
        "original_and_candidate_same_game_same_direct_line":True,
        "source_evidence":source,
        "original_model_vs_new_shadow":report,
        "overweight_jingcai_vs_crown_scorecard_exposure":{"jingcai":0.7,"crown_id3":0.3},
        "not_new_moneyline_spread_total_production_accuracy_proof":True,
        "automatic_live_model_promotion":False,
        "never_change_scheduled_report_or_pushplus":True,
    }

def selftest():
    assert ARTIFACT_PREFIX.endswith("shadow-")
    assert I.equal(-7.5,-7.5) and not I.equal(-7.5,+7.5)
    assert I.D.clock("2026-11-02T10:00:00Z")<I.D.clock("2026-11-03T00:00:00Z")
    assert hashlib.sha256(b'foo').hexdigest()!=hashlib.sha256(b'bar').hexdigest()
    print("NBA_FROZEN_PROSPECTIVE_FIVE_PLAY_FINAL_GRADER_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo",default=os.environ.get("GITHUB_REPOSITORY","noki1022/mcp-sports-hub"))
    p.add_argument("--token",default=os.environ.get("GH_TOKEN"))
    p.add_argument("--date",help="Beijing date of the actual NBA games; default: today Beijing")
    p.add_argument("--daily-root",default="reports/daily")
    p.add_argument("--sent-root",default="reports/pushplus-sent")
    p.add_argument("--ledger-root",default="reports/shadow-pretip-ledger")
    p.add_argument("--settled-root",default="reports/five-market-settled")
    p.add_argument("--out",default="/tmp/nba-shadow-prospective-postgame-scorecard.json")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:selftest();return
    if not args.token:raise SystemExit("GH_TOKEN_WITH_ACTIONS_READ_REQUIRED")
    from zoneinfo import ZoneInfo
    target=args.date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    output=grade_day(args.repo,args.token,target,args.ledger_root,args.settled_root,
                     datetime.now(timezone.utc))
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print("NBA_007_NEW_SHADOW_REAL_POSTGAME_PERFORMANCE",
          json.dumps({"status":output["status"],
              "day":target,
              "paired_independent_games":output.get("original_model_vs_new_shadow",{}).get(
                  "independent_games",0),
              "by_market":output.get("original_model_vs_new_shadow",{}).get(
                  "paired_by_market",{}),
              "live_model_modified":False},ensure_ascii=False))
if __name__=="__main__":main()
