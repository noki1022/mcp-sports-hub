#!/usr/bin/env python3
"""2022-24 replacement features vs ACTUAL production rolling fitter.

Use existing production ridge+Elo+isotonic fitter; injury terms only in
separately frozen pre-test margin residual and calibrated-probability layer.
Uses genuine archived game IDs, no fabricated odds or causal player catalog.
Historical report version is nominal, not proven first HTTP publication time.
"""
import argparse,json,math
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np
from nba_early_injury_replacement_study import main as early_pairs, ridge, pred
from nba_chronological_backtest import extract_history,p_greater,brier,logloss,ece
from nba_independent_predictions import (_rows_with_dynamic_strength,_fit_production_model,
    _predict_extended,_isotonic_predict,_isotonic_fit,MODEL_VERSION)
def evaluate(data,col):
    y=np.asarray([float(z["margin"]>0) for z in data])
    p=np.asarray([z[col+"_p"] for z in data])
    mu=np.asarray([z[col+"_mu"] for z in data])
    actual=np.asarray([z["margin"] for z in data])
    return {"Brier":float(brier(p,y)),"LogLoss":float(logloss(p,y)),
       "ECE10":float(ece(p,y)),"margin_MAE":float(np.mean(abs(mu-actual)))}
def confidence(data,key):
    grp=defaultdict(list)
    dif=np.array([r[key] for r in data])
    for i,r in enumerate(data):grp[r["date"]].append(i)
    groups=list(grp.values());rng=np.random.default_rng(20261031);boot=[]
    for _ in range(500):
        indices=np.concatenate([groups[int(j)] for j in rng.integers(0,len(groups),len(groups))])
        boot.append(float(np.mean(dif[indices])))
    return {"delta":float(dif.mean()),"CI95":[float(np.quantile(boot,.025)),float(np.quantile(boot,.975))],
            "dates":len(groups)}
def run(out):
    pairs,identity,old=early_pairs("/tmp/p0-early-replacement-source-evidence.json",return_paired=True)
    byfixture={}
    for sample,(day,g,home,away) in zip(pairs,identity):
        k=(day,home,away)
        if k in byfixture:raise AssertionError("DUPLICATE_FIXTURE")
        byfixture[k]={"date":day,"nba_game_id":g,"home":home,"away":away,
                      "margin":sample[1],"injury_x":np.array(sample[3][2:],float)}
    games,_,_=extract_history(date(2026,10,29))
    production=_rows_with_dynamic_strength(games)
    bydate=defaultdict(list)
    for r in production:
        k=(r["date"],r["home"],r["away"])
        if k in byfixture and r["date"]<"2024-04-15":
            if abs(float(r["margin"])-float(byfixture[k]["margin"]))>0.1:
                raise AssertionError("HOME_AWAY_SCORE_OR_GAME_ID_MISMATCH")
            bydate[r["date"]].append((r,byfixture[k]))
    shadow=[]
    for day in sorted(bydate):
        try:fits,cal,meta=_fit_production_model(production,date.fromisoformat(day))
        except (ValueError,RuntimeError):continue
        if meta["calibration_through"]>=day:raise AssertionError("PRODUCTION_MODEL_LEAK")
        for r,inp in bydate[day]:
            mu=float(_predict_extended([r],fits["margin"])[0]+cal["margin"]["residual_bias"])
            sig=float(cal["margin"]["sigma"])
            raw=p_greater(mu,sig,0.)
            baseline=float(_isotonic_predict(cal["moneyline_isotonic"],raw))
            shadow.append({**inp,"production_mu":mu,"production_p":baseline,"sigma":sig,
                           "production_model_calibration_end":meta["calibration_through"]})
    fit=[r for r in shadow if r["date"]<"2023-02-01"]
    cal=[r for r in shadow if "2023-02-08"<=r["date"]<="2023-04-09"]
    test=[r for r in shadow if "2023-10-24"<=r["date"]<="2024-04-15"]
    report={"status":"BLOCKED_INSUFFICIENT_PRODUCTION_MATCHED_GAMES",
        "production_algorithm":MODEL_VERSION,
        "same_production_rolling_fitter":True,
        "source_early_archive_status":old["status"],
        "counts":{"matched_replay":len(shadow),"injury_fit":len(fit),"injury_cal":len(cal),"later_test":len(test)},
        "nominal_report_clock_not_verified_publication":True,
        "2023_24_test_previously_inspected":True,
        "historical_true_007_lines_missing":True,
        "validated_individual_player_values":False,
        "production_approval":False}
    if len(fit)>=150 and len(cal)>=80 and len(test)>=400:
        x=np.asarray([r["injury_x"] for r in fit])
        y=np.asarray([r["margin"]-r["production_mu"] for r in fit])
        correction=ridge(x,y,150)
        cc=np.asarray([r["injury_x"] for r in cal])
        cc_delta=pred(cc,correction)
        cx=[p_greater(r["production_mu"]+float(v),r["sigma"],0) for r,v in zip(cal,cc_delta)]
        neutral=[p_greater(r["production_mu"],r["sigma"],0) for r in cal]
        yy=[float(r["margin"]>0) for r in cal]
        iso_inj=_isotonic_fit(cx,yy)
        iso_ctrl=_isotonic_fit(neutral,yy)
        for r in test:
            shift=float(np.clip(pred(np.asarray([r["injury_x"]]),correction)[0],-8.,8.))
            r["injury_mu"]=r["production_mu"]+shift
            r["injury_p"]=float(_isotonic_predict(iso_inj,p_greater(r["injury_mu"],r["sigma"],0)))
            r["recalibration_mu"]=r["production_mu"]
            r["recalibration_p"]=float(_isotonic_predict(iso_ctrl,p_greater(r["production_mu"],r["sigma"],0)))
            truth=float(r["margin"]>0)
            r["injury_specific_Brier_delta"]=(r["injury_p"]-truth)**2-(r["recalibration_p"]-truth)**2
            r["injury_vs_production_Brier_delta"]=(r["injury_p"]-truth)**2-(r["production_p"]-truth)**2
            r["injury_margin_MAE_delta"]=abs(r["injury_mu"]-r["margin"])-abs(r["production_mu"]-r["margin"])
        report["metrics"]={key:evaluate(test,key) for key in ("production","recalibration","injury")}
        report["paired_CI"]={k:confidence(test,k) for k in ("injury_specific_Brier_delta",
                           "injury_vs_production_Brier_delta","injury_margin_MAE_delta")}
        report["status"]="SAME_PRODUCTION_2022_24_REPLACEMENT_RESEARCH_COMPLETED_NO_AUTOPROMOTION"
    Path(out).write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print("P0_REPLACEMENT_PRODUCTION_REPLAY",json.dumps(report,ensure_ascii=False)[:11000])
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True);args=p.parse_args();run(args.out)
