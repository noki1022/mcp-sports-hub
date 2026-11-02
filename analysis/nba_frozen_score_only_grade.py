#!/usr/bin/env python3
"""Grade an immutable GitHub Actions pre-tip NBA score-only forecast artifact.

Requires the artifact manifest SHA and source capture/tipoff proof. Settles only
completed ESPN finals matching exactly the original event ID, home, away and
UTC tipoff. No retrospective odds, invented outcomes, probability overwrites,
or writes to original forecast snapshot. Research only.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import math
from pathlib import Path

import historical_odds_validator as H
import nba_multibook_asof_settled_ledger as E

MAX_DATES=5
SCHEMA="nba-frozen-score-only-final-grade-v1"

def original(input_jsonl,manifest_path):
    path=Path(input_jsonl);artifact=Path(manifest_path)
    raw=path.read_bytes()
    manifest=json.loads(artifact.read_text(encoding="utf-8"))
    if sha256(raw).hexdigest()!=manifest["predictions_sha256"]:
        raise RuntimeError("IMMUTABLE_PRETIP_ARTIFACT_CHECKSUM_MISMATCH")
    if (manifest.get("future_game_outcomes_used_to_train") is not False or
        manifest.get("production_push_model_changed") is not False or
        manifest.get("auto_promotion") is not False):
        raise RuntimeError("INELIGIBLE_ARTIFACT_PROVENANCE")
    rows=[json.loads(s) for s in raw.decode("utf-8").splitlines() if s]
    if not rows or len(rows)!=manifest["valid_future_games"]:
        raise RuntimeError("PRETIP_ROW_COUNT_DISAGREEMENT")
    ids=set()
    for r in rows:
        eid=str(r["nba_game_id"])
        tip=H.dt(r["tipoff_utc"])
        capture=H.dt(r["capture_utc"])
        if (not eid or eid in ids or tip-capture<timedelta(minutes=10) or
            capture!=H.dt(manifest["captured_at_utc"]) or
            r.get("last_completed_input_date_et")>=r["date_et"]):
            raise RuntimeError("INVALID_OR_REPEATED_PRETIP_FORECAST")
        ids.add(eid)
        p=float(r["predicted_home_win_probability"])
        if not math.isfinite(p) or not 0<p<1:
            raise RuntimeError("INVALID_FROZEN_PROBABILITY")
        for k in ("predicted_home_margin","predicted_game_total"):
            if not math.isfinite(float(r[k])):
                raise RuntimeError("INVALID_FROZEN_SCORE_VALUE")
    return rows,manifest

def settlement(rows,now=None,provider=E.fetch_espn_day):
    now=now or datetime.now(timezone.utc)
    days=sorted({r["date_et"] for r in rows})
    if len(days)>MAX_DATES:
        raise RuntimeError("SCOREBOARD_DAY_BOUND_EXCEEDED")
    known={}
    conflicts=set()
    fetched=[]
    failures=[]
    for s in days:
        d=datetime.fromisoformat(s).date()
        try:
            url,doc,digest=provider(d)
            finals,rejected=E.parse_espn(doc,url,now.isoformat().replace("+00:00","Z"))
            fetched.append({"date_et":s,"source_url":url,"source_sha256":digest,
                            "completed_rows":len(finals),"rejections":dict(rejected)})
            for f in finals:
                eid=str(f["espn_event_id"])
                if eid in known:
                    conflicts.add(eid)
                else:known[eid]=f
        except (OSError,ValueError,KeyError,TimeoutError,TypeError) as err:
            failures.append({"date_et":s,"error":type(err).__name__})
    for bad in conflicts:known.pop(bad,None)
    scored=[];statuses=Counter()
    for r in rows:
        eventid=r["nba_game_id"];tip=H.dt(r["tipoff_utc"])
        item={
            "nba_game_id":eventid,"home":r["home"],"away":r["away"],
            "frozen_capture_utc":r["capture_utc"],
            "frozen_home_probability":r["predicted_home_win_probability"],
            "frozen_margin":r["predicted_home_margin"],
            "frozen_total":r["predicted_game_total"],
            "tipoff_utc":r["tipoff_utc"],
        }
        if now<tip+timedelta(minutes=120):
            item["status"]="PENDING_NOT_SENSIBLY_FINISHED"
        else:
            final=known.get(str(eventid))
            if final is None:
                item["status"]="UNSETTLED_NO_COMPLETED_ESPN_EVENT"
            elif (final["home"]!=r["home"] or final["away"]!=r["away"] or
                  abs((H.dt(final["score_tip_utc"])-tip).total_seconds())>10800):
                item["status"]="QUARANTINED_EVENT_OR_TEAM_CONFLICT"
            else:
                hp,ap=int(final["home_points"]),int(final["away_points"])
                margin=hp-ap;total=hp+ap
                outcome=int(margin>0)
                p=float(r["predicted_home_win_probability"])
                item.update({
                    "status":"SCORED","home_points":hp,"away_points":ap,
                    "margin_actual":margin,"total_actual":total,
                    "home_win_actual":outcome,
                    "home_win_correct":int((p>=.5)==bool(outcome)),
                    "brier":(p-outcome)**2,
                    "logloss":-math.log(p if outcome else 1-p),
                    "margin_abs_error":abs(float(r["predicted_home_margin"])-margin),
                    "total_abs_error":abs(float(r["predicted_game_total"])-total),
                    "final_source":final["score_source"],
                    "final_score_observed_utc":final["score_collected_utc"],
                })
        statuses[item["status"]]+=1
        scored.append(item)
    complete=[r for r in scored if r["status"]=="SCORED"]
    average=lambda k:sum(r[k] for r in complete)/len(complete) if complete else None
    summary={
        "schema_version":SCHEMA,
        "asof_settlement_utc":now.isoformat().replace("+00:00","Z"),
        "frozen_games":len(rows),
        "completed_safely_scored":len(complete),
        "status_counts":dict(sorted(statuses.items())),
        "home_win_accuracy":average("home_win_correct"),
        "home_win_brier":average("brier"),
        "home_win_logloss":average("logloss"),
        "margin_MAE":average("margin_abs_error"),
        "total_MAE":average("total_abs_error"),
        "ESPN_source_evidence":fetched,
        "ESPN_source_fetch_failures":failures,
        "preserved_original_probabilities":True,
        "no_live_007_market_or_push_change":True,
        "no_auto_model_promotion":True,
    }
    return scored,summary

def run(input_jsonl,manifest,out):
    rows,original_manifest=original(input_jsonl,manifest)
    settled,summary=settlement(rows)
    summary["original_forecast_sha256"]=original_manifest["predictions_sha256"]
    target=Path(out);target.mkdir(parents=True,exist_ok=True)
    (target/"frozen_forecast_graded.json").write_text(json.dumps(
        {"summary":summary,"per_game":settled},ensure_ascii=False,
        indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("NBA_GENUINE_PRETIP_FROZEN_SCORE_GRADE",json.dumps({
        "original_forecast_sha256":summary["original_forecast_sha256"],
        "games":summary["frozen_games"],
        "complete":summary["completed_safely_scored"],
        "counts":summary["status_counts"],
        "ML_accuracy":summary["home_win_accuracy"],
        "ML_Brier":summary["home_win_brier"],
        "margin_MAE":summary["margin_MAE"],
        "total_MAE":summary["total_MAE"],
    },ensure_ascii=False))
    return summary

def selftest():
    now=datetime(2026,11,3,18,tzinfo=timezone.utc)
    future={"nba_game_id":"test-7","home":"UTA","away":"POR",
            "date_et":"2026-11-02",
            "tipoff_utc":"2026-11-03T00:00:00Z",
            "capture_utc":"2026-11-02T04:00:00Z",
            "predicted_home_win_probability":.4,
            "predicted_home_margin":-5.0,
            "predicted_game_total":223.5}
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        directory=Path(folder)
        originalpath=directory/"pred.jsonl"
        raw=json.dumps({**future,"last_completed_input_date_et":"2026-10-31"})+"\n"
        originalpath.write_text(raw)
        audit={"predictions_sha256":sha256(raw.encode()).hexdigest(),
               "future_game_outcomes_used_to_train":False,
               "production_push_model_changed":False,
               "auto_promotion":False,"valid_future_games":1,
               "captured_at_utc":"2026-11-02T04:00:00Z"}
        artifact=directory/"manifest.json"
        artifact.write_text(json.dumps(audit))
        saved,meta=original(originalpath,artifact)
        assert len(saved)==1
        originalpath.write_text(raw.replace('"home":"UTA"','"home":"BOS"'))
        try:original(originalpath,artifact)
        except RuntimeError as err:
            assert str(err)=="IMMUTABLE_PRETIP_ARTIFACT_CHECKSUM_MISMATCH"
        else:raise AssertionError("CHANGED_FROZEN_FORECAST_NOT_REJECTED")
        originalpath.write_text(raw)
    def sample(d):
        return "https://example.invalid/test",{"events":[{
          "id":"test-7","date":"2026-11-03T00:00:00Z",
          "status":{"type":{"completed":True}},
          "competitions":[{"competitors":[
             {"homeAway":"home","team":{"displayName":"Utah Jazz"},"score":"100"},
             {"homeAway":"away","team":{"displayName":"Portland Trail Blazers"},"score":"113"}
          ]}]
        }]},"test-hash"
    graded,summary=settlement([future],now,sample)
    assert summary["completed_safely_scored"]==1
    assert graded[0]["home_win_correct"]==1 and graded[0]["margin_abs_error"]==8.
    changed=[{**future,"away":"BOS"}]
    graded,summary=settlement(changed,now,sample)
    assert summary["completed_safely_scored"]==0
    assert graded[0]["status"]=="QUARANTINED_EVENT_OR_TEAM_CONFLICT"
    early,meta=settlement([future],datetime(2026,11,3,1,tzinfo=timezone.utc),sample)
    assert meta["completed_safely_scored"]==0
    print("NBA_FROZEN_GENUINE_SCORECARD_INTEGRITY_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input")
    p.add_argument("--manifest")
    p.add_argument("--out",default="/tmp/nba-frozen-score-only-grade")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:selftest()
    else:
        if not args.input or not args.manifest:
            p.error("--input and --manifest required")
        run(args.input,args.manifest,args.out)
