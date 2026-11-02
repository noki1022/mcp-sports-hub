#!/usr/bin/env python3
"""Strict pretip NBA score-only shadow, completely separate from live market model.

Fetch genuinely upcoming ESPN schedule and verified completed source games.
No fabricated future result, no historical odds, no retrospective market price
time assumptions, no production odds/PushPlus updates. Freeze research forecasts
with source and model hashes as immutable GitHub Actions artifacts before tip.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict,deque
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen,Request
from zoneinfo import ZoneInfo

import nba_historical_market_benchmark as B
import nba_current_season_score_bridge as BR
import nba_opponent_adjusted_23574 as O
import nba_23574_score_only_strength as S
import historical_odds_validator as MAP

ET=ZoneInfo("America/New_York")
BJ=ZoneInfo("Asia/Shanghai")
SCHEMA="nba-independent-score-frozen-prospective-v1"
SCHEDULE_URL="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
MAX_BYTES=2_500_000

def iso(d):
    return d.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def get_future_fixtures(now,fetcher=None):
    """ESPN supplies *schedule metadata*, never completed future game labels."""
    def standard(url):
        request=Request(url,headers={"User-Agent":"NBA-Certified-Research-Pretip/1.0",
                                     "Accept":"application/json"})
        with urlopen(request,timeout=22) as res:
            raw=res.read(MAX_BYTES+1)
        if not raw or len(raw)>MAX_BYTES:raise ValueError("SCHEDULE_SIZE_INVALID")
        return json.loads(raw),sha256(raw).hexdigest()
    fetcher=fetcher or standard
    today=now.astimezone(ET).date()
    fixtures,seen={},set()
    sources=[]
    rejects=Counter()
    for delta in range(3):
        d=today+timedelta(days=delta)
        url=SCHEDULE_URL+"?"+urlencode({"dates":d.strftime("%Y%m%d"),"limit":"100"})
        data,digest=fetcher(url)
        sources.append({"url":url,"sha256":digest})
        for event in data.get("events",[]):
            try:
                if event["status"]["type"].get("completed") is True:
                    rejects["ALREADY_FINISHED"]+=1;continue
                tip=MAP.dt(event["date"])
                if not now+timedelta(minutes=10)<tip<=now+timedelta(hours=72):
                    rejects["NOT_PREGAME_IN_WINDOW"]+=1;continue
                comps=event["competitions"][0]["competitors"]
                if len(comps)!=2:
                    rejects["NON_TWO_TEAM"]+=1;continue
                sides={x["homeAway"]:x for x in comps}
                h=MAP.team(sides["home"]["team"].get("displayName") or "")
                a=MAP.team(sides["away"]["team"].get("displayName") or "")
                if not h or not a or h==a:
                    rejects["UNVERIFIED_HOME_AWAY_TEAM"]+=1;continue
                day=tip.astimezone(ET).date().isoformat()
                identifier=str(event["id"])
                k=(day,h,a)
                if k in fixtures or identifier in seen:
                    old=fixtures.get(k)
                    # ESPN often serves the very same event in adjacent-date
                    # requests. Identical ID+time is a duplicate, not conflict.
                    if (old and old["nba_game_id"]==identifier and
                        old["tipoff_utc"]==iso(tip)):
                        rejects["DUPLICATE_IDENTICAL_EVENT"]+=1
                        continue
                    rejects["DUPLICATE_OR_COLLIDING_EVENT"]+=1
                    fixtures.pop(k,None)
                    continue
                seen.add(identifier)
                fixtures[k]={
                    "date":day,"home":h,"away":a,"nba_game_id":identifier,
                    "tipoff_utc":iso(tip),
                    "tipoff_beijing":tip.astimezone(BJ).isoformat(),
                }
            except (KeyError,ValueError,TypeError,IndexError):
                rejects["INVALID_SCHEDULE_EVENT"]+=1
    return sorted(fixtures.values(),key=lambda f:f["tipoff_utc"]),sources,dict(sorted(rejects.items()))

def latest_form_for_fixtures(past,fixtures):
    """As-of features use *only completed scored games*, never pseudo finals."""
    if not past or not fixtures:
        return []
    dates=sorted({x["date"] for x in past})
    maximum=dates[-1]
    history=defaultdict(list)
    totals=deque(maxlen=300)
    for g in sorted(past,key=lambda x:(x["date"],x["home"],x["away"])):
        when=date.fromisoformat(g["date"]).toordinal()
        season=S.source_season(g)
        totals.append(float(g["total_points"]))
        for team,pf,pa,at_home in (
            (g["home"],g["home_points"],g["away_points"],True),
            (g["away"],g["away_points"],g["home_points"],False)):
            history[team].append({
                "date":g["date"],"ordinal":when,"season":season,"scored":pf,
                "conceded":pa,"net":pf-pa,"total":pf+pa,
                "win":float(pf>pa),"at_home":at_home,
            })
    league=S.average(totals,218.)
    opp=O.opponent_adjusted_features(past,future_fixtures=fixtures)
    out=[]
    for game in fixtures:
        if game["date"]<=maximum:
            raise RuntimeError("PRETIP_FIXTURE_DATE_NOT_AFTER_LAST_COMPLETED_GAME")
        day=date.fromisoformat(game["date"])
        season=int(B.season_of(game["date"]).split("-")[0])
        h=S.before_game_stats(history[game["home"]],season,day,league)
        a=S.before_game_stats(history[game["away"]],season,day,league)
        base_margin=[h["net12"]-a["net12"],h["net20"]-a["net20"],
                     h["win"]-a["win"],h["rest"]-a["rest"]]
        base_total=[league-218.,(h["total"]+a["total"])/2-league,
                    h["points_for"]+a["points_for"]-league]
        x=opp[(game["date"],game["home"],game["away"])]
        out.append({
            **game,
            "x_margin_baseline":base_margin,
            "x_total_baseline":base_total,
            "total_baseline":league,
            "x_margin_opponent":base_margin+[
               x["opponent_elo_gap"],x["opponent_power_gap"],
               x["opponent_pred_margin"]-2.2,
               x["opponent_pred_home_pts"]-x["opponent_pred_away_pts"]],
            "x_total_opponent":base_total+[
               x["opponent_pred_total"]-league,
               x["opponent_pred_home_pts"]+x["opponent_pred_away_pts"]-218.,
               x["opponent_elo_gap"]],
            "last_completed_score_date":maximum,
            "max_feature_input_date":maximum,
            "home_last_score_date":history[game["home"]][-1]["date"]
                if history[game["home"]] else None,
            "away_last_score_date":history[game["away"]][-1]["date"]
                if history[game["away"]] else None,
            "source_score_only":True,
        })
    assert all(r["max_feature_input_date"]<r["date"] for r in out)
    return out

def load_verified_asof(now):
    history,meta=B.transform(B.fetch())
    logs,logmeta,logrejects=BR.collect_boxscore(now.astimezone(ET).date())
    joined,merge_stats,conflicts,overlap=BR.merge(history,logs)
    recent=[r for r in logs if r["date"]>="2026-07-01"]
    settled,scoremeta=BR.espn_verify_current(recent,now)
    permitted={BR.key(x) for x in settled}
    allowed=[g for g in joined if g["date"]<"2026-07-01" or BR.key(g) in permitted]
    return allowed,{
        "historic_games":len(history),
        "verified_source_overlap":overlap,
        "admitted_completed_games":len(allowed),
        "verified_2026_27_completed":len(permitted),
        "score_source_hashes":logmeta,
        "source_rejections":logrejects,
        "score_conflicts":conflicts,
        "ESPN_completed_score_evidence":scoremeta,
        "historic_source_sha256":meta["source_sha256"],
        "market_data_used":False,
    }

def make_forecasts(past,fixtures,now):
    if not fixtures:raise RuntimeError("NO_FUTURE_GAMES_FOUND")
    maxscore=max(g["date"] for g in past)
    if min(f["date"] for f in fixtures)<=maxscore:
        raise RuntimeError("PRETIP_DATE_OVERLAPS_SCORE_DATA")
    prepared=latest_form_for_fixtures(past,fixtures)
    train=O.add_features(past)
    fit_m=O.opponent_fit(train,"margin")
    fit_t=O.opponent_fit(train,"total")
    margins=O.opponent_pred(prepared,"margin",fit_m)
    totals=O.opponent_pred(prepared,"total",fit_t)
    probas=S.probability({"target":"margin","sigma":fit_m["sigma"]},margins)
    cutoff=iso(now)
    predictions=[]
    for g,m,t,p in zip(prepared,margins,totals,probas):
        if MAP.dt(g["tipoff_utc"])<=now+timedelta(minutes=3):
            raise RuntimeError("FORECAST_NOT_PREGAME")
        predictions.append({
            "schema_version":SCHEMA,
            "capture_utc":cutoff,
            "nba_game_id":g["nba_game_id"],"date_et":g["date"],
            "tipoff_utc":g["tipoff_utc"],"tipoff_beijing":g["tipoff_beijing"],
            "home":g["home"],"away":g["away"],
            "model":"OPPONENT_STRENGTH_SCORE_ONLY_V1",
            "predicted_home_margin":round(float(m),5),
            "predicted_game_total":round(float(t),5),
            "predicted_home_win_probability":round(float(p),8),
            "margin_training_sigma":round(float(fit_m["sigma"]),5),
            "total_training_sigma":round(float(fit_t["sigma"]),5),
            "last_completed_input_date_et":maxscore,
            "training_game_count":len(train),
            "probability_calibration":"TRAINING_RESIDUAL_GAUSSIAN_NOT_INDEPENDENTLY_PROVEN",
            "bookmaker_reference":None,
            "no_retroactive_market_quotes":True,
            "production_promotion_eligible":False,
        })
    if not predictions:raise RuntimeError("NO_PREGAME_FORECAST")
    return predictions

def run(out):
    now=datetime.now(timezone.utc)
    if not now.tzinfo:raise RuntimeError("NAIVE_CURRENT_TIME")
    fixtures,schedules,rejections=get_future_fixtures(now)
    past,source=load_verified_asof(now)
    forecasts=make_forecasts(past,fixtures,now)
    output=Path(out);output.mkdir(parents=True,exist_ok=True)
    path=output/"frozen_pregame_score_only.jsonl"
    path.write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n"
                            for x in forecasts),encoding="utf-8")
    root=Path(__file__).resolve().parents[1]
    sources={
       "nba_prospective_score_shadow.py":root/"analysis/nba_prospective_score_shadow.py",
       "nba_opponent_adjusted_23574.py":root/"analysis/nba_opponent_adjusted_23574.py",
       "nba_23574_score_only_strength.py":root/"analysis/nba_23574_score_only_strength.py"}
    fingerprints={name:sha256(p.read_bytes()).hexdigest() for name,p in sources.items()}
    report={
        "schema_version":SCHEMA,"captured_at_utc":iso(now),
        "valid_future_games":len(forecasts),
        "last_score_asof_date":max(x["date"] for x in past),
        "inputs":source,
        "schedule_sources":schedules,
        "schedule_rejections":rejections,
        "model_code_sha256":fingerprints,
        "predictions_sha256":sha256(path.read_bytes()).hexdigest(),
        "predictions":forecasts,
        "future_game_outcomes_used_to_train":False,
        "historical_007_quote_time_fabricated":False,
        "production_push_model_changed":False,
        "auto_promotion":False,
        "research_artifact_retention_days":60,
    }
    (output/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,
                                      indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("NBA_SCORE_ONLY_FROZEN_FUTURE_SHADOW",json.dumps({
        "captured_at":report["captured_at_utc"],
        "games":report["valid_future_games"],
        "train_games":forecasts[0]["training_game_count"],
        "first_tipoff_utc":forecasts[0]["tipoff_utc"],
        "scores_through":report["last_score_asof_date"],
        "predictions":[{"game_id":r["nba_game_id"],"home":r["home"],
                        "away":r["away"],"tip":r["tipoff_beijing"],
                        "margin":r["predicted_home_margin"],
                        "total":r["predicted_game_total"],
                        "p_home":r["predicted_home_win_probability"]}
                        for r in forecasts],
        "production_changed":False,
    },ensure_ascii=False))
    return report

def selftest():
    original=[
      {"date":"2026-10-31","home":"UTA","away":"POR",
       "home_points":100,"away_points":110,
       "home_margin":-10,"total_points":210,"home_win":0,
       "market_p_home_no_vig":None}
    ]
    future=[{"date":"2026-11-02","home":"UTA","away":"POR",
             "nba_game_id":"123","tipoff_utc":"2026-11-03T00:00:00Z",
             "tipoff_beijing":"2026-11-03T08:00:00+08:00"}]
    result=latest_form_for_fixtures(original,future)
    assert len(result)==1
    assert result[0]["max_feature_input_date"]<result[0]["date"]
    assert result[0]["x_margin_opponent"][-1]!=0
    try:
        latest_form_for_fixtures(original,[{**future[0],"date":"2026-10-31"}])
    except RuntimeError:
        pass
    else:
        raise AssertionError("SAME_DAY_PSEUDO_FUTURE_ACCEPTED")
    def fake(url):
        return {"events":[{
          "id":"987","date":"2026-11-03T00:00:00Z",
          "status":{"type":{"completed":False}},
          "competitions":[{"competitors":[
            {"homeAway":"home","team":{"displayName":"Utah Jazz"}},
            {"homeAway":"away","team":{"displayName":"Portland Trail Blazers"}}
          ]}]
        }]},"testhash"
    items,src,rej=get_future_fixtures(datetime(2026,11,2,12,tzinfo=timezone.utc),fake)
    assert len(items)==1 and items[0]["nba_game_id"]=="987"
    print("NBA_PROSPECTIVE_SCORE_ONLY_PRETIP_FREEZE_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="/tmp/nba-prospective-score-shadow")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    selftest() if args.selftest else run(args.out)
