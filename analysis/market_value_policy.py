#!/usr/bin/env python3
"""Fail-closed value decision policy for calibrated model versus de-vig market.

The policy is disabled by default until historical odds settlement coverage has
been validated. Enabling it requires an explicit workflow flag.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

def evaluate(decision, enabled=False, min_edge=0.03):
    rows, candidates = [], []
    for row in decision.get("rows", []):
        reasons = []
        if row.get("model_status") != "VALIDATED_OUT_OF_SAMPLE":
            reasons.append("MODEL_NOT_VALIDATED")
        if row.get("market_status") != "OK":
            reasons.append("MARKET_NOT_OK")
        if not row.get("direction_verified"):
            reasons.append("MARKET_SIDE_DIRECTION_UNVERIFIED")
        e1, e2 = row.get("edge_side1"), row.get("edge_side2")
        best = max([(abs(e1), "SIDE1", e1), (abs(e2), "SIDE2", e2)],
                   key=lambda x: x[0] if x[0] is not None else -1) if e1 is not None or e2 is not None else None
        if not enabled:
            reasons.append("POLICY_DISABLED_PENDING_HISTORICAL_ODDS")
        elif best is None or best[0] < min_edge:
            reasons.append("EDGE_BELOW_MINIMUM")
        recommendation = "NO_BET"
        if enabled and not reasons and best:
            recommendation = "VALUE_CANDIDATE_" + best[1]
            candidates.append({**row, "recommendation": recommendation, "edge": best[2]})
        rows.append({**row, "policy_reasons": reasons, "recommendation": recommendation})
    return {
        "schema_version": "market-value-policy-v1",
        "enabled": enabled,
        "minimum_edge": min_edge,
        "historical_odds_validation_required": True,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "rows": rows,
        "decision": "NO_BET" if not candidates else "VALUE_CANDIDATE_REQUIRES_REVIEW",
    }

def self_test():
    base = {"rows": [{
        "game_id": "1", "market": "full_spread", "market_status": "OK",
        "model_status": "VALIDATED_OUT_OF_SAMPLE", "direction_verified": True,
        "edge_side1": 0.04, "edge_side2": -0.04
    }]}
    assert evaluate(base)["candidate_count"] == 0
    x = evaluate(base, enabled=True)
    assert x["candidate_count"] == 1 and x["decision"].startswith("VALUE_CANDIDATE")
    print("MARKET_VALUE_POLICY_SELF_TEST_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market-decision")
    ap.add_argument("--out", default="market_value_policy.json")
    ap.add_argument("--enable", action="store_true")
    ap.add_argument("--min-edge", type=float, default=0.03)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
    else:
        if not a.market_decision: raise SystemExit("--market-decision is required")
        decision = json.loads(Path(a.market_decision).read_text(encoding="utf-8"))
        result = evaluate(decision, enabled=a.enable, min_edge=a.min_edge)
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"out": a.out, "candidate_count": result["candidate_count"], "decision": result["decision"]}, ensure_ascii=False))
