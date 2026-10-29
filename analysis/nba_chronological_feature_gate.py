#!/usr/bin/env python3
"""Strict chronological features from tri-route verified NBA scores.

Research candidate only. Every input to feature vector for target day D
has game_date <= D-2 calendar days. All games on same target date are scored
before any standings update. Frozen season-aware chronological train/val/test
metadata. Source records are complete-game results, not as-of vendor feeds.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from collections import defaultdict,deque
from datetime import date,timedelta
from pathlib import Path

from build_three_route_scores import assemble

RAW_COLS={"date","home","away","home_points","away_points","playoffs"}
OUT_FEATURES=["home_wins5","away_wins5","home_margin5","away_margin5",
"home_for5","away_for5","home_against5","away_against5",
"home_wins10","away_wins10","home_margin10","away_margin10",
"home_for10","away_for10","home_against10","away_against10",
"home_rest_days","away_rest_days","h2h_home_margin5","h2h_prior_games"]
OUT_COLS=["date","home","away",*OUT_FEATURES,"home_win","home_margin","final_total","split",
          "feature_latest_source_date","feature_embargo_days"]
TRAIN_END="2019-08-01"
VALID_END="2021-08-01"
HOLDOUT_END="2022-08-01"
EMBARGO_DAYS=1

def add_day(ymd,days):
    return (date.fromisoformat(ymd)+timedelta(days=days)).isoformat()

def stats(games,n):
    a=games[-n:]
    return (sum(int(v["win"]) for v in a)/n,
            sum(v["margin"] for v in a)/n,
            sum(v["points_for"] for v in a)/n,
            sum(v["points_against"] for v in a)/n)

def split_for(day):
    if day<TRAIN_END:return "train"
    if day<VALID_END:return "validation"
    if day<HOLDOUT_END:return "sealed_holdout"
    raise ValueError("OUT_OF_TRAIN_RANGE")

def produce(rows,embargo_days=EMBARGO_DAYS,min_history=5):
    """Return features and rejection audit, no same-day history or future outcomes."""
    if embargo_days<1:raise ValueError("EMBARGO_TOO_SMALL")
    sorted_rows=sorted(rows,key=lambda x:(x["date"],x["home"],x["away"]))
    unique=set()
    daily=defaultdict(list)
    for r in sorted_rows:
        if set(r)!=RAW_COLS:raise ValueError("UNAPPROVED_SOURCE_COLUMN")
        day=date.fromisoformat(r["date"]).isoformat()
        if not ("2007-08-01"<=day<HOLDOUT_END):raise ValueError("DATA_RANGE_VIOLATION")
        key=(day,r["home"],r["away"])
        if key in unique:raise ValueError("DUPLICATE_GAME")
        unique.add(key)
        if r["home"]==r["away"]:raise ValueError("DUPLICATE_TEAM")
        daily[day].append(r)
    history=defaultdict(list);pair_history=defaultdict(list)
    staged=deque()
    accepted=[]
    skipped=defaultdict(int)
    for day in sorted(daily):
        # A game can contribute on day D only when its date < D-1 day.
        cut=add_day(day,-embargo_days)
        while staged and staged[0][0]<cut:
            _,games=staged.popleft()
            for g in games:
                d=g["date"];h=g["home"];a=g["away"]
                hp=int(g["home_points"]);ap=int(g["away_points"])
                history[h].append({"date":d,"win":hp>ap,"margin":hp-ap,
                    "points_for":hp,"points_against":ap})
                history[a].append({"date":d,"win":ap>hp,"margin":ap-hp,
                    "points_for":ap,"points_against":hp})
                pair_history[tuple(sorted((h,a)))].append((d,h,a,hp-ap))
        for g in daily[day]:
            h,a=g["home"],g["away"]
            home_hist,away_hist=history[h],history[a]
            if len(home_hist)<min_history or len(away_hist)<min_history:
                skipped["COLD_START_LESS_THAN_5_GAMES"]+=1
                continue
            hh5=stats(home_hist,5);aa5=stats(away_hist,5)
            hh10=stats(home_hist,10) if len(home_hist)>=10 else None
            aa10=stats(away_hist,10) if len(away_hist)>=10 else None
            if hh10 is None or aa10 is None:
                skipped["LESS_THAN_10_GAMES"]+=1
                continue
            h2h=pair_history.get(tuple(sorted((h,a))),[])
            latest=max(home_hist[-1]["date"],away_hist[-1]["date"])
            if not (latest<cut and all(x["date"]<cut for x in home_hist+away_hist)):
                raise AssertionError("CHRONOLOGICAL_LEAKAGE")
            recentpair=h2h[-5:]
            margin_hh=sum((m if home==h else -m) for _,home,away,m in recentpair)/len(recentpair) if recentpair else 0.0
            hp,ap=int(g["home_points"]),int(g["away_points"])
            row={
                "date":day,"home":h,"away":a,
                "home_wins5":hh5[0],"away_wins5":aa5[0],
                "home_margin5":hh5[1],"away_margin5":aa5[1],
                "home_for5":hh5[2],"away_for5":aa5[2],
                "home_against5":hh5[3],"away_against5":aa5[3],
                "home_wins10":hh10[0],"away_wins10":aa10[0],
                "home_margin10":hh10[1],"away_margin10":aa10[1],
                "home_for10":hh10[2],"away_for10":aa10[2],
                "home_against10":hh10[3],"away_against10":aa10[3],
                "home_rest_days":(date.fromisoformat(day)-date.fromisoformat(home_hist[-1]["date"])).days,
                "away_rest_days":(date.fromisoformat(day)-date.fromisoformat(away_hist[-1]["date"])).days,
                "h2h_home_margin5":margin_hh,"h2h_prior_games":len(recentpair),
                "home_win":int(hp>ap),"home_margin":hp-ap,"final_total":hp+ap,
                "split":split_for(day),"feature_latest_source_date":latest,
                "feature_embargo_days":embargo_days
            }
            if set(row)!=set(OUT_COLS):raise AssertionError("NON_WHITELISTED_OUTPUT")
            accepted.append(row)
        staged.append((day,daily[day]))
    # Invariance and time assertions on every target row
    for row in accepted:
        assert row["feature_latest_source_date"]<add_day(row["date"],-embargo_days)
        assert row["split"]==split_for(row["date"])
        assert all(math.isfinite(float(row[k])) for k in OUT_FEATURES)
    return accepted,dict(skipped)

def selftest():
    # Two teams playing same calendar day twice: neither game's result can
    # affect any game on that date; also check previous day embargo.
    games=[]
    for i in range(12):
        day=add_day("2018-01-01",i*2)
        games.append({"date":day,"home":"BOS","away":"NYK","home_points":110+i,
                      "away_points":100,"playoffs":0})
    target_day="2018-02-01"
    # Synthetic warmups create history; add other teams with matching counts.
    games += [{"date":add_day("2018-01-01",i*2),"home":"LAL","away":"GSW",
               "home_points":101+i,"away_points":98,"playoffs":0} for i in range(12)]
    base={"date":target_day,"home":"BOS","away":"LAL","home_points":123,"away_points":101,"playoffs":0}
    second={"date":target_day,"home":"NYK","away":"GSW","home_points":95,"away_points":93,"playoffs":0}
    t1,_=produce(games+[base,second])
    t2,_=produce(games+[dict(base,home_points=140),dict(second,home_points=40)])
    x1={tuple(v[k] for k in ("date","home","away")):v for v in t1}
    x2={tuple(v[k] for k in ("date","home","away")):v for v in t2}
    assert x1.keys()==x2.keys()
    for key in x1:
        for f in OUT_FEATURES:
            assert x1[key][f]==x2[key][f],(key,f)
    assert t1[-1]["feature_latest_source_date"]<add_day(target_day,-1)
    assert split_for("2019-07-31")=="train"
    assert split_for("2019-08-01")=="validation"
    assert split_for("2021-08-01")=="sealed_holdout"
    print("NBA_PRETIP_LAG_FEATURE_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:return selftest()
    games,rej,digest=assemble()
    features,skips=produce(games)
    out=Path("/tmp/nba-pregame-lagged-research")
    out.mkdir(exist_ok=True)
    csv_path=out/"nba_pregame_rolling_features_2007_2022.csv"
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=OUT_COLS)
        writer.writeheader();writer.writerows(features)
    splits={x:sum(r["split"]==x for r in features) for x in ("train","validation","sealed_holdout")}
    meta={"status":"LAGGED_FEATURE_RESEARCH_ONLY",
       "input_tri_route_games":len(games),"rows":len(features),
       "splits":splits,"coverage_rejections":skips,
       "input_crosscheck_rejections":rej,"source_index_sha256":digest,
       "feature_sha256":hashlib.sha256(csv_path.read_bytes()).hexdigest(),
       "date_embargo_days":EMBARGO_DAYS,
       "latest_source_day_strictly_before_target_minus_embargo":True,
       "same_day_outcome_feature_leakage_unit_test_passed":True,
       "underlying_source_publication_timestamps_verified":False,
       "upstream_rights_and_independence_unresolved":True,
       "odds_data_joined":False,"holdout_used_for_fitting":False,
       "model_trained":False,"production_promoted":False,
       "raw_data_committed_to_git":False}
    (out/"manifest.json").write_text(json.dumps(meta,sort_keys=True,indent=2))
    print("NBA_PRETIP_LAGGED_FEATURES_AUDIT "+json.dumps(meta,sort_keys=True),flush=True)
    assert splits["train"]>5000 and splits["validation"]>1500 and splits["sealed_holdout"]>1000
if __name__=="__main__":main()
