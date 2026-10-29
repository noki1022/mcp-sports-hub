#!/usr/bin/env python3
"""Discrete normal settlement probabilities for Asian basketball lines."""
from __future__ import annotations
import math

def _cdf(x, mu, sigma):
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))

def _mass(x, mu, sigma):
    return max(0.0, _cdf((x + 0.5 - mu) / 1.0, 0.0, sigma) -
            _cdf((x - 0.5 - mu) / 1.0, 0.0, sigma))

def _leg(value, line, side1):
    if value > line:
        result = "win"
    elif value < line:
        result = "loss"
    else:
        result = "push"
    return result if side1 else {"win": "loss", "loss": "win", "push": "push"}[result]

def settlement_probs(line, mu, sigma, side1=True, lo=-120, hi=400):
    """Return full/half win-loss and push probabilities for a line.

    Quarter lines are split into their two adjacent half/integer legs. The
    distribution is over integer final margins or totals, so a push can only
    occur on an integer leg.
    """
    line = float(line)
    sigma = float(sigma)
    if not math.isfinite(line) or not math.isfinite(mu) or sigma <= 0:
        raise ValueError("finite line/mu and positive sigma required")
    q = round(line * 4)
    if abs(q / 4.0 - line) > 1e-9:
        raise ValueError("line must be quarter-line precision")
    if q % 2 == 0:
        legs = [line]
    else:
        legs = [math.floor(line * 2) / 2, math.ceil(line * 2) / 2]
    out = {"full_win": 0.0, "half_win": 0.0, "push": 0.0,
           "half_loss": 0.0, "full_loss": 0.0}
    for value in range(int(lo), int(hi) + 1):
        p = _mass(value, mu, sigma)
        results = [_leg(value, leg, side1) for leg in legs]
        if len(results) == 1:
            key = {"win": "full_win", "push": "push", "loss": "full_loss"}[results[0]]
        elif results.count("win") == 2:
            key = "full_win"
        elif results.count("loss") == 2:
            key = "full_loss"
        elif results.count("push") == 2:
            key = "push"
        elif "win" in results and "push" in results:
            key = "half_win"
        elif "loss" in results and "push" in results:
            key = "half_loss"
        else:
            raise AssertionError("unexpected split settlement")
        out[key] += p
    z = sum(out.values())
    if z <= 0:
        raise ValueError("probability mass underflow")
    return {k: v / z for k, v in out.items()}

def self_test():
    x = settlement_probs(3.5, 3.5, 15)
    assert abs(x["full_win"] - .5) < 1e-9
    assert x["push"] == 0
    q25 = settlement_probs(3.25, 3.0, 10)
    q75 = settlement_probs(3.75, 3.0, 10)
    assert q25["half_loss"] > 0 and q75["half_win"] > 0
    assert abs(sum(q25.values()) - 1) < 1e-9
    print("NBA_SETTLEMENT_PROBABILITIES_SELF_TEST_PASS")

if __name__ == "__main__":
    self_test()
