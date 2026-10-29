#!/usr/bin/env python3
"""Development-only dynamic strength + available Four Factors benchmark."""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np
import nba_chronological_backtest as B

SEASONS = B.SEASON_FILES
ELO_START, ELO_K, HOME_ADV = 1500.0, 20.0, 35.0

def enriched_games(cutoff):
    raw, sources = [], {}
    for season in SEASONS:
        url = f"{B.PREFIX}{season}-team-game-results.csv"
        text = B.checked_download(url)
        parsed = B.parse(text, season, cutoff)
        raw.extend(parsed)
        sources[season] = {"url": url, "rows": len(parsed)}
    games, rejected = B.unique_games(raw)
    idx = {(r["date"], r["team"], r["opponent"]): r for r in raw}
    out = []
    for g in games:
        h = idx.get((g["date"], g["home"], g["away"]))
        a = idx.get((g["date"], g["away"], g["home"]))
        if not h or not a:
            continue
        g = dict(g)
        g["home_box"] = {k: h[k] for k in ("fga", "fta", "oreb", "tov", "possessions_est", "points")}
        g["away_box"] = {k: a[k] for k in ("fga", "fta", "oreb", "tov", "possessions_est", "points")}
        out.append(g)
    return out, rejected, sources

def team_entry(g, team):
    base = B.team_entry(g, team)
    box = g["home_box"] if g["home"] == team else g["away_box"]
    return {**base, **box}

def factors(hist):
    h = hist[-5:]
    if not h: return [0.0]*4
    def safe(a, b): return a/b if b else 0.0
    return [
        sum(safe(x["tov"], x["possessions_est"]) for x in h)/len(h),
        sum(safe(x["fta"], x["fga"]) for x in h)/len(h),
        sum(safe(x["oreb"], x["possessions_est"]) for x in h)/len(h),
        sum(safe(x["points"], x["possessions_est"]) for x in h)/len(h),
    ]

def rows_with_features(games):
    by_day = defaultdict(list)
    for g in games: by_day[g["date"]].append(g)
    hist, pairs = defaultdict(list), defaultdict(list)
    ratings = defaultdict(lambda: ELO_START)
    out = []
    for day in sorted(by_day):
        for g in by_day[day]:
            vals = B.features(g, hist, pairs)
            if vals is None: continue
            home, away = g["home"], g["away"]
            fh, fa = factors(hist[home]), factors(hist[away])
            elo = ratings[home] + HOME_ADV - ratings[away]
            out.append({
                "date": day, "season": g["season"], "home": home, "away": away,
                "game_id": f"{day}:{home}:{away}", "form": vals["form"],
                "h2h": vals["h2h"], "elo_diff": float(elo),
                "factors": [fh[i]-fa[i] for i in range(4)],
                "proof": vals["proof"], "margin": float(g["margin_home"]),
                "total": float(g["total"]),
            })
        for g in by_day[day]:
            home, away = g["home"], g["away"]
            expected = 1/(1+10**(-(ratings[home]+HOME_ADV-ratings[away])/400))
            actual = float(g["margin_home"] > 0)
            delta = ELO_K*(1+math.log1p(abs(g["margin_home"]))/2)*(actual-expected)
            ratings[home] += delta; ratings[away] -= delta
            hist[home].append(team_entry(g, home)); hist[away].append(team_entry(g, away))
            pairs[tuple(sorted((home, away)))].append(g)
    return out

def design(rows):
    return np.asarray([r["form"]+r["h2h"]+[r["elo_diff"]]+r["factors"] for r in rows], dtype=float)

def fit(rows, target, alpha=100.0):
    x, y = design(rows), np.asarray([r[target] for r in rows], dtype=float)
    means, stds = x.mean(0), np.where(x.std(0)>1e-6, x.std(0), 1.0)
    z=(x-means)/stds; mean_y=float(y.mean())
    beta=np.linalg.solve(z.T@z+alpha*np.eye(z.shape[1]),z.T@(y-mean_y))
    return {"means":means,"stds":stds,"mean_y":mean_y,"beta":beta}

def pred(rows, m):
    x=design(rows)
    return m["mean_y"]+((x-m["means"])/m["stds"])@m["beta"]

def evaluate(test, fits, cal):
    pm=pred(test,fits["margin"])+cal["margin"]["bias"]
    pt=pred(test,fits["total"])+cal["total"]["bias"]
    sm,st=cal["margin"]["sigma"],cal["total"]["sigma"]
    home=np.asarray([float(x["margin"]>.5) for x in test])
    over=np.asarray([float(x["total"]>B.TOTAL_LINE) for x in test])
    ph=np.asarray([B.p_greater(x,sm,.5) for x in pm])
    po=np.asarray([B.p_greater(x,st,B.TOTAL_LINE) for x in pt])
    return {"n":len(test),"margin_mae":float(np.mean(abs(pm-np.asarray([x["margin"] for x in test])))),
            "total_mae":float(np.mean(abs(pt-np.asarray([x["total"] for x in test])))),
            "home_brier":B.brier(ph,home),"home_log_loss":B.logloss(ph,home),
            "total_brier":B.brier(po,over),"total_log_loss":B.logloss(po,over)}

def run(out):
    games,rejected,sources=enriched_games(date(2026,10,29))
    rows=rows_with_features(games); splits=B.partition(rows)
    fits={t:fit(splits["train"],t) for t in ("margin","total")}
    cal={}
    for t in ("margin","total"):
        r=np.asarray([x[t] for x in splits["calibration"]])-pred(splits["calibration"],fits[t])
        bias=float(r.mean()); cal[t]={"bias":bias,"sigma":max(1.,float(np.sqrt(np.mean((r-bias)**2))))}
    metrics=evaluate(splits["test"],fits,cal)
    report={"schema_version":"nba-four-factors-extension-v1","generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "verified_independent_games":len(games),"sample_partitions":{k:len(v) for k,v in splits.items()},
            "hyperparameters":{"elo_start":ELO_START,"elo_k":ELO_K,"home_advantage":HOME_ADV,"ridge_alpha":100.},
            "factor_names":["turnover_rate","free_throw_rate","offensive_rebound_rate_proxy","points_per_possession"],
            "metrics":metrics,"decision":"DEVELOPMENT_ONLY_NO_PRODUCTION_SWITCH","odds_used":False,
            "sources":sources,"rejected":len(rejected),
            "notes":["Four Factors are available-data proxies; eFG% is not included without verified three-point fields.",
                     "All features are before tip and same-day scores update only after featurization."]}
    Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"metrics":metrics,"decision":report["decision"]},ensure_ascii=False)); return report

def self_test():
    g=[]
    for i in range(12):
        d=(date(2023,1,1)).fromordinal(date(2023,1,1).toordinal()+i).isoformat()
        g.append({"date":d,"season":"2022-23","home":"ATL","away":"MIA","home_points":110+i,"away_points":90,
                  "margin_home":20+i,"total":200+i,"home_possessions_est":99.,"away_possessions_est":100.,
                  "pace_est":99.5,"home_box":{"fga":80,"fta":20,"oreb":10,"tov":12,"possessions_est":99.,"points":110+i},
                  "away_box":{"fga":80,"fta":20,"oreb":9,"tov":13,"possessions_est":100.,"points":90}})
    r=rows_with_features(g); assert r and all(x["proof"]["max_input_game_date"]<x["date"] for x in r)
    print("NBA_FOUR_FACTORS_SELF_TEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--out",default="nba_four_factors_extension.json"); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test:self_test()
    else:run(a.out)
