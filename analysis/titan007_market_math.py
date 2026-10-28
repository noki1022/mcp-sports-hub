#!/usr/bin/env python3
"""Transparent handicap/total math for Hong Kong basketball odds.

The first spread column is interpreted as HOME-cover (raw positive = home gives)
only after independent same-game sportsbook direction verification.
The first total column is interpreted as OVER; if not directly verified, side
labels must remain provisional.

No stake sizing or wagering actions are performed.
"""
from __future__ import annotations
import math

def hk_decimal(hk):
    if hk is None or not math.isfinite(float(hk)) or float(hk) <= 0:
        raise ValueError("Missing or invalid positive HK odds")
    return 1.0 + float(hk)

def devig(hk1,hk2):
    d1,d2=hk_decimal(hk1),hk_decimal(hk2)
    q1,q2=1/d1,1/d2
    z=q1+q2
    return {
        "decimal_side1":d1,
        "decimal_side2":d2,
        "raw_implied_side1":q1,
        "raw_implied_side2":q2,
        "overround":z-1,
        "no_vig_conditional_side1":q1/z,
        "no_vig_conditional_side2":q2/z,
        "push_handling":"Conditional on the market producing a non-push settlement; push probability requires an independent margin/total model",
    }

def cdf(x,mu,sigma):
    if sigma <= 0 or not math.isfinite(sigma):raise ValueError("sigma must be positive")
    return 0.5*(1+math.erf((x-mu)/(sigma*math.sqrt(2))))

def legs(line):
    q=round(line*4)
    if abs(q/4-line)>1e-8:raise ValueError("Unknown quarter-line convention")
    # Asian quarter line splits into adjacent integer and half-line markets.
    if q%2:
        return [math.floor(line*2)/2,math.ceil(line*2)/2]
    return [line]

def discrete_right(rounded_integer_line,mu,sigma):
    # For integer basketball totals/margins: P(X>line), P(X==line), P(X<line)
    # approximate mass of integer x by a continuous normal from x-.5 to x+.5.
    upper=math.floor(rounded_integer_line)+1
    lower=math.ceil(rounded_integer_line)-1
    pwin=1-cdf(upper-0.5,mu,sigma)
    ploss=cdf(lower+0.5,mu,sigma)
    ppush=max(0.0,1-pwin-ploss)
    return {"win":pwin,"loss":ploss,"push":ppush}

def outcome_probs(line,mu,sigma,side1=True):
    """Side 1 wins if integer result > line; side2 wins if integer result < line."""
    components=[discrete_right(x,mu,sigma) for x in legs(float(line))]
    mass={k:sum(r[k] for r in components)/len(components) for k in ("win","loss","push")}
    if not side1:mass={"win":mass["loss"],"loss":mass["win"],"push":mass["push"]}
    # Quarter line push is mathematically half-push; here the 2-leg mixture
    # preserves correct net EV, not a literal all-or-nothing probability.
    mass["quarter_split"]=(len(components)==2)
    return mass

def market_ev(hk,prob):
    w=float(hk)
    return w*prob["win"]-prob["loss"]

def evaluate(line,hk1,hk2,mu,sigma):
    baseline=devig(hk1,hk2)
    p1=outcome_probs(line,mu,sigma,True)
    p2=outcome_probs(line,mu,sigma,False)
    return {**baseline,"line":line,
        "model_side1":p1,
        "model_side2":p2,
        "diagnostic_ev_side1":market_ev(hk1,p1),
        "diagnostic_ev_side2":market_ev(hk2,p2),
        "model_assumptions":{"mu":mu,"sigma":sigma,"distribution":"normal approximation to discrete NBA scores","calibrated":False},
        "note":"EV is experimental: do not interpret as verified value until advanced efficiency, availability, and historical calibration are validated",
    }

def self_test():
    d=devig(.86,1.00)
    assert abs(d["no_vig_conditional_side1"]-.5181347150259068)<1e-10
    assert abs(d["overround"]-.0376344086021505)<1e-10
    assert legs(3.25)==[3.0,3.5]
    assert legs(-4.75)==[-5.0,-4.5]
    p=outcome_probs(3.5,3.5,15)
    assert p["push"]==0
    assert abs(p["win"]-.5)<1e-10
    assert abs(p["loss"]-.5)<1e-10
    q=outcome_probs(3.0,3.0,15)
    assert q["push"]>0
    assert abs(sum(q[k] for k in ("win","loss","push"))-1)<1e-9
    assert abs(market_ev(1.0,q))<1e-9
    assert abs(sum(outcome_probs(3.25,3,15)[k] for k in ("win","loss","push"))-1)<1e-9
    # Home cover line +3.5 is home winning by 4+, home -5.5 means home +5.5.
    p1=outcome_probs(3.5,0,15);p2=outcome_probs(-5.5,0,15)
    assert p1["win"]<.5 and p2["win"]>.5
    print("MARKET_MATH_TEST_PASS")

if __name__=="__main__":
    self_test()
