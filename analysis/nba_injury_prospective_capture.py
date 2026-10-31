#!/usr/bin/env python3
"""Fail-closed pretip prospective injury shadow capture.

Never invents injury probabilities. A sealed matching replacement-model
candidate is required for paired scoring; until then only baseline and a
block reason are archived. Distinct first capture per game is immutable.
"""
import argparse,hashlib,json,math
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from nba_chronological_backtest import p_greater
from nba_independent_predictions import _isotonic_predict

def instant(x):
    d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("NAIVE_TIMESTAMP")
    return d.astimezone(timezone.utc)
def read(p):
    return json.loads(Path(p).read_text())
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def value(p):
    n=float(p)
    if not math.isfinite(n):raise ValueError("INVALID_PROBABILITY")
    return max(1e-7,min(1-1e-7,n))
def record(joined,model,inj,candidate_path,now,existing=None):
    if existing is None:existing={}
    games={str(x["game_id"]):x for x in model.get("games",[])}
    injured={str(x["game_id"]):x for x in inj.get("games",[])}
    candidate=read(candidate_path) if candidate_path and Path(candidate_path).is_file() else None
    candidate_digest=sha(candidate_path) if candidate else None
    if candidate:
        if candidate.get("schema_version")!="nba-injury-replacement-prospective-v1" or candidate.get("release_approved") is not False:
            raise ValueError("UNQUALIFIED_CANDIDATE")
    result=[]
    for fixture in joined.get("nba_cba_games",[]):
        if fixture.get("league")!="NBA":continue
        key=str(fixture["game_id"]);tip=instant(fixture["tipoff_utc"])
        if now>=tip:continue
        nba_id=str(fixture.get("nba_game_id") or "")
        if not nba_id.isdecimal():continue
        game=games.get(key);ctx=injured.get(key)
        if not game or game.get("model_status")!="OK" or game.get("model_probability",{}).get("home") is None:continue
        if not ctx:continue
        base=value(game["model_probability"]["home"])
        rec={"schema_version":"nba-injury-shadow-record-v1",
             "game_id":nba_id,"007_game_id":key,
             "home":fixture.get("home_team"),"away":fixture.get("away_team"),
             "tipoff_utc":tip.isoformat(),"predicted_at_utc":now.isoformat(),
             "base_home_prob":base,"injury_home_prob":None,
             "candidate_sha256":candidate_digest,
             "model_version":game.get("model_version"),
             "source_report_captured_at_utc":ctx.get("source_captured_at_utc"),
             "quality":ctx.get("quality"),"research_only":True,
             "status":"NO_FROZEN_REPLACEMENT_CANDIDATE" if not candidate else "BLOCKED_FEATURE_INCOMPATIBILITY"}
        if candidate:
            # Never extrapolate from name-only 2026 injury entries to
            # historic NBA person_id coefficients / replacement depth.
            if candidate.get("feature_schema")=="nba-id-current-team-prior-minutes-v1" and ctx.get("nba_person_id_join_verified") is True:
                # The full online feature service must explicitly supply its
                # as-of feature vector and the training-compatible schema.
                fields=ctx.get("replacement_pregame_features")
                if isinstance(fields,list) and len(fields)==len(candidate.get("coefficients",[])):
                    if instant(ctx["source_captured_at_utc"])<tip and all(math.isfinite(float(x)) for x in fields):
                        shift=sum(float(a)*float(b) for a,b in zip(fields,candidate["coefficients"]))
                        shift=max(-8.,min(8.,shift))
                        mu=float(game["margin_mean_home_minus_away"])+shift
                        sigma=float(game["margin_sigma"])
                        raw=p_greater(mu,sigma,0.)
                        rec["injury_home_prob"]=value(_isotonic_predict(candidate.get("moneyline_isotonic"),raw))
                        rec["status"]="PAIRED_SHADOW_CAPTURED"
                        rec["shadow_margin_delta"]=shift
        result.append(rec)
    return result
def capture(args):
    now=instant(args.captured_at_utc) if args.captured_at_utc else datetime.now(timezone.utc)
    if args.captured_at_utc and not args.test_mode:raise ValueError("CLOCK_OVERRIDE_NOT_ALLOWED")
    existing=read(args.out) if Path(args.out).exists() else {"games":[]}
    if existing.get("games"):
        # Never overwrite already sealed predictions or reassign game IDs.
        raise ValueError("SEALED_CAPTURE_ALREADY_EXISTS")
    games=record(read(args.joined),read(args.model),read(args.injuries),args.candidate,now)
    payload={"schema_version":"nba-injury-shadow-batch-v1",
             "captured_at_utc":now.isoformat(),"games":games,
             "paired_count":sum(g["status"]=="PAIRED_SHADOW_CAPTURED" for g in games),
             "nonproduction":True}
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    print("INJURY_SHADOW_CAPTURE",len(games),payload["paired_count"])
def selftest():
    now=instant("2026-11-01T00:00:00Z")
    joined={"nba_cba_games":[{"game_id":"123","nba_game_id":"401111111","league":"NBA",
            "tipoff_utc":"2026-11-01T02:00:00Z"}]}
    model={"games":[{"game_id":"123","model_status":"OK","model_probability":{"home":1.0}}]}
    inj={"games":[{"game_id":"123","quality":"PUBLISHED_AFFECTED","source_captured_at_utc":"2026-10-31T23:00:00Z"}]}
    rows=record(joined,model,inj,None,now)
    assert len(rows)==1 and rows[0]["base_home_prob"]<1 and rows[0]["injury_home_prob"] is None
    assert not record(joined,model,inj,None,instant("2026-11-01T02:01:00Z"))
    print("INJURY_PROSPECTIVE_PIT_CAPTURE_TEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("joined","model","injuries","candidate","out","captured_at_utc"):
        p.add_argument("--"+k.replace("_","-"))
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--test-mode",action="store_true")
    x=p.parse_args()
    if x.self_test:selftest()
    else:
        if not all((x.joined,x.model,x.injuries,x.out)):p.error("missing input")
        capture(x)
