#!/usr/bin/env python3
"""NBA official Four Factors data-contract audit; research only.

The legacy season CSV currently exposes FGA, FTA, offensive rebounds, turnovers
and estimated possessions, but the parsed row does not include FGM/3PM, opponent
defensive rebounds, or a verified official TOV%. These missing fields MUST NOT
be filled with zero or inferred from points/possessions. Odds never used.

NBA official glossary:
  eFG = (FGM + 0.5 * 3PM) / FGA
  OREB% = OREB / (OREB + Opponent DREB)
  FTA rate = FTA / FGA
  TOV% is required as a separately verified statistic (no silent proxy rename).
"""
from __future__ import annotations
import math

CANONICAL=("efg_pct","tov_pct","oreb_pct","fta_rate")
SOURCE=("fgm","fg3m","fga","tov_pct","oreb","opp_dreb","fta")
SHADOW_ONLY=True

def finite(x):
    if x is None or isinstance(x,bool):return None
    try:
        value=float(x)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None

def canonical_from_snapshot(snapshot):
    """One historical team-game; must contain all source-verified inputs."""
    absent=[key for key in SOURCE if finite(snapshot.get(key)) is None]
    if absent:
        return {"status":"INCOMPLETE_CANONICAL_FOUR_FACTORS",
                "missing":absent,"metrics":None,"production_enabled":False}
    fgm,fg3m,fga=[finite(snapshot[x]) for x in ("fgm","fg3m","fga")]
    oreb,opp_dreb=[finite(snapshot[x]) for x in ("oreb","opp_dreb")]
    fta,tov=[finite(snapshot[x]) for x in ("fta","tov_pct")]
    assert None not in (fgm,fg3m,fga,oreb,opp_dreb,fta,tov)
    if not(0<=fg3m<=fgm<=fga and fga>0 and 0<=oreb and 0<=opp_dreb and
           oreb+opp_dreb>0 and 0<=fta and 0<=tov<=1):
        return {"status":"INVALID_FOUR_FACTORS_SOURCE_VALUES",
                "missing":[],"metrics":None,"production_enabled":False}
    metrics={"efg_pct":(fgm+0.5*fg3m)/fga,
             "tov_pct":tov,
             "oreb_pct":oreb/(oreb+opp_dreb),
             "fta_rate":fta/fga}
    if metrics["efg_pct"]>1.5 or metrics["fta_rate"]>2:
        return {"status":"IMPLAUSIBLE_FOUR_FACTORS",
                "missing":[],"metrics":None,"production_enabled":False}
    return {"status":"CANONICAL_FIELDS_PRESENT_SHADOW_ONLY",
            "missing":[],"metrics":metrics,"production_enabled":False}

def audit_parsed_history_schema():
    # Rows produced by nba_rolling_form_h2h.parse() are exactly these fields.
    # The CSV itself may have other columns; do not claim the upstream source lacks them.
    parsed_schema={"date","season","team","opponent","home","points","against",
                   "result","possessions_est","fga","fta","oreb","tov"}
    return {"parsed_contract":"nba_rolling_form_h2h.parse",
            "missing_for_canonical":sorted(set(SOURCE)-parsed_schema),
            "has_complete_official_four_factors":set(SOURCE)<=parsed_schema,
            "warning":"Existing proxy-only research cannot be called official Four Factors; inspect verified upstream raw columns before extending parser.",
            "production_enabled":False}

def self_test():
    schema=audit_parsed_history_schema()
    assert not schema["has_complete_official_four_factors"]
    assert {"fgm","fg3m","opp_dreb","tov_pct"}<=set(schema["missing_for_canonical"])
    sample={"fgm":40,"fg3m":12,"fga":88,"tov_pct":0.125,
            "oreb":12,"opp_dreb":28,"fta":22}
    out=canonical_from_snapshot(sample)
    assert out["status"]=="CANONICAL_FIELDS_PRESENT_SHADOW_ONLY"
    assert abs(out["metrics"]["efg_pct"]-(46/88))<1e-12
    assert out["metrics"]["oreb_pct"]==0.3
    assert out["metrics"]["fta_rate"]==0.25
    assert not out["production_enabled"]
    for k in SOURCE:
        broken={v:x for v,x in sample.items() if v!=k}
        assert canonical_from_snapshot(broken)["metrics"] is None
    bad={**sample,"fg3m":50}
    assert canonical_from_snapshot(bad)["status"]=="INVALID_FOUR_FACTORS_SOURCE_VALUES"
    assert canonical_from_snapshot({**sample,"fga":0})["status"]=="INVALID_FOUR_FACTORS_SOURCE_VALUES"
    assert canonical_from_snapshot({**sample,"tov_pct":float("nan")})["metrics"] is None
    print("NBA_OFFICIAL_FOUR_FACTORS_SOURCE_CONTRACT_PASS")

if __name__=="__main__":
    self_test()
