#!/usr/bin/env python3
"""Research-only chronological market baseline on independently score-matched SBR games.

No trained model, no betting profitability claim, no raw file persisted.
Closing odds may be compared with results, not used as an earlier prediction.
"""
import math
from collections import defaultdict
from datetime import date
from nba_archive_crosscheck import (LINE_SHEET, SBR_BASE, SEASONS, bounded_fetch,
                                     line_sheet_audit, sbr_season_audit)
from sbr_archive_import import transform, rows_from_grid
import csv, io, hashlib, json

def brier(ps,ys):
    return sum((p-y)**2 for p,y in zip(ps,ys))/len(ps) if ps else None
def logloss(ps,ys):
    return sum(-y*math.log(max(1e-12,min(1-1e-12,p)))-(1-y)*math.log(max(1e-12,min(1-1e-12,1-p))) for p,y in zip(ps,ys))/len(ps) if ps else None

def main():
    reference,_=line_sheet_audit(bounded_fetch(LINE_SHEET))
    by_season=defaultdict(list)
    unmatched=0
    for season in SEASONS:
        blob=bounded_fetch(SBR_BASE+season+".csv")
        parsed=transform(rows_from_grid(csv.reader(io.StringIO(blob.decode("utf-8-sig")))),season,hashlib.sha256(blob).hexdigest())
        for g in parsed["games"]:
            key=(g["date"],g["home"],g["away"])
            ref=reference.get(key)
            if ref is None or (ref["home_points"],ref["away_points"])!=(g["home_points"],g["away_points"]):
                unmatched+=1
                continue
            by_season[season].append((g["close_home_ml_no_vig"],int(g["home_points"]>g["away_points"])))
    seasons=[]
    for season in SEASONS:
        values=by_season[season]
        ps=[x[0] for x in values]; ys=[x[1] for x in values]
        seasons.append({"season":season,"games":len(values),"closing_market_brier":round(brier(ps,ys),6) if ps else None,
                        "closing_market_log_loss":round(logloss(ps,ys),6) if ps else None,
                        "home_win_rate":round(sum(ys)/len(ys),6) if ys else None})
    allrows=[r for season in SEASONS for r in by_season[season]]
    p=[r[0] for r in allrows];y=[r[1] for r in allrows]
    print("MARKET_BENCHMARK_VERDICT "+json.dumps({"status":"RESEARCH_ONLY","games":len(p),
      "unmatched_excluded":unmatched,"closing_market_brier":round(brier(p,y),6),
      "closing_market_log_loss":round(logloss(p,y),6),"seasons":seasons,
      "no_model_trained":True,"no_roi_claim":True,"no_raw_data_persisted":True},sort_keys=True))
    assert len(p)>5000 and unmatched>=0

if __name__=="__main__":
    main()
