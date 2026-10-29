#!/usr/bin/env python3
"""Reliability diagnostics for frozen NBA holdout probabilities."""
from __future__ import annotations
import argparse, csv, json, math, random
from collections import defaultdict
from pathlib import Path

def wilson(successes, n, z=1.959963984540054):
    if n <= 0:
        return [None, None]
    p = successes / n
    d = 1 + z*z/n
    center = (p + z*z/(2*n)) / d
    half = z * math.sqrt((p*(1-p) + z*z/(4*n))/n) / d
    return [max(0.0, center-half), min(1.0, center+half)]

def reliability(rows, prob_key, truth_key, bins=10):
    out = []
    for b in range(bins):
        lo, hi = b/bins, (b+1)/bins
        selected = [r for r in rows if lo <= r[prob_key] < hi or
                    (b == bins-1 and r[prob_key] <= hi)]
        n = len(selected)
        hits = sum(r[truth_key] for r in selected)
        out.append({
            "bin": b, "lower": lo, "upper": hi, "n": n,
            "mean_predicted": sum(r[prob_key] for r in selected)/n if n else None,
            "observed_rate": hits/n if n else None,
            "observed_rate_wilson_95": wilson(hits, n),
            "absolute_calibration_gap": abs(sum(r[prob_key] for r in selected)/n - hits/n) if n else None,
        })
    return out

def cluster_bootstrap_brier(rows, prob_key, truth_key, reps=1000):
    groups = defaultdict(list)
    for r in rows:
        groups[r["date"]].append(r)
    days = sorted(groups)
    if not days:
        return {"estimate": None, "ci95": [None, None], "days": 0}
    observed = sum((r[prob_key]-r[truth_key])**2 for r in rows)/len(rows)
    rng = random.Random(20261029)
    stats = []
    for _ in range(reps):
        sample = [r for _ in days for r in groups[days[rng.randrange(len(days))]]]
        stats.append(sum((r[prob_key]-r[truth_key])**2 for r in sample)/len(sample))
    stats.sort()
    return {"estimate": observed, "ci95": [stats[int(.025*len(stats))], stats[int(.975*len(stats))-1]],
            "days": len(days), "resamples": reps}

def load(path, variant="form_h2h"):
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for x in csv.DictReader(f):
            rows.append({
                "date": x["date"],
                "p_home": float(x[f"{variant}_p_home"]),
                "y_home": float(float(x["actual_margin"]) > .5),
                "p_over": float(x[f"{variant}_p_over225_5"]),
                "y_over": float(float(x["actual_total"]) > 225.5),
            })
    return rows

def diagnose(path, variant="form_h2h"):
    rows = load(path, variant)
    return {
        "schema_version": "nba-reliability-diagnostics-v1",
        "variant": variant, "n": len(rows),
        "moneyline_home": {
            "reliability_bins": reliability(rows, "p_home", "y_home"),
            "calendar_day_cluster_brier": cluster_bootstrap_brier(rows, "p_home", "y_home"),
        },
        "total_over_225_5": {
            "reliability_bins": reliability(rows, "p_over", "y_over"),
            "calendar_day_cluster_brier": cluster_bootstrap_brier(rows, "p_over", "y_over"),
        },
        "decision": "NO_BET",
        "odds_used": False,
    }

def self_test():
    p = Path("/tmp/reliability.csv")
    p.write_text("date,actual_margin,actual_total,form_h2h_p_home,form_h2h_p_over225_5\n"
                 "2026-01-01,10,230,0.8,0.7\n"
                 "2026-01-02,-5,220,0.2,0.3\n", encoding="utf-8")
    out = diagnose(p)
    assert out["n"] == 2
    assert len(out["moneyline_home"]["reliability_bins"]) == 10
    assert out["moneyline_home"]["calendar_day_cluster_brier"]["ci95"][0] <= out["moneyline_home"]["calendar_day_cluster_brier"]["estimate"]
    print("NBA_RELIABILITY_DIAGNOSTICS_SELF_TEST_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions")
    ap.add_argument("--variant", default="form_h2h")
    ap.add_argument("--out", default="nba_reliability_diagnostics.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
    else:
        if not a.predictions: raise SystemExit("--predictions is required")
        Path(a.out).write_text(json.dumps(diagnose(a.predictions, a.variant), ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"out": a.out, "decision": "NO_BET"}, ensure_ascii=False))
