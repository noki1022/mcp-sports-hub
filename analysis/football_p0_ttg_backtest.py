#!/usr/bin/env python3
"""P0 proper-scoring football total-goals distribution competition.

Inputs: original frozen 21:00 forecast + immutable per-match final + review
with ORIGINAL 007 FT response bytes. Never directly read odds or postgame
revised intensities. Production's original lambdas may already include bounded
Asian market assimilation; this study isolates only the distribution family,
not the causal value of bookmaker inputs. All grids share identical lambdas.
No auto-promotion. Holdout is strictly later than selection training period.
"""
from __future__ import annotations
import argparse
import gzip
import io
from zipfile import ZipFile
from datetime import datetime,timezone,timedelta
import json,math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_jc_final_2130 as final_2100
import sport_match_final_registry as registry
import sports_verified_review as verifier
import football_jc_prospective_score as ft

VERSION="football-p0-ttg-distribution-competition-v1"
CAP=16
CANDIDATES=("independent_poisson","dixon_coles_-0.08","dixon_coles_+0.08",
            "bivariate_0.10","bivariate_0.25")
MIN_TRAIN=80
MIN_HOLDOUT=40


def utc(value):
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("BACKTEST_TIMESTAMP_NAIVE")
    return d.astimezone(timezone.utc)


def poisson(lam,cap=CAP):
    if type(lam) not in (float,int) or not math.isfinite(lam) or not .05<=lam<=6:
        raise ValueError("INVALID_MODEL_LAMBDA")
    probs=[math.exp(-lam)]
    for k in range(1,cap+1):probs.append(probs[-1]*lam/k)
    return probs


def score_grid(home,away,candidate):
    if not .15<=home<=4.5 or not .15<=away<=4.5:
        raise ValueError("GOAL_INTENSITIES_OUT_OF_BOUNDS")
    if candidate not in CANDIDATES:raise ValueError("UNKNOWN_DISTRIBUTION")
    values={}
    if candidate.startswith("bivariate"):
        shared=float(candidate.rsplit("_",1)[1])
        if shared>=min(home,away):raise ValueError("INVALID_COMMON_GOAL_COMPONENT")
        h,a,joint=poisson(home-shared),poisson(away-shared),poisson(shared)
        for x in range(CAP+1):
            for y in range(CAP+1):
                values[x,y]=sum(h[x-k]*a[y-k]*joint[k] for k in range(min(x,y)+1))
    else:
        h,a=poisson(home),poisson(away)
        rho=0. if candidate=="independent_poisson" else float(candidate.split("_")[-1])
        for x in range(CAP+1):
            for y in range(CAP+1):
                tau=1.
                if x==0 and y==0:tau=1-home*away*rho
                elif x==0 and y==1:tau=1+home*rho
                elif x==1 and y==0:tau=1+away*rho
                elif x==1 and y==1:tau=1-rho
                if tau<=0:raise ValueError("NEGATIVE_DIXON_COLES_ADJUSTMENT")
                values[x,y]=h[x]*a[y]*tau
    total=sum(values.values())
    if total<=0 or not math.isfinite(total):raise ValueError("INVALID_GRID_MASS")
    bins=[0.]*8
    for (h,a),p in values.items():bins[min(7,h+a)]+=p/total
    if abs(sum(bins)-1)>1e-9:raise ValueError("TTG_NOT_NORMALIZED")
    return bins


def score(pr,y):
    if len(pr)!=8 or type(y) is not int or not 0<=y<=7:
        raise ValueError("INVALID_SCORE_INPUT")
    return {"log_loss":-math.log(max(1e-12,pr[y])),
            "brier":sum((p-(i==y))**2 for i,p in enumerate(pr)),
            "top1_hit":int(max(range(8),key=lambda i:pr[i])==y),
            "top2_hit":int(y in sorted(range(8),key=lambda i:-pr[i])[:2])}


def validated_samples(frozen,finals,reviews):
    """Admit only complete original-byte-backed scores and matched frozen file."""
    if frozen.get("schema_version")!="football-jc-single-final-2100-v1":
        raise ValueError("NOT_21_00_FROZEN_DOCUMENT")
    if frozen.get("final_forecast_sha256")!=final_2100.sha(frozen["forecast"]):
        raise ValueError("FROZEN_MODEL_HASH_MISMATCH")
    if frozen.get("model_version")!=frozen["forecast"]["model_version"]:
        raise ValueError("FROZEN_MODEL_VERSION_DRIFT")
    start=utc(frozen["actual_model_generated_utc"])
    facts={str(r["match_id"]):r for r in frozen.get("snapshot_facts",[])}
    cases=[]
    for row in frozen["forecast"]["games"]:
        mid=str(row["match_id"])
        if mid not in finals or mid not in reviews:continue
        locked,review=finals[mid],reviews[mid]
        verifier.verify(review,locked) # hashes and replays original compressed 007 FT bytes
        if locked["selection_rule"]!="ONLY_BEIJING_2100_IMMUTABLE_FORECAST":
            raise ValueError("NOT_FROZEN_21_00_SELECTION")
        if locked["forecast_sha256"]!=frozen["final_forecast_sha256"] or locked["source_snapshot_sha256"]!=frozen["source_snapshot_sha256"]:
            raise ValueError("FROZEN_PREDICTION_IDENTITY_MISMATCH")
        if locked["match_id"]!=mid or locked["jc_number"]!=row.get("jc_number"):
            raise ValueError("MATCH_ID_OR_JC_NUMBER_DRIFT")
        tip=utc(locked["kickoff_utc"])
        if not start<tip or utc(locked["generated_utc"])>=tip:
            raise ValueError("PRETIP_CUTOFF_VIOLATED")
        if locked["home_team"]!=row["home_team"] or locked["away_team"]!=row["away_team"]:
            raise ValueError("HOME_AWAY_FROZEN_DRIFT")
        if len(review.get("matches",[]))!=1 or review["matches"][0]["match_id"]!=mid:
            raise ValueError("REVIEW_MATCH_ID_DRIFT")
        actual=review["matches"][0].get("actual_score")
        if not isinstance(actual,dict):
            raise ValueError("NO_OFFICIAL_FT_RESULT")
        hg,ag=actual.get("home"),actual.get("away")
        if type(hg) is not int or type(ag) is not int or not (0<=hg<=25 and 0<=ag<=25):
            raise ValueError("INVALID_OFFICIAL_FT_GOALS")
        goal=row.get("goal_expectation") or {}
        h,a=goal.get("home"),goal.get("away")
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (h,a)):
            raise ValueError("MISSING_PREGAME_GOAL_EXPECTATION")
        observed=utc(review["result_evidence"]["observed_at_utc"])
        if observed<=tip+timedelta(minutes=90):
            raise ValueError("PREMATURE_FT_OBSERVATION")
        cases.append({"match_id":mid,"kickoff_utc":tip.isoformat(),
                      "frozen_model_sha256":locked["forecast_sha256"],
                      "verified_review_sha256":review["review_sha256"],
                      "home_lambda":float(h),"away_lambda":float(a),
                      "outcome_bucket":min(7,hg+ag)})
    return cases


def load_verified_2100_review(blob):
    """Original 21:00 archive + original 007 FT bytes, not inferred scores.

    Uses already-created official research grading release. Match identity,
    kickoff, team IDs, original result SHA and generated-before-kickoff are
    validated from the original 007 response.
    """
    if not isinstance(blob,bytes) or not 0<len(blob)<=2_000_000:
        raise ValueError("VERIFIED_REVIEW_ZIP_SIZE_INVALID")
    with ZipFile(io.BytesIO(blob)) as archive:
        names=set(archive.namelist())
        if "frozen-2100.json" not in names or "verified-results.json" not in names:
            raise ValueError("VERIFIED_REVIEW_REQUIRED_MEMBERS_MISSING")
        def member(path,cap):
            item=archive.getinfo(path)
            if item.file_size>cap:
                raise ValueError("VERIFIED_REVIEW_MEMBER_TOO_LARGE")
            return archive.read(item)
        locked=json.loads(member("frozen-2100.json",2_000_000))
        payload=json.loads(member("verified-results.json",2_000_000))
        if locked.get("schema_version")!="football-jc-single-final-2100-v1" or (
            locked.get("final_forecast_sha256")!=final_2100.sha(locked["forecast"])):
            raise ValueError("INVALID_ORIGINAL_2100_FORECAST_HASH")
        if locked.get("source_snapshot_sha256")!=locked["forecast"].get("source_sha256"):
            raise ValueError("FROZEN_007_SOURCE_HASH_DRIFT")
        raw={}
        for result in payload.get("results") or []:
            mid=str(result.get("match_id") or "")
            if not mid.isdecimal() or len(mid)>12 or mid in raw:
                raise ValueError("DUPLICATE_OR_INVALID_VERIFIED_RESULT_ID")
            filename=f"raw/{mid}.html.gz"
            if filename not in names:raise ValueError("MISSING_ORIGINAL_007_FT_RESPONSE")
            original=member(filename,900_000)
            with gzip.GzipFile(fileobj=io.BytesIO(original)) as stream:
                raw[mid]=stream.read(850001)
            if len(raw[mid])>850000:
                raise ValueError("OVERSIZE_ORIGINAL_007_RESULT")
        finals=ft.validate_results(payload,raw)
    return locked, finals


def validated_2100_review_archive(blob):
    locked, finals = load_verified_2100_review(blob)
    facts={str(g["match_id"]):g for g in locked["snapshot_facts"]}
    if len(facts)!=len(locked["snapshot_facts"]):
        raise ValueError("DUPLICATE_21_00_FIXTURE")
    asof=utc(locked["actual_model_generated_utc"])
    output=[]
    for row in locked["forecast"]["games"]:
        mid=str(row["match_id"])
        if mid not in finals:continue
        fact=facts.get(mid)
        if fact is None or row.get("jc_number")!=fact.get("jc_number"):
            raise ValueError("FROZEN_007_IDENTITY_MISMATCH")
        result=finals[mid]
        ft.verify_join({
          "match_id":mid,"jc_number":fact["jc_number"],
          "kickoff_beijing":fact["kickoff_beijing"],
          "home_team_id_007":fact["home_team_id_007"],
          "away_team_id_007":fact["away_team_id_007"]},result,asof)
        if row.get("status")!="RESEARCH_READY":
            continue
        goal=row.get("goal_expectation") or {}
        h,a=goal.get("home"),goal.get("away")
        if type(h) not in (int,float) or type(a) not in (int,float):
            continue
        if not all(math.isfinite(v) and .15<=v<=4.5 for v in (h,a)):
            continue
        tip=utc(fact["kickoff_beijing"])
        if utc(locked["actual_capture_utc"])>=tip or asof>=tip:
            raise ValueError("FROZEN_FORECAST_NOT_PRETIP")
        output.append({
            "match_id":mid,"kickoff_utc":tip.isoformat(),
            "frozen_model_sha256":locked["final_forecast_sha256"],
            "verified_review_sha256":result["source_sha256"],
            "home_lambda":float(h),"away_lambda":float(a),
            "outcome_bucket":min(7,result["home_goals"]+result["away_goals"])})
    return output


def paired_eval(examples):
    seen=set();data=[]
    for row in examples:
        mid=str(row["match_id"])
        if mid in seen:raise ValueError("DUPLICATE_VERIFIED_GAME")
        seen.add(mid)
        t=utc(row["kickoff_utc"])
        for k in ("frozen_model_sha256","verified_review_sha256"):
            if not isinstance(row.get(k),str) or len(row[k])!=64:
                raise ValueError("MISSING_HASH_BOUND_GAME")
        y=row["outcome_bucket"]
        data.append((t,mid,float(row["home_lambda"]),float(row["away_lambda"]),y))
    data.sort(key=lambda x:(x[0],x[1]))
    report={"schema_version":VERSION,"total_verified_fixtures":len(data),
      "market_prices_directly_read_by_benchmark":False,
      "pregame_lambdas_may_already_include_bounded_market_assimilation":True,
      "same_pregame_intensities_for_all_candidates":True,
      "candidate_metrics":{},"promotion_approved":False,
      "production_weights_modified":False}
    results={c:[] for c in CANDIDATES}
    for _,mid,h,a,y in data:
        for c in CANDIDATES:
            try:p=score_grid(h,a,c)
            except ValueError:continue
            results[c].append((mid,score(p,y)))
    for c,rows in results.items():
        report["candidate_metrics"][c]={"n":len(rows),
            **{key:round(sum(r[key] for _,r in rows)/len(rows),6) if rows else None
               for key in ("log_loss","brier","top1_hit","top2_hit")}}
    if len(data)<MIN_TRAIN+MIN_HOLDOUT:
        report["status"]="INSUFFICIENT_PROSPECTIVE_BLIND_SAMPLE"
        report["missing_to_120"]=max(0,MIN_TRAIN+MIN_HOLDOUT-len(data))
        report["selected_candidate"]=None
        return report
    # Candidate selection sees only chronological training cases. The
    # untouched holdout is used solely to verify generalisation.
    n_train=len(data)-max(MIN_HOLDOUT,int(len(data)*.25))
    train=data[:n_train]
    test=data[n_train:]
    if (test[0][0]-train[-1][0]).total_seconds()<3*3600:
        report.update(status="INSUFFICIENT_TIME_GAP_AT_HOLDOUT_BOUNDARY",selected_candidate=None)
        return report
    scores={}
    for c in CANDIDATES:
        valid=[]
        for _,_,h,a,y in train:
            try:valid.append(score(score_grid(h,a,c),y)["log_loss"])
            except ValueError:pass
        if len(valid)!=len(train):continue
        scores[c]=sum(valid)/len(valid)
    if "independent_poisson" not in scores:
        report.update(status="BASELINE_NOT_SCORABLE",selected_candidate=None)
        return report
    winner=min(scores,key=scores.get)
    holdout={}
    for c in (winner,"independent_poisson"):
        losses=[]
        for _,_,h,a,y in test:
            try:losses.append(score(score_grid(h,a,c),y)["log_loss"])
            except ValueError:pass
        holdout[c]={"n":len(losses),"mean_log_loss":round(sum(losses)/len(losses),6) if losses else None}
    report.update({"status":"RESEARCH_HOLDOUT_EVALUATED_NO_AUTO_PROMOTION",
                   "train_n":len(train),"holdout_n":len(test),
                   "selected_candidate":winner,
                   "selection_training_only":True,
                   "holdout":holdout,
                   "auto_promote":False})
    return report


def main():
    parser=argparse.ArgumentParser(description="Verified 21:00 FT total goal competition only")
    parser.add_argument("--frozen")
    parser.add_argument("--final-dir")
    parser.add_argument("--review-dir")
    parser.add_argument("--review-2100-zip")
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    if args.review_2100_zip:
        if any((args.frozen,args.final_dir,args.review_dir)):
            parser.error("CHOOSE_ONLY_ONE_VERIFIED_EVIDENCE_MODE")
        examples=validated_2100_review_archive(Path(args.review_2100_zip).read_bytes())
    else:
        if not all((args.frozen,args.final_dir,args.review_dir)):
            parser.error("MISSING_ORIGINAL_FROZEN_AND_REVIEW_FILES")
        def files(folder,suffix):
            return {p.name.split(".")[0].removeprefix("football-"):json.loads(p.read_text())
                    for p in Path(folder).glob("*"+suffix)}
        frozen=json.loads(Path(args.frozen).read_text())
        examples=validated_samples(frozen,files(args.final_dir,".final.json"),files(args.review_dir,".review.json"))
    out=paired_eval(examples)
    target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print("FOOTBALL_P0_TTG_BACKTEST",json.dumps({"n":len(examples),"status":out["status"]}))


if __name__=="__main__":main()
