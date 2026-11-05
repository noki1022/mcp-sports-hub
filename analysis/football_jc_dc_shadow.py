#!/usr/bin/env python3
"""Standalone football-only Dixon-Coles shadow candidate using timestamped 007.

Research code inspired by the publicly documented Dixon-Coles approach in
MIT-licensed penaltyblog (martineastwood) and dixon-coles (callumfm).
This is a clean-room standard mathematical implementation; no external
runtime package, changes to NBA/CBA, or automatic PushPlus actions.

Do not confuse an experimental, time-split likelihood with a demonstrated
prospective betting return. Source prices are not training features.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import football_007_analysis_extract as source
import football_jc_probability as baseline

UTC=timezone.utc
VERSION="football-dixon-coles-shadow-v1"
MAX_GOALS=15
RHO_GRID=(-0.12,-0.08,-0.04,0.0,0.04,0.08,0.12)
HISTORY_DAYS=420
HALF_LIFE_DAYS=180
MIN_TRAIN_MATCHES=80
MIN_TEAM_GAMES=4
MIN_VALIDATION_GAMES=40
GOALS_LABELS=tuple([f"{i}球" for i in range(7)]+["7+球"])
OUTCOMES=("主胜","平","客胜")
HANDICAP_OUTCOMES=("让胜","让平","让负")

def parsed_at(value):
    return baseline.when(value)

def valid_goals(value):
    return type(value) is int and 0<=value<=25

def history_from_json(data, cutoff, horizon_days=HISTORY_DAYS):
    """Deduplicate only completed historical matches by 007 ID, both team lists.

    A reported matchTime is its kickoff, not final whistle: exclude the 3-hour
    window before the capture boundary to avoid in-progress scores.
    """
    if not isinstance(data,dict):
        raise ValueError("INVALID_007_ANALYSIS_JSON")
    near=data.get("nearMatches")
    if not isinstance(near,dict):
        return []
    observed={}
    for field in ("homeMatches","awayMatches"):
        group=near.get(field)
        if not isinstance(group,dict):
            continue
        for item in (group.get("matches") or [])[:100]:
            if not isinstance(item,dict):
                continue
            match_id=str(item.get("id") or "")
            if not match_id.isdigit() or len(match_id)>12:
                continue
            try:
                t=datetime.fromtimestamp(int(item["matchTime"]),UTC)
            except (ValueError,OverflowError,TypeError,KeyError):
                continue
            lag=(cutoff-t).total_seconds()
            if lag < 3*3600 or lag > horizon_days*86400:
                continue
            home=item.get("homeTeam")
            away=item.get("awayTeam")
            if not isinstance(home,dict) or not isinstance(away,dict):
                continue
            hid=str(home.get("id") or "")
            aid=str(away.get("id") or "")
            hg=home.get("score")
            ag=away.get("score")
            if not hid.isdigit() or not aid.isdigit() or hid==aid:
                continue
            if not valid_goals(hg) or not valid_goals(ag):
                continue
            row={"match_id":match_id,"played_at_utc":t.isoformat(),
                 "home_id":hid,"away_id":aid,"home_goals":hg,"away_goals":ag}
            if match_id in observed and observed[match_id]!=row:
                # Contradictory snapshots of a completed event are unsuitable.
                observed[match_id]=None
            elif match_id not in observed:
                observed[match_id]=row
    return [r for r in observed.values() if r is not None]

def collect_historical(snapshot,raw_dir):
    cutoff=parsed_at(snapshot["captured_at_utc"])
    games=snapshot.get("games") or []
    data={}
    counts={"analysis_read":0,"analysis_failed":0,"duplicate_matches":0,
            "conflicting_matches":0,"historical_matches":0}
    for g in games:
        mid=str(g.get("match_id") or "")
        # Only analysis pages reported as successfully validated by the 007
        # acquisition chain can provide training rows.
        if g.get("analysis_source_status")!="007_EMBEDDED_JSON_VALIDATED":
            continue
        file=Path(raw_dir)/f"analysis_{mid}.html.gz"
        try:
            raw=gzip.decompress(file.read_bytes())
            if len(raw)>source.MAX_HTML:raise ValueError("ANALYSIS_TOO_LARGE")
            evidence=g.get("analysis_source_evidence") or {}
            if hashlib.sha256(raw).hexdigest()!=evidence.get("sha256"):
                raise ValueError("ANALYSIS_RAW_HASH_MISMATCH")
            obj=source.decode_json(raw,mid)
            counts["analysis_read"]+=1
        except (OSError,EOFError,ValueError,KeyError):
            counts["analysis_failed"]+=1
            continue
        for r in history_from_json(obj,cutoff):
            identity=r["match_id"]
            if identity not in data:
                data[identity]=r
            elif data[identity]!=r:
                data[identity]=None
                counts["conflicting_matches"]+=1
            else:
                counts["duplicate_matches"]+=1
    rows=[r for r in data.values() if r is not None]
    rows.sort(key=lambda r:(r["played_at_utc"],r["match_id"]))
    counts["historical_matches"]=len(rows)
    return rows,counts

def exponential_strength_fit(matches,cutoff,iterations=140,ridge=4.0):
    """Deterministic time-weighted regularized Poisson strength estimates.

    lambda_home = base_home * exp(attack_home + defense_away)
    lambda_away = base_away * exp(attack_away + defense_home)

    This is intentionally isolated from betting prices and target future
    fixtures. Parameter ridge shrinkage protects sparse 007 team histories.
    """
    if len(matches)<MIN_TRAIN_MATCHES:
        return None
    weights=[]
    teams=set()
    for row in matches:
        age=max(0.0,(cutoff-parsed_at(row["played_at_utc"])).total_seconds()/86400)
        weights.append(2.0**(-age/HALF_LIFE_DAYS))
        teams.add(row["home_id"]);teams.add(row["away_id"])
    weight_total=sum(weights)
    if weight_total<=0:return None
    base_h=max(.35,min(3.5,sum(w*r["home_goals"] for w,r in zip(weights,matches))/weight_total))
    base_a=max(.35,min(3.5,sum(w*r["away_goals"] for w,r in zip(weights,matches))/weight_total))
    attack={team:0.0 for team in teams}
    defense={team:0.0 for team in teams}
    exposure={team:0.0 for team in teams}
    games={team:0 for team in teams}
    for r,w in zip(matches,weights):
        h,a=r["home_id"],r["away_id"]
        exposure[h]+=w;exposure[a]+=w
        games[h]+=1;games[a]+=1
    for _ in range(iterations):
        ag=defaultdict(float);dg=defaultdict(float)
        for r,w in zip(matches,weights):
            h,a=r["home_id"],r["away_id"]
            lh=base_h*math.exp(max(-2.0,min(2.0,attack[h]+defense[a])))
            la=base_a*math.exp(max(-2.0,min(2.0,attack[a]+defense[h])))
            gh=w*(r["home_goals"]-lh)
            ga=w*(r["away_goals"]-la)
            ag[h]+=gh;dg[a]+=gh
            ag[a]+=ga;dg[h]+=ga
        # damped, normalized gradient with a ridge prior
        for t in teams:
            scale=0.55/(ridge+exposure[t])
            attack[t]=max(-1.3,min(1.3,attack[t]+scale*(ag[t]-ridge*attack[t])))
            defense[t]=max(-1.3,min(1.3,defense[t]+scale*(dg[t]-ridge*defense[t])))
    return {"base_h":base_h,"base_a":base_a,"attack":attack,
            "defense":defense,"games":games,"history_count":len(matches),
            "unique_teams":len(teams)}

def expected_goals(model,home,away):
    if model is None:
        return None
    h,a=str(home),str(away)
    if model["games"].get(h,0)<MIN_TEAM_GAMES or model["games"].get(a,0)<MIN_TEAM_GAMES:
        return None
    lamh=model["base_h"]*math.exp(model["attack"][h]+model["defense"][a])
    lama=model["base_a"]*math.exp(model["attack"][a]+model["defense"][h])
    return max(0.15,min(5.0,lamh)),max(0.15,min(5.0,lama))

def tau(h,a,lh,la,rho):
    if h==0 and a==0:return 1-lh*la*rho
    if h==0 and a==1:return 1+lh*rho
    if h==1 and a==0:return 1+la*rho
    if h==1 and a==1:return 1-rho
    return 1.0

def poisson(lam, cap=MAX_GOALS):
    p=[math.exp(-lam)]
    for k in range(1,cap+1):
        p.append(p[-1]*lam/k)
    # Bounded renormalization is done on the complete 2d grid below.
    return p

def score_grid(lh,la,rho=0.0,cap=MAX_GOALS):
    if not (0.05<=lh<=8.0 and 0.05<=la<=8.0 and -0.30<=rho<=0.30):
        raise ValueError("INVALID_DC_PARAMETERS")
    hp,ap=poisson(lh,cap),poisson(la,cap)
    grid={}
    for h,x in enumerate(hp):
        for a,y in enumerate(ap):
            weight=tau(h,a,lh,la,rho)
            if weight<=0:raise ValueError("INVALID_NEGATIVE_DC_TAU")
            grid[h,a]=x*y*weight
    total=sum(grid.values())
    if not math.isfinite(total) or total<=0:raise ValueError("INVALID_DC_DISTRIBUTION")
    return {(h,a):p/total for (h,a),p in grid.items()}

def jc_three_markets(grid,handicap=None):
    had=[0.0]*3;hhad=[0.0]*3 if handicap is not None else None;ttg=[0.0]*8
    for (h,a),p in grid.items():
        had[0 if h>a else 1 if h==a else 2]+=p
        if hhad is not None:
            score=h+handicap-a
            hhad[0 if score>0 else 1 if score==0 else 2]+=p
        ttg[min(h+a,7)]+=p
    top=max(grid,key=grid.get)
    return had,hhad,ttg,top

def mean_log_score(matches,model,rho):
    score=0.0;matched=0
    for r in matches:
        lam=expected_goals(model,r["home_id"],r["away_id"])
        if lam is None:continue
        grid=score_grid(*lam,rho=rho)
        outcome=(r["home_goals"],r["away_goals"])
        score-=math.log(max(grid.get(outcome,1e-12),1e-12))
        matched+=1
    return score/matched if matched else None,matched

def choose_rho(history,cutoff):
    if len(history)<MIN_TRAIN_MATCHES+MIN_VALIDATION_GAMES:
        return 0.0,{"status":"INSUFFICIENT_HISTORICAL_SPLIT","holdout_games":0}
    ordered=sorted(history,key=lambda r:r["played_at_utc"])
    cut=max(MIN_TRAIN_MATCHES,int(len(ordered)*.80))
    split_time=ordered[cut]["played_at_utc"]
    # A historical game's kickoff is NOT its result-observed timestamp.
    # Exclude the preceding three hours at the validation boundary so that
    # an in-progress/future result cannot train the earlier model.
    older=[m for m in ordered
           if (parsed_at(split_time)-parsed_at(m["played_at_utc"])).total_seconds()>=3*3600]
    newer=[m for m in ordered if m["played_at_utc"]>=split_time]
    if len(newer)<MIN_VALIDATION_GAMES or len(older)<MIN_TRAIN_MATCHES:
        return 0.0,{"status":"INSUFFICIENT_UNIQUE_CHRONOLOGICAL_VALIDATION","holdout_games":len(newer)}
    model=exponential_strength_fit(older,parsed_at(split_time))
    if model is None:
        return 0.0,{"status":"TRAINING_NOT_AVAILABLE","holdout_games":len(newer)}
    scored={}
    for rho in RHO_GRID:
        try:
            val,n=mean_log_score(newer,model,rho)
        except ValueError:
            continue
        if val is not None:scored[rho]=(val,n)
    if 0.0 not in scored or scored[0.0][1]<MIN_VALIDATION_GAMES:
        return 0.0,{"status":"NO_SUFFICIENT_VALIDATION_TEAM_COVERAGE",
                    "holdout_games":len(newer),
                    "scored_matches":scored.get(0.0,(None,0))[1]}
    best=min(scored,key=lambda x:scored[x][0])
    gain=scored[0.0][0]-scored[best][0]
    # Require a measurable improvement. rho=0 is always the safe baseline.
    if gain < .005:best=0.0
    return best,{"status":"RESEARCH_CHRONOLOGICAL_HOLDOUT_NOT_PROSPECTIVE",
                "holdout_games":len(newer),"scored_matches":scored[0.0][1],
                "baseline_logloss":round(scored[0.0][0],5),
                "candidate_logloss":round(scored[best][0],5),
                "in_sample_selection_optimism":True}

def prob_market(labels,values,odds=None):
    if values is None:
        return {"status":"UNAVAILABLE","direction":None,"probabilities":None}
    direction=max(range(len(values)),key=lambda i:values[i])
    return {"status":"SHADOW_UNCALIBRATED",
            "direction":labels[direction],
            "direction_probability":round(values[direction],6),
            "probabilities":{name:round(p,6) for name,p in zip(labels,values)},
            "jc_odds":odds}

def make_shadow(snapshot,raw_dir):
    cutoff=parsed_at(snapshot["captured_at_utc"])
    rows,source_quality=collect_historical(snapshot,raw_dir)
    rho,validation=choose_rho(rows,cutoff)
    model=exponential_strength_fit(rows,cutoff)
    outputs=[]
    for game in snapshot.get("games",[]):
        match_id=str(game.get("match_id") or "")
        base={"match_id":match_id,"jc_number":game.get("jc_number"),
              "home_team":game.get("home_team"),"away_team":game.get("away_team"),
              "kickoff_beijing":game.get("kickoff_beijing"),
              "model_source":"007_HISTORICAL_FINISHED_MATCHES_ONLY",
              "injury_source_state":game.get("injury_report_state","UNAVAILABLE")}
        try:
            if parsed_at(game["kickoff_beijing"])<=cutoff:
                raise ValueError("POST_KICKOFF_REJECTED")
            h,a=game["home_team_id_007"],game["away_team_id_007"]
            if h is None or a is None:raise ValueError("MISSING_TEAM_007_ID")
            lam=expected_goals(model,h,a)
            if lam is None:raise ValueError("INSUFFICIENT_TEAM_MATCH_HISTORY")
            markets=game.get("jc_markets") or {}
            hh=markets.get("hhad")
            handicap=None if hh is None else hh.get("signed_home_handicap")
            if handicap is not None and (type(handicap)!=int or abs(handicap)>12):
                raise ValueError("INVALID_OFFICIAL_JC_HANDICAP")
            grid=score_grid(*lam,rho=rho)
            had,hhad,ttg,top=jc_three_markets(grid,handicap)
            ranked=sorted(zip(GOALS_LABELS,ttg),key=lambda x:x[1],reverse=True)
            chosen=ranked[:2] if ranked[1][1]>=.10 else ranked[:1]
            base.update(status="SHADOW_RESEARCH_READY",
                expected_goals={"home":round(lam[0],3),"away":round(lam[1],3)},
                top_score={"home":top[0],"away":top[1]},
                markets={
                    "had":prob_market(OUTCOMES,had,markets.get("had")),
                    "hhad":{**prob_market(HANDICAP_OUTCOMES,hhad,hh.get("odds") if hh else None),
                            "signed_home_handicap":handicap},
                    "ttg":{**prob_market(GOALS_LABELS,ttg,markets.get("ttg")),
                            "goal_selection":{"goals":[x[0] for x in chosen],
                                              "individual_probabilities":[round(x[1],6) for x in chosen],
                                              "combined_probability":round(sum(x[1] for x in chosen),6)}}
                })
            if markets.get("had") is None:
                base["markets"]["had"]["status"]="SHADOW_PROBABILITY_ONLY_JC_HAD_NOT_OFFERED"
            if handicap is None:
                base["markets"]["hhad"]["status"]="OFFICIAL_HANDICAP_UNAVAILABLE"
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            base.update(status="SHADOW_UNAVAILABLE",reason=str(exc)[:150],markets={})
        outputs.append(base)
    return {
        "model_version":VERSION,
        "mode":"FOOTBALL_SHADOW_ONLY_NO_PUSH_NO_CHAMPION_PROMOTION",
        "created_at_utc":datetime.now(UTC).isoformat(),
        "source_snapshot_sha256":hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "captured_at_utc":snapshot["captured_at_utc"],
        "game_count":len(outputs),
        "shadow_ready":sum(x["status"]=="SHADOW_RESEARCH_READY" for x in outputs),
        "history_source_quality":source_quality,
        "training_summary":{"historical_matches":len(rows),
                            "teams":0 if model is None else model["unique_teams"],
                            "rho":rho,"rho_validation":validation,
                            "injury_adjustment":"NONE_UNVERIFIED_007_AVAILABILITY",
                            "historical_holdout_is_not_prospective":True},
        "markets":["had","hhad","ttg"],
        "no_claim_of_backtested_accuracy":True,
        "games":outputs}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot",required=True)
    ap.add_argument("--analysis-dir",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    raw=Path(args.snapshot).read_bytes()
    if len(raw)>12_000_000:raise SystemExit("SNAPSHOT_TOO_LARGE")
    snapshot=json.loads(raw)
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise SystemExit("NOT_VERIFIED_007_SNAPSHOT_SCHEMA")
    report=make_shadow(snapshot,args.analysis_dir)
    report["input_raw_sha256"]=hashlib.sha256(raw).hexdigest()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_DC_SHADOW",report["shadow_ready"],"/",report["game_count"],
          "history",report["training_summary"]["historical_matches"],
          "rho",report["training_summary"]["rho"],
          "validation",report["training_summary"]["rho_validation"]["status"])

if __name__=="__main__":
    main()
