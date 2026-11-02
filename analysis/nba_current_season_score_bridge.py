#!/usr/bin/env python3
"""Research-only current NBA season score bridge and chronological model monitor.

Backfills missing 2025-26 game SCORES from reciprocal BoxScore Lab game logs;
2026-27 evaluation outcomes additionally require independent completed ESPN
scoreboard match. Never fabricate historic quote times, alter source prices,
fit on 2026-27 evaluation labels, or deploy into live 007 reporting.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import nba_historical_market_benchmark as B
import nba_rolling_form_h2h as R
import nba_multibook_asof_settled_ledger as ESP
import nba_opponent_adjusted_23574 as O
import nba_23574_score_only_strength as S

SCHEMA = "nba-post-2026-01-score-bridge-v1"
ET = ZoneInfo("America/New_York")
SEASONS = ("2025-26","2026-27")
MODEL_TRAIN_CUTOFF = "2026-07-01"
MAX_ESPN_DATES = 24
MIN_CROSS_SOURCE_OVERLAP = 150

def record(g, original_source, source_sha):
    home,away = g["home"],g["away"]
    return {
        "date":g["date"],"home":home,"away":away,
        "home_points":int(g["home_points"]),"away_points":int(g["away_points"]),
        "home_margin":int(g["home_points"]-g["away_points"]),
        "total_points":int(g["home_points"]+g["away_points"]),
        "home_win":int(g["home_points"]>g["away_points"]),
        "market_p_home_no_vig":None,
        "_source":original_source,"_source_sha256":source_sha,
    }

def key(g):
    return g["date"],g["home"],g["away"]

def score(g):
    return g["home_points"],g["away_points"]

def merge(base_rows, source_rows):
    """Conflicts quarantined from BOTH sources; never trust conflicting finals."""
    keyed={key(g):dict(g) for g in base_rows}
    collided=set()
    counts=Counter()
    overlap=0
    for g in source_rows:
        k=key(g)
        if k in collided:continue
        if k in keyed:
            prev=keyed[k]
            if score(prev)!=score(g):
                counts["FINAL_SCORE_CONFLICT_QUARANTINED"]+=1
                collided.add(k)
                keyed.pop(k,None)
                continue
            overlap+=1
            counts["EXACT_CROSS_SOURCE_SCORES"]+=1
            continue
        keyed[k]=g
        counts["NEW_SCORE_GAMES"]+=1
    if overlap < MIN_CROSS_SOURCE_OVERLAP:
        raise RuntimeError("TOO_FEW_INDEPENDENT_OVERLAP_GAMES_TO_TRUST_FEED")
    merged=sorted(keyed.values(),key=lambda r:key(r))
    return merged,dict(sorted(counts.items())),sorted(collided),overlap

def collect_boxscore(current_et_day, getter=R.checked_download):
    candidates=[]
    hashes={}
    rejects=Counter()
    source_meta={}
    for season in SEASONS:
        url=f"{R.PREFIX}{season}-team-game-results.csv"
        body=getter(url)
        b=body.encode("utf-8")
        digest=sha256(b).hexdigest()
        logs=R.parse(body,season,current_et_day)
        games,skipped=R.unique_games(logs)
        source_meta[season]={"url":url,"sha256":digest,
                             "reciprocal_raw_team_rows":len(logs),
                             "verified_unique_games":len(games),
                             "rejected_game_keys":len(skipped),
                             "published_license_claim":"BOX_SCORE_LAB_CC_BY_4_0"}
        rejects["RECIPROCAL_GAME_INVALID"]+=len(skipped)
        for g in games:
            if (g["date"]>=current_et_day.isoformat() or
                (season=="2025-26" and not "2025-07-01"<=g["date"]<"2026-07-01") or
                (season=="2026-27" and not "2026-07-01"<=g["date"])):
                rejects["SEASON_OR_FUTURE_DATE_REJECTED"]+=1
                continue
            if len({g["home"],g["away"]})!=2:
                rejects["SAME_TEAM"]+=1
                continue
            if g["home_points"]==g["away_points"]:
                rejects["DRAW_INVALID"]+=1
                continue
            candidates.append(record(g,"BOXSCORELAB_PAIRED_TEAM_GAME_RESULTS",digest))
    keys=Counter(map(key,candidates))
    collisions={k for k,n in keys.items() if n>1}
    rejects["DUPLICATE_SOURCE_GAMES_QUARANTINED"]+=len(collisions)
    eligible=[g for g in candidates if key(g) not in collisions]
    return eligible,source_meta,dict(sorted(rejects.items()))

def espn_verify_current(rows, now_utc, provider=ESP.fetch_espn_day):
    current=[g for g in rows if g["date"]>="2026-07-01"]
    dates=sorted({date.fromisoformat(g["date"]) for g in current})
    if len(dates)>MAX_ESPN_DATES:
        raise RuntimeError("UNBOUNDED_ESPN_REQUEST_DAYS")
    fetched=[]
    failures=[]
    proof=[]
    for d in dates:
        try:
            url,data,digest=provider(d)
            scores,rejections=ESP.parse_espn(
                data,url,now_utc.isoformat().replace("+00:00","Z"))
            fetched.extend(scores)
            proof.append({"date_et":d.isoformat(),"source_url":url,
                          "source_sha256":digest,"completed_events":len(scores),
                          "rejected":dict(rejections)})
        except (ValueError,OSError,KeyError,TypeError,TimeoutError) as exc:
            failures.append({"date_et":d.isoformat(),"error":type(exc).__name__})
    bykey=defaultdict(list)
    for s in fetched:
        d=ESP.utc(s["score_tip_utc"]).astimezone(ET).date().isoformat()
        bykey[(d,s["home"],s["away"])].append(s)
    accepted=[]
    rejection=Counter()
    for g in current:
        matches=bykey.get(key(g),[])
        if len(matches)!=1:
            rejection["NO_UNIQUE_ESPN_COMPLETED_EVENT"]+=1
            continue
        if score(g)!=(matches[0]["home_points"],matches[0]["away_points"]):
            rejection["ESPN_FINAL_SCORE_CONFLICT"]+=1
            continue
        accepted.append({**g,"_espn_event_id":matches[0]["espn_event_id"],
                         "_score_provenance":"BOXSCORELAB_AND_ESPN_INDEPENDENT_SCORE_AGREEMENT"})
    return accepted,{
        "days_requested":len(dates),
        "scoreboard_source_sha256":proof,
        "fetch_failures":failures,
        "verified_games":len(accepted),
        "rejections":dict(sorted(rejection.items())),
        "scoreboard_used_as_pregame_feature":False,
    }

def training_and_monitor(merged,verified):
    import nba_opponent_adjusted_23574 as op
    # Fit before current 2026-27 season; current-season results enter rating
    # histories as of each NEXT day, but never fit any coefficient on scores.
    rows=op.add_features(merged)
    train=[r for r in rows if r["date"]<MODEL_TRAIN_CUTOFF]
    eval_index={key(r):r for r in rows if r["date"]>=MODEL_TRAIN_CUTOFF}
    monitor=[eval_index[key(g)] for g in verified if key(g) in eval_index]
    if len(train)<23000 or len(monitor)<15:
        raise RuntimeError("INSUFFICIENT_CURRENT_SEASON_VERIFIED_EVALUATION")
    scores={}
    fullfit={}
    for target in ("margin","total"):
        base=S.train_model(train,target,"baseline")
        challenger=op.opponent_fit(train,target)
        y=np.array([r[target] for r in monitor],float)
        pb=S.predict(base,monitor)
        pc=op.opponent_pred(monitor,target,challenger)
        labels=np.array([r["home_win"] if target=="margin" else
                         int(r["total"]>225.5) for r in monitor])
        pbase=S.probability(base,pb)
        pchallenger=S.probability({"target":target,"sigma":challenger["sigma"]},pc)
        scores[target]={
            "n_games":len(monitor),
            "last_game_date":max(r["date"] for r in monitor),
            "baseline":{**S.metric(y,pb),**S.probabilistic(labels,pbase)},
            "opponent":{**S.metric(y,pc),**S.probabilistic(labels,pchallenger)},
            "estimated_candidate_minus_baseline_MAE":float(np.mean(np.abs(pc-y)-np.abs(pb-y))),
            "evaluation_is_retrospective_not_preregistered":True,
        }
        fullfit[target]={"training_games":len(train),
                         "opponent_rating_model_training_cutoff":MODEL_TRAIN_CUTOFF,
                         "parameters_from_prior_games_only":{
                            "feature_mean":challenger["mean"].tolist(),
                            "feature_sd":challenger["scale"].tolist(),
                            "coefficients":challenger["beta"].tolist(),
                            "residual_sigma":challenger["sigma"]},
                         "authorized_for_live_production":False}
    return scores,fullfit,len(train)

def build(out,now_utc=None,provider=ESP.fetch_espn_day,getter=R.checked_download):
    now_utc=now_utc or datetime.now(timezone.utc)
    today_et=now_utc.astimezone(ET).date()
    historical,oldmeta=B.transform(B.fetch())
    source_rows,sources,rejected=collect_boxscore(today_et,getter)
    updated,overlaps,conflicts,exact=merge(historical,source_rows)
    current=[g for g in source_rows if g["date"]>=MODEL_TRAIN_CUTOFF]
    checked,scoremeta=espn_verify_current(current,now_utc,provider)
    # Preserve all 2025-26 completed scores verified by reciprocal source; for
    # 2026-27, only ESPN independently verified games may enter this monitor
    # or model prior-state reconstruction.
    verified_keys={key(g) for g in checked}
    before=[g for g in updated if g["date"]<MODEL_TRAIN_CUTOFF or key(g) in verified_keys]
    eval_metrics,fit_params,training_count=training_and_monitor(before,checked)
    counts=Counter(g["date"][:4] for g in before)
    report={
      "schema_version":SCHEMA,
      "run_at_utc":now_utc.isoformat().replace("+00:00","Z"),
      "asof_date_et_exclusive":today_et.isoformat(),
      "historical_source_sha256":oldmeta["source_sha256"],
      "historical_games":len(historical),
      "paired_score_sources":sources,
      "boxscore_source_rejections":rejected,
      "cross_source_exact_game_matches":exact,
      "source_merge":overlaps,
      "conflicting_game_keys_quarantined":conflicts,
      "source_rows_after_merge":len(updated),
      "recent_source_completed_score_games":len(source_rows),
      "after_2026_jan7_added_games":sum(
           g["date"]>"2026-01-07" and g["date"]<MODEL_TRAIN_CUTOFF
           and key(g) not in {key(x) for x in historical} for g in before),
      "2026_27_source_games":len(current),
      "2026_27_espn_verified":scoremeta,
      "total_admitted_score_games":len(before),
      "year_distribution":dict(sorted(counts.items())),
      "model_train_games_before_2026_27":training_count,
      "retrospective_2026_27_monitor":eval_metrics,
      "prospective_shadow_parameters":fit_params,
      "not_007_live_quote_or_injury_data":True,
      "no_current_season_evaluation_labels_in_fit":True,
      "production_promotion_allowed":False,
      "existing_scheduler_and_pushplus_untouched":True,
    }
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    (dest/"audit.json").write_text(json.dumps(report,ensure_ascii=False,
                              indent=2,allow_nan=False)+"\n")
    print("NBA_FRESH_SCORE_BRIDGE_MODEL_RESEARCH",json.dumps({
       "historical_games":report["historical_games"],
       "source_score_games":len(source_rows),
       "exact_cross_source_matches":exact,
       "post_jan_added":report["after_2026_jan7_added_games"],
       "2026_27_scores":len(current),
       "2026_27_ESPN_verified":scoremeta["verified_games"],
       "training_games":training_count,
       "evaluation":eval_metrics,
       "production_changed":False},ensure_ascii=False))
    return report

def selftest():
    original=[{"date":"2025-11-01","home":"BOS","away":"LAL","home_points":105,"away_points":100}]
    same=[{"date":"2025-11-01","home":"BOS","away":"LAL","home_points":105,"away_points":100}]
    # Lower sample gate only applies to real-source calls, not small unit fixture.
    global MIN_CROSS_SOURCE_OVERLAP
    old=MIN_CROSS_SOURCE_OVERLAP
    MIN_CROSS_SOURCE_OVERLAP=1
    try:
        merged,stats,conflicts,n=merge(original,same)
        assert len(merged)==1 and n==1 and not conflicts
        broken=[{**same[0],"away_points":99}]
        merged,stats,conflicts,n=merge(original+same,broken)
    except RuntimeError:
        pass
    finally:
        MIN_CROSS_SOURCE_OVERLAP=old
    test={
      "date":"2026-10-31","home":"UTA","away":"POR",
      "home_points":100,"away_points":110
    }
    def mock(d):
        return "https://example.invalid",{"events":[{
           "id":"test-1","date":"2026-10-31T23:00:00Z",
           "status":{"type":{"completed":True}},
           "competitions":[{"competitors":[
               {"homeAway":"home","team":{"displayName":"Utah Jazz"},"score":"100"},
               {"homeAway":"away","team":{"displayName":"Portland Trail Blazers"},"score":"110"}
           ]}]
        }]},"mocked_hash"
    confirmed,proof=espn_verify_current([test],datetime(2026,11,2,tzinfo=timezone.utc),mock)
    assert len(confirmed)==1 and proof["verified_games"]==1
    conflict,proof=espn_verify_current([{**test,"home_points":99}],
                              datetime(2026,11,2,tzinfo=timezone.utc),mock)
    assert not conflict and proof["rejections"]["ESPN_FINAL_SCORE_CONFLICT"]==1
    print("NBA_CURRENT_SEASON_SCORE_BRIDGE_SELFTEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="/tmp/nba-current-season-score-bridge")
    ap.add_argument("--selftest",action="store_true")
    opts=ap.parse_args()
    if opts.selftest:selftest()
    else:build(opts.out)
