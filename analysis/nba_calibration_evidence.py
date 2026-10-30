#!/usr/bin/env python3
"""Explain sample support of odds-blind isotonic probabilities (NO forecast rewrite).

Reference: scikit-learn calibration guide warns isotonic overfits on small data.
This diagnostic ONLY measures historical calibration support. It never reads
bookmaker prices, changes a win probability, or changes focus ranking.
"""
from __future__ import annotations
import math

def finite(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def evidence(model, raw, calibrated):
    p,q=finite(raw),finite(calibrated)
    out={"status":"UNAVAILABLE","odds_as_features":False,
         "modifies_probability":False,"sample_n":None,"nearest_knot_n":None,
         "nearby_5pp_samples":None,"outside_training_range":None,
         "calibration_shift_pp":None,"warnings":[]}
    if p is None or q is None or not 0<=p<=1 or not 0<=q<=1:
        out["warnings"].append("INVALID_OR_MISSING_PROBABILITY")
        return out
    out["calibration_shift_pp"]=round(100*(q-p),2)
    if not model:
        out["warnings"].append("NO_ISOTONIC_SUPPORT_METADATA")
        return out
    xs=model.get("probability_knots") or []
    intervals=model.get("knot_input_probability_ranges") or []
    ns=model.get("knot_sample_counts") or []
    if not xs or len(xs)!=len(ns) or len(xs)!=len(intervals):
        out["warnings"].append("CALIBRATION_KNOT_SUPPORT_UNAVAILABLE")
        return out
    if not all(n and n>0 for n in ns):
        out["warnings"].append("INVALID_CALIBRATION_COUNTS")
        return out
    out["status"]="AUDITED"
    out["sample_n"]=sum(ns)
    out["nearest_knot_n"]=ns[min(range(len(xs)),key=lambda i:abs(xs[i]-p))]
    out["nearby_5pp_samples"]=int(sum(n for (lo,hi),n in zip(intervals,ns)
                                    if lo<=p+0.05 and hi>=p-0.05))
    out["outside_training_range"]=p<min(k[0] for k in intervals) or p>max(k[1] for k in intervals)
    if out["outside_training_range"]:
        out["warnings"].append("EXTRAPOLATED_OUTSIDE_CALIBRATION_RANGE")
    if q in (0.0,1.0):
        out["warnings"].append("ISOTONIC_0_OR_100_PERCENT_ENDPOINT")
    if abs(q-p)>=0.15:
        out["warnings"].append("CALIBRATION_SHIFT_GE_15PP")
    if out["sample_n"]<1000:
        out["warnings"].append("ISOTONIC_LT_1000_TOTAL_SAMPLES_OVERFIT_RISK")
    if out["nearest_knot_n"]<20:
        out["warnings"].append("NEAREST_KNOT_LT_20_SAMPLES")
    # Counts and diagnostics are observational; not hard selection thresholds.
    return out

def self_test():
    m={"probability_knots":[0.2,0.7],"rate_knots":[0,1],
       "knot_input_probability_ranges":[[0.1,0.3],[0.6,0.8]],
       "knot_sample_counts":[8,32]}
    e=evidence(m,0.05,0.0)
    assert e["status"]=="AUDITED" and e["sample_n"]==40
    assert e["outside_training_range"] is True and e["nearest_knot_n"]==8
    assert "ISOTONIC_0_OR_100_PERCENT_ENDPOINT" in e["warnings"]
    assert "ISOTONIC_LT_1000_TOTAL_SAMPLES_OVERFIT_RISK" in e["warnings"]
    assert evidence(m,0.5,0.6)["calibration_shift_pp"]==10
    assert evidence(None,0.099,0.099)["status"]=="UNAVAILABLE"
    assert not evidence(m,0.4,0.3)["modifies_probability"]
    print("NBA_CALIBRATION_EVIDENCE_SELF_TEST_PASS")

if __name__=="__main__":self_test()
