#!/usr/bin/env python3
"""Prospective acceptance: sealed pretip predictions vs later real results.

Never self-certify from development holdout. Game IDs, tipoff and SHA seal
must match. Missing/new outcomes are excluded, never backfilled as guesses.
"""
import argparse,csv,hashlib,json,math
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np

MIN_GAMES=300
START="2026-11-01T00:00:00+00:00"
def stamp(x):
    d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
    if not d.tzinfo:raise ValueError("NAIVE_TIME")
    return d.astimezone(timezone.utc)
def load(path):
    return json.loads(Path(path).read_text())
def valid(r):
    for key in ("game_id","tipoff_utc","predicted_at_utc","base_home_prob","injury_home_prob"):
        if key not in r:raise ValueError("MISSING_"+key)
    if stamp(r["predicted_at_utc"])>=stamp(r["tipoff_utc"]):raise ValueError("POST_TIP_PREDICTION")
    if stamp(r["tipoff_utc"])<stamp(START):raise ValueError("PRE_FREEZE_GAME")
    for k in ("base_home_prob","injury_home_prob"):
        p=float(r[k])
        if not math.isfinite(p) or not 0<p<1:raise ValueError("BAD_PROBABILITY")
    if r.get("research_only") is not True or r.get("candidate_sha256") is None:
        raise ValueError("UNSEALED_OR_FAKE_RESEARCH_ROW")
def verify(predictions,results,candidate_hash):
    raw=Path(predictions).read_bytes()
    rows=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if not rows:raise ValueError("NO_SEALED_FORECASTS")
    outcome=load(results)
    if not isinstance(outcome,dict) or not isinstance(outcome.get("games"),list):
        raise ValueError("BAD_REAL_RESULTS")
    scored={}
    for r in outcome["games"]:
        key=str(r.get("game_id",""))
        if not key or key in scored:raise ValueError("DUPLICATE_OR_NO_RESULT_ID")
        if str(r.get("official_result_status"))!="FINAL":continue
        h=r.get("home_points");a=r.get("away_points")
        if not all(isinstance(x,int) and x>=0 for x in (h,a)):continue
        scored[key]=(float(h>a),r.get("tipoff_utc"))
    seen=set();usable=[];rejected=defaultdict(int)
    for r in rows:
        k=str(r.get("game_id",""))
        if not k or k in seen:raise ValueError("DUPLICATE_PREDICTION")
        seen.add(k)
        if r.get("candidate_sha256")!=candidate_hash:raise ValueError("FROZEN_MODEL_CHANGED")
        # CSV Boolean must be explicit, never Python truthiness of "False".
        r["research_only"]=r.get("research_only")=="True"
        valid(r)
        if k not in scored:
            rejected["missing_official_final"]+=1;continue
        y,tip=scored[k]
        if tip and stamp(tip)!=stamp(r["tipoff_utc"]):
            raise ValueError("RESULT_FIXTURE_TIP_MISMATCH")
        usable.append((r,y))
    report={"sealed_prediction_file_sha256":hashlib.sha256(raw).hexdigest(),
            "total_sealed":len(rows),"scored_games":len(usable),
            "missing_results":dict(rejected),
            "historical_sample_reused":False,
            "stage":"PROSPECTIVE_INJURY_MONEYLINE",
            "status":"PENDING_MORE_PROSPECTIVE_FINAL_GAMES",
            "production_approved":False}
    if len(usable)<MIN_GAMES:return report
    p0=np.asarray([float(r["base_home_prob"]) for r,y in usable])
    p1=np.asarray([float(r["injury_home_prob"]) for r,y in usable])
    y=np.asarray([y for r,y in usable])
    loss=lambda p:(p-y)**2
    b0,b1=loss(p0),loss(p1)
    log=lambda p:-(y*np.log(p)+(1-y)*np.log(1-p))
    delta=b1-b0
    grouped=defaultdict(list)
    for i,(r,_) in enumerate(usable):grouped[stamp(r["tipoff_utc"]).date().isoformat()].append(i)
    days=sorted(grouped)
    rng=np.random.default_rng(20261031)
    samples=[]
    for z in range(1000):
        sampled=rng.integers(0,len(days),size=len(days))
        idx=[i for a in sampled for i in grouped[days[a]]]
        samples.append(float(delta[idx].mean()))
    lo,hi=np.quantile(samples,[.025,.975])
    report.update(base_Brier=float(np.mean(b0)),injury_Brier=float(np.mean(b1)),
                  base_LogLoss=float(np.mean(log(p0))),injury_LogLoss=float(np.mean(log(p1))),
                  injury_minus_base_Brier=float(np.mean(delta)),
                  paired_day_bootstrap_95CI=[float(lo),float(hi)],
                  n_calendar_day_clusters=len(days),
                  status="PROSPECTIVE_SCORE_COMPUTED_NOT_AUTO_PRODUCTION_PROMOTED")
    report["moneyline_accuracy_gate_pass"]=bool(hi<0 and report["injury_LogLoss"]<report["base_LogLoss"])
    report["production_approved"]=False  # publication / player impact / other gating separately required
    return report
def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/"pred.csv"
        with path.open("w",newline="") as o:
            writer=csv.DictWriter(o,fieldnames=["game_id","tipoff_utc","predicted_at_utc",
                 "base_home_prob","injury_home_prob","candidate_sha256","research_only"])
            writer.writeheader()
            writer.writerow({"game_id":"test1","tipoff_utc":"2026-11-01T01:00:00Z",
                "predicted_at_utc":"2026-11-01T00:30:00Z","base_home_prob":0.5,
                "injury_home_prob":0.6,"candidate_sha256":"frozen_hash","research_only":"True"})
        result=Path(d)/"result.json"
        result.write_text(json.dumps({"games":[{"game_id":"test1",
            "home_points":100,"away_points":99,"official_result_status":"FINAL",
            "tipoff_utc":"2026-11-01T01:00:00Z"}]}))
        t=verify(path,result,"frozen_hash")
        assert t["scored_games"]==1 and t["production_approved"] is False
        bad=path.read_text().replace("00:30:00Z","01:30:00Z")
        path.write_text(bad)
        try:verify(path,result,"frozen_hash")
        except ValueError as e:assert str(e)=="POST_TIP_PREDICTION"
        else:raise AssertionError("POSTTIP_SHOULD_FAIL")
        print("PROSPECTIVE_INJURY_ACCEPTANCE_FAIL_CLOSED_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    for a in ("predictions","results","candidate_sha256","out"):
        p.add_argument("--"+a.replace("_","-"))
    x=p.parse_args()
    if x.self_test:return selftest()
    if not all((x.predictions,x.results,x.candidate_sha256,x.out)):p.error("all input args required")
    out=verify(x.predictions,x.results,x.candidate_sha256)
    Path(x.out).write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out,indent=2))
if __name__=="__main__":main()
