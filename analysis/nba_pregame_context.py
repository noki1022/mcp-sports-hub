#!/usr/bin/env python3
"""Point-in-time NBA fatigue and recency-weighted H2H features.

Use only dated, completed games strictly prior to tipoff. Source game dates
have day resolution, so travel, actual player minutes and rest hours are NOT
inferred. This is a candidate numerical extension; no injuries are imputed.
"""
from __future__ import annotations
from datetime import date
import math

NAMES=(
    "home_b2b", "away_b2b", "both_b2b",
    "home_games_previous_4d", "away_games_previous_4d",
    "home_rest_days", "away_rest_days",
    "h2h_effective_games", "h2h_recent_margin", "h2h_recent_total_offset",
)
H2H_HALF_LIFE_DAYS=365.0

def build(target,home,away,home_games,away_games,h2h_games):
    target_date=date.fromisoformat(str(target))
    def days_before(g):
        delta=(target_date-date.fromisoformat(g["date"])).days
        if delta<=0:raise ValueError("PREGAME_CONTEXT_FUTURE_OR_SAME_DAY_LEAK")
        return delta
    def rest(rows):
        if not rows:return None
        return min(7,max(0,days_before(rows[-1])-1))
    def recent(rows):
        return sum(1 for g in rows if days_before(g)<=4)
    hr,ar=rest(home_games),rest(away_games)
    if hr is None or ar is None:raise ValueError("INSUFFICIENT_TEAM_REST_HISTORY")
    hb,ab=float(hr==0),float(ar==0)
    weights=[2.0**(-days_before(g)/H2H_HALF_LIFE_DAYS) for g in h2h_games]
    effective=sum(weights)
    denom=effective+5.0
    margin=0.0;tot=0.0
    for weight,g in zip(weights,h2h_games):
        m=(g["home_points"]-g["away_points"]) if g["home"]==home else (g["away_points"]-g["home_points"])
        margin+=weight*m
        tot+=weight*(g["total"]-225.0)
    features=[
        hb,ab,float(hb and ab),float(recent(home_games)),float(recent(away_games)),
        float(hr),float(ar),float(effective),margin/denom,tot/denom,
    ]
    if len(features)!=len(NAMES) or not all(math.isfinite(x) for x in features):
        raise ValueError("INVALID_PREGAME_CONTEXT_FEATURES")
    return {"features":features,"names":list(NAMES),
            "fatigue":{"home_rest_days":hr,"away_rest_days":ar,
                       "home_b2b":bool(hb),"away_b2b":bool(ab),
                       "both_b2b":bool(hb and ab),
                       "home_games_previous_4d":int(features[3]),
                       "away_games_previous_4d":int(features[4]),
                       "minutes_and_travel_adjusted":False},
            "h2h_recency":{"observed_games":len(h2h_games),
                           "effective_games":round(effective,3),
                           "half_life_days":H2H_HALF_LIFE_DAYS,
                           "adjusted_margin":round(margin/denom,3),
                           "adjusted_total_offset":round(tot/denom,3),
                           "roster_similarity_verified":False}}

def self_test():
    def match(d,h="ATL",a="MIA",m=7):
        return {"date":d,"home":h,"away":a,"home_points":110+m,"away_points":110,"total":220+m}
    g=[{"date":"2026-10-29"}]
    b=build("2026-10-30","ATL","MIA",g,g,
        [match("2025-10-29"),match("2026-10-20")])
    assert b["fatigue"]["both_b2b"] is True
    assert b["fatigue"]["home_rest_days"]==0
    assert b["h2h_recency"]["effective_games"]<2
    reversed_site=build("2026-10-30","ATL","MIA",g,g,[match("2026-10-20","MIA","ATL")])
    assert reversed_site["h2h_recency"]["adjusted_margin"]<0
    assert build("2026-10-30","ATL","MIA",[{"date":"2026-10-25"}],g,[])["fatigue"]["home_b2b"] is False
    try:build("2026-10-30","ATL","MIA",[{"date":"2026-10-30"}],g,[])
    except ValueError as e:assert "LEAK" in str(e)
    else:raise AssertionError("SAME_DAY_LEAK_ACCEPTED")
    print("NBA_PREGAME_CONTEXT_SELF_TEST_PASS")

if __name__=="__main__":
    self_test()
