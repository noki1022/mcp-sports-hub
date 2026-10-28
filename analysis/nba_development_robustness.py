#!/usr/bin/env python3
"""Development-only NBA chronological lag-sensitivity and expanding CV.

NEVER call the previously viewed 2025-26 holdout "unseen" again.
This diagnostic reports only 2023-24 and 2024-25 development periods.
Each fold:
  - fit ridge on earlier completed seasons;
  - fixed alpha=100, no alpha sweep on evaluation outcomes;
  - fit residual bias/sigma on earlier calibration block;
  - score strictly later games;
  - 7-day embargo between calibration and evaluation;
  - 1d vs 2d vs 3d score-publication lag scenarios.
No historical bookmaker prices are used or inferred.
"""
from __future__ import annotations
import argparse,json,math
from collections import defaultdict
from datetime import date, timedelta, datetime,timezone
from pathlib import Path
import numpy as np

import nba_chronological_backtest as B

FOLDS=[
    {"name":"development_2023_24","train":("2022-23",),"cal_start":"2024-01-01",
     "cal_end":"2024-02-15","eval_start":"2024-02-23","eval_end":"2024-04-14"},
    {"name":"development_2024_25","train":("2022-23","2023-24"),
     "cal_start":"2025-01-01","cal_end":"2025-02-15",
     "eval_start":"2025-02-23","eval_end":"2025-04-13"},
]
ALPHA=100.0
LAGS=(1,2,3)
MODEL=("baseline","form","form_h2h")

def asof_rows(games,lag_days):
    """Build candidate prior game features only after date-lag_days is reached."""
    byday=defaultdict(list)
    for g in games:byday[g["date"]].append(g)
    team_hist=defaultdict(list);pair_hist=defaultdict(list)
    waiting=defaultdict(list)
    result=[]
    for day in sorted(byday):
        today=date.fromisoformat(day)
        for old in sorted(list(waiting)):
            if date.fromisoformat(old)+timedelta(days=lag_days)<=today:
                for g in waiting.pop(old):
                    team_hist[g["home"]].append(B.team_entry(g,g["home"]))
                    team_hist[g["away"]].append(B.team_entry(g,g["away"]))
                    pair_hist[tuple(sorted((g["home"],g["away"])))].append(g)
        for g in byday[day]:
            vals=B.features(g,team_hist,pair_hist)
            if vals is None:continue
            used=vals["proof"]["max_input_game_date"]
            if not date.fromisoformat(used)+timedelta(days=lag_days)<=today:
                raise AssertionError("LOOKAHEAD_DATA_PUBLICATION_LAG")
            result.append({"date":day,"season":g["season"],"home":g["home"],"away":g["away"],
                "game_id":f"{day}:{g['home']}:{g['away']}",
                "form":vals["form"],"h2h":vals["h2h"],"proof":vals["proof"],
                "margin":float(g["margin_home"]),"total":float(g["total"])})
        waiting[day].extend(byday[day])
    return result

def score(rows,target,variant,model,calibration):
    mu=B.predict(rows,variant,model)+calibration["residual_bias"]
    sigma=calibration["sigma"]
    y=np.asarray([g[target] for g in rows],dtype=float)
    p=np.array([B.p_greater(x,sigma,0.5 if target=="margin" else B.TOTAL_LINE) for x in mu])
    truth=(y>(0.5 if target=="margin" else B.TOTAL_LINE)).astype(float)
    return {"n":len(rows),"MAE":float(np.mean(abs(mu-y))),
      "Brier":B.brier(p,truth),"log_loss":B.logloss(p,truth),
      "ECE10":B.ece(p,truth)}

def run(out):
    games,rej,sources=B.extract_history(date(2026,10,29))
    results={}
    for lag in LAGS:
        rows=asof_rows(games,lag)
        folds=[]
        for f in FOLDS:
            tr=[r for r in rows if r["season"] in f["train"]]
            cal=[r for r in rows if f["cal_start"]<=r["date"]<=f["cal_end"]]
            ev=[r for r in rows if f["eval_start"]<=r["date"]<=f["eval_end"]]
            assert tr and cal and ev
            if len(tr)<900 or len(cal)<100 or len(ev)<100:
                raise RuntimeError("Incomplete chronological fold samples")
            assert max(r["date"] for r in tr)<min(r["date"] for r in cal)
            assert max(r["date"] for r in cal)<min(r["date"] for r in ev)
            assert (date.fromisoformat(min(r["date"] for r in ev))-
                    date.fromisoformat(max(r["date"] for r in cal))).days>=8
            fm={}
            for variant in MODEL:
                fm[variant]={}
                for target in ("margin","total"):
                    m=B.train_ridge(tr,target,variant,ALPHA if variant!="baseline" else 0)
                    resid=np.array([x[target] for x in cal],dtype=float)-B.predict(cal,variant,m)
                    bias=float(resid.mean())
                    z={"residual_bias":bias,"sigma":max(1.0,float(np.sqrt(np.mean((resid-bias)**2))))}
                    fm[variant][target]=score(ev,target,variant,m,z)
            folds.append({"name":f["name"],"period":f,
                "train_size":len(tr),"cal_size":len(cal),"eval_size":len(ev),
                "models":fm,
                "provenance_lag_pass":all(date.fromisoformat(x["proof"]["max_input_game_date"])+timedelta(days=lag)<=date.fromisoformat(x["date"]) for x in ev)})
        results[str(lag)]={"folds":folds}
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "purpose":"DEVELOPMENT_ROBUSTNESS_NOT_NEW_UNSEEN_HOLDOUT",
        "public_results_used_through":"2026-10-29",
        "alpha_frozen":ALPHA,
        "publication_delay_days":list(LAGS),
        "folds":results,
        "source_shas":sources,
        "notes":["The 2025-26 holdout was already examined previously; this script refuses to treat it as a newly blind holdout.",
                 "These expanding folds are development diagnostics. They must not be used to reselect the model based on 2025-26 outcomes.",
                 "Source CSV lacks original publication timestamp; +2/+3 day lag tests conservative robustness, not point-in-time data availability proof.",
                 "No historical bookmaker odds or EV included, no picks."]}
    Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"purpose":report["purpose"],
      "folds":[{"lag":lag,"name":v["name"],"n":v["eval_size"],
                "baseline_margin_mae":v["models"]["baseline"]["margin"]["MAE"],
                "form_margin_mae":v["models"]["form"]["margin"]["MAE"],
                "form_h2h_margin_mae":v["models"]["form_h2h"]["margin"]["MAE"],
                "form_h2h_total_brier":v["models"]["form_h2h"]["total"]["Brier"]}
               for lag,z in results.items() for v in z["folds"]]},ensure_ascii=False,indent=2))
    return report

def self_test():
    g=[]
    for i in range(1,12):
        d=(date(2023,1,1)+timedelta(days=i)).isoformat()
        g.append({"date":d,"home":"ATL" if i%2 else "MIA","away":"MIA" if i%2 else "ATL",
            "season":"2022-23","home_points":100+i,"away_points":90,
            "margin_home":10+i,"total":190+i,
            "home_possessions_est":99.5,"away_possessions_est":100.5,"pace_est":100})
    d1=asof_rows(g,1);d3=asof_rows(g,3)
    assert d1 and d3
    assert d1[0]["date"]<d3[0]["date"]
    assert all(date.fromisoformat(x["proof"]["max_input_game_date"])+timedelta(days=3)<=date.fromisoformat(x["date"]) for x in d3)
    # Future outcomes cannot influence features for earlier game.
    changed=[dict(x) for x in g];changed[-1]["home_points"]=200
    assert asof_rows(g,3)[-1]["form"]==asof_rows(changed,3)[-1]["form"]
    print("LAGGED_WALKFORWARD_ANTI_LEAK_TEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",default="nba_development_lag_walkforward.json")
    a=p.parse_args()
    if a.self_test:self_test()
    else:run(a.out)
