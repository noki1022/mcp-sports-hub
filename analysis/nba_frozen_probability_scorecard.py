#!/usr/bin/env python3
"""Score PRETIP frozen independent NBA probabilities against official Final scores.

Retrospective metrics do not update forecasts. No odds interpolation, no assumed
moneyline ROI, and no games counted before official completion.
Historical predictions are read only from frozen reports/daily/<day>/<slot>.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from datetime import datetime
from nba_nightly_two_market_settlement import scores_for

def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))

def score(frozen,scores,day,slot):
    if frozen.get("target_display_date")!=day:
        raise ValueError("FROZEN_DATE_MISMATCH")
    rows=[]
    seen=set()
    for g in frozen.get("games",[]):
        gid=str(g.get("game_id") or "")
        if not gid or gid in seen:raise ValueError("INVALID_OR_DUPLICATE_FROZEN_ID")
        seen.add(gid)
        p=(g.get("model_probability") or {}).get("home")
        try:p=float(p)
        except (TypeError,ValueError):p=float("nan")
        if not math.isfinite(p) or not 0<=p<=1:
            rows.append({"game_id":gid,"status":"EXCLUDED_INVALID_MODEL_PROBABILITY"})
            continue
        eid=str(g.get("nba_game_id") or "")
        q=scores.get(eid) or {}
        # Never guess an event ID from matchup or display order.
        if not eid:
            rows.append({"game_id":gid,"status":"EXCLUDED_NO_VERIFIED_EVENT_ID"})
            continue
        if q.get("completed") is not True or not all(isinstance(q.get(k),int) and not isinstance(q.get(k),bool) and q[k]>=0 for k in ("home_points","away_points")):
            rows.append({"game_id":gid,"status":"UNSETTLED_OFFICIAL_FINAL_MISSING"})
            continue
        home,away=q["home_points"],q["away_points"]
        if home==away:
            rows.append({"game_id":gid,"status":"EXCLUDED_TIED_FINAL_INVALID_NBA"})
            continue
        outcome=int(home>away)
        safe_p=max(1e-12,min(1-1e-12,p))
        rows.append({"game_id":gid,"nba_game_id":eid,"status":"SCORED",
            "home_win_probability_frozen":p,"home_win_actual":outcome,
            "brier":(p-outcome)**2,
            "log_loss":-(outcome*math.log(safe_p)+(1-outcome)*math.log1p(-safe_p)),
            "predicted_home_win":p>0.5,
            "prediction_correct":int((p>0.5)==bool(outcome)),
            "home_score":home,"away_score":away,
            "model_calibration_evidence":g.get("model_calibration_evidence")})
    scored=[r for r in rows if r["status"]=="SCORED"]
    def avg(k):return round(sum(x[k] for x in scored)/len(scored),7) if scored else None
    bins=[]
    for i in range(10):
        sub=[x for x in scored if (i/10<=x["home_win_probability_frozen"]<(i+1)/10) or (i==9 and x["home_win_probability_frozen"]==1)]
        bins.append({"lower":i/10,"upper":(i+1)/10,"n":len(sub),
          "mean_probability":round(sum(x["home_win_probability_frozen"] for x in sub)/len(sub),6) if sub else None,
          "realized_home_win":round(sum(x["home_win_actual"] for x in sub)/len(sub),6) if sub else None})
    return {"schema_version":"nba-frozen-probability-scorecard-v1","date":day,
      "slot":slot,"games":rows,"n":len(scored),"pending":sum(x["status"].startswith("UNSETTLED") for x in rows),
      "excluded":sum(x["status"].startswith("EXCLUDED") for x in rows),
      "brier":avg("brier"),"log_loss":avg("log_loss"),
      "accuracy":avg("prediction_correct"),"calibration_bins":bins,
      "score_policy":"Independent frozen pretip probabilities + verified official Final only",
      "odds_used_as_features":False,"no_model_retraining":True,
      "no_ev_or_roi_claims":True}

def test():
    data={"target_display_date":"2026-10-31","games":[
      {"game_id":"a","nba_game_id":"101","model_probability":{"home":0.099}},
      {"game_id":"b","nba_game_id":"102","model_probability":{"home":0.8}},
      {"game_id":"c","nba_game_id":"103","model_probability":{"home":0.9}}]}
    finals={"101":{"completed":True,"home_points":99,"away_points":110},
            "102":{"completed":True,"home_points":120,"away_points":110},
            "103":{"completed":False}}
    output=score(data,finals,"2026-10-31","0630")
    assert output["n"]==2 and output["pending"]==1
    assert output["accuracy"]==1.0
    expected=((0.099-0)**2+(.8-1)**2)/2
    assert abs(output["brier"]-expected)<1e-6
    # A 9.9% model forecast can be correct despite odds and must be evaluated fairly.
    assert output["games"][0]["brier"]<0.01
    assert score(data,{}, "2026-10-31","0630")["n"]==0
    try:score(data,finals,"2026-10-30","0630")
    except ValueError:pass
    else:raise AssertionError("DATE_MISMATCH_NOT_CAUGHT")
    print("NBA_FROZEN_PROBABILITY_SCORECARD_TEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--frozen");ap.add_argument("--scores");ap.add_argument("--day")
    ap.add_argument("--slot",choices=("2130","0630"))
    ap.add_argument("--out");ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:test()
    else:
        if not all((a.frozen,a.day,a.slot,a.out)):raise SystemExit("MISSING_INPUT")
        result=score(load(a.frozen),load(a.scores) if a.scores else scores_for(a.day),a.day,a.slot)
        Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("NBA_FROZEN_PROBABILITY_SCORECARD",a.day,a.slot,"GRADED",result["n"],
              "PENDING",result["pending"],"BRIER",result["brier"])
