#!/usr/bin/env python3
"""Shadow-only dynamic five-market probabilities from point-in-time 007 captures.

The independent model remains immutable. Market quotes set settlement thresholds;
they never become features or weights in the independent model. Not wired to PushPlus.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

MARKETS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")

def n(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):
        return None

def cdf(z):
    return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))

def side_probability(mu,sigma,threshold,greater=True):
    mu,sigma,threshold=map(n,(mu,sigma,threshold))
    if None in (mu,sigma,threshold) or sigma<=0:
        return None
    p=cdf((mu-threshold)/sigma)
    return p if greater else 1.0-p

def evaluate(joined,model,five,jingcai=None,consensus=None,injury=None,previous=None):
    games={str(x.get("game_id")):x for x in joined.get("nba_cba_games",[])}
    preds={str(x.get("game_id")):x for x in model.get("games",[])}
    frozen={str(x.get("game_id")):x for x in five.get("games",[])}
    jc={str(x.get("game_id")):x for x in (jingcai or {}).get("games",[])}
    cons={str(x.get("game_id")):x for x in (consensus or {}).get("games",[])}
    inj={str(x.get("game_id")):x for x in (injury or {}).get("games",[])}
    old={str(x.get("game_id")):x for x in (previous or {}).get("games",[])}
    rows=[]
    for gid,game in games.items():
        p=preds.get(gid,{})
        f=frozen.get(gid,{})
        if gid not in f or (game.get("home_team"),game.get("away_team")) != (f.get("home_team"),f.get("away_team")):
            raise ValueError("TEAM_IDENTITY_MISMATCH:"+gid)
        margin=n(p.get("margin_mean_home_minus_away"))
        total=n(p.get("total_mean"))
        margin_sigma=n(p.get("margin_sigma"))
        total_sigma=n(p.get("total_sigma"))
        ml=p.get("model_probability") or {}
        home_ml=n(ml.get("home")); away_ml=n(ml.get("away"))
        jc_markets=(jc.get(gid,{}).get("markets") or {})
        current={}
        for key in MARKETS:
            frozen_market=(f.get("markets") or {}).get(key) or {}
            direction=frozen_market.get("direction")
            if key=="JINGCAI_WIN":
                prob=home_ml if direction=="HOME_WIN" else away_ml if direction=="AWAY_WIN" else None
                current[key]={"direction":direction,"line":None,
                    "selected_side_probability":prob,
                    "probability_status":"INDEPENDENT_MONEYLINE_BASELINE" if prob is not None else "MODEL_MONEYLINE_MISSING"}
                continue
            if key=="JINGCAI_HANDICAP":
                q=((jc_markets.get("handicap") or {}).get("data") or {}).get("current") or {}
                line=n(q.get("line"))
                signed_home=line
            elif key=="JINGCAI_TOTAL":
                q=((jc_markets.get("total") or {}).get("data") or {}).get("current") or {}
                line=n(q.get("line"))
                signed_home=None
            elif key=="CROWN_HANDICAP":
                q=((game.get("markets") or {}).get("full_spread") or {}).get("current") or {}
                line=n(q.get("line"))
                signed_home=-line if line is not None else None
            else:
                q=((game.get("markets") or {}).get("full_total") or {}).get("current") or {}
                line=n(q.get("line"))
                signed_home=None
            if key.endswith("HANDICAP"):
                home_cover=side_probability(margin,margin_sigma,-signed_home,True) if signed_home is not None else None
                away_cover=1.0-home_cover if home_cover is not None else None
                prob=home_cover if direction=="HOME_COVER" else away_cover if direction=="AWAY_COVER" else None
                candidate="HOME_COVER" if home_cover is not None and home_cover>=0.5 else "AWAY_COVER" if away_cover is not None else None
                both={"home_cover_probability":home_cover,"away_cover_probability":away_cover}
            else:
                over=side_probability(total,total_sigma,line,True) if line is not None else None
                under=1.0-over if over is not None else None
                prob=over if direction=="OVER" else under if direction=="UNDER" else None
                candidate="OVER" if over is not None and over>=0.5 else "UNDER" if under is not None else None
                both={"over_probability":over,"under_probability":under}
            current[key]={"direction":direction,"candidate_direction":candidate,"line":line,
                "signed_home_handicap":signed_home,**both,"selected_side_probability":prob,
                "probability_status":"SHADOW_RECALCULATED" if prob is not None else "MISSING_LINE_OR_MODEL_SIGMA"}
        prev=old.get(gid,{})
        for key,item in current.items():
            before=n(((prev.get("markets") or {}).get(key) or {}).get("selected_side_probability"))
            after=n(item.get("selected_side_probability"))
            item["delta_probability_pp"]=round((after-before)*100,3) if before is not None and after is not None else None
        cm=(cons.get(gid,{}).get("markets") or {})
        context={}
        for kind,key in (("full_spread","CROWN_HANDICAP"),("full_total","CROWN_TOTAL")):
            z=cm.get(kind) or {}
            context[key]={"status":z.get("status"),"main_line":z.get("main_line"),
                "company_count":z.get("main_line_company_count"),
                "same_line_probability":(z.get("same_line_price_consensus") or {}).get("first_side_probability"),
                "fusion_applied":False}
        rows.append({"game_id":gid,"home_team":game.get("home_team"),"away_team":game.get("away_team"),
            "captured_at_utc":joined.get("captured_at_utc"),
            "independent_model":{"home_win_probability":home_ml,"away_win_probability":away_ml,
                "margin_mean_home_minus_away":margin,"total_mean":total,
                "margin_sigma":margin_sigma,"total_sigma":total_sigma},
            "injury_quality":inj.get(gid,{}).get("quality","NOT_PROVIDED"),
            "markets":current,"multi_company_context":context,
            "market_probability_fusion":"DISABLED_SHADOW_ONLY","production_probability_changed":False})
    return {"schema_version":"nba-dynamic-five-market-shadow-v1",
        "target_date":joined.get("requested_display_date"),"captured_at_utc":joined.get("captured_at_utc"),
        "game_count":len(rows),"games":rows,"production_model_modified":False,"pushplus_enabled":False,
        "validation_state":"RESEARCH_ONLY_PENDING_CHRONOLOGICAL_OOS"}

def self_test():
    joined={"requested_display_date":"2026-11-01","captured_at_utc":"2026-10-31T10:00:00Z",
      "nba_cba_games":[{"game_id":"1","home_team":"H","away_team":"A","markets":{
        "full_spread":{"current":{"line":-5.5}},"full_total":{"current":{"line":220}}}}]}
    model={"games":[{"game_id":"1","model_probability":{"home":.6,"away":.4},
      "margin_mean_home_minus_away":4,"total_mean":225,"margin_sigma":10,"total_sigma":15}]}
    five={"games":[{"game_id":"1","home_team":"H","away_team":"A","markets":{
      "JINGCAI_WIN":{"direction":"HOME_WIN"},"JINGCAI_HANDICAP":{"direction":"HOME_COVER"},
      "JINGCAI_TOTAL":{"direction":"OVER"},"CROWN_HANDICAP":{"direction":"AWAY_COVER"},
      "CROWN_TOTAL":{"direction":"OVER"}}}]}
    jc={"games":[{"game_id":"1","markets":{
      "handicap":{"data":{"current":{"line":5.5}}},"total":{"data":{"current":{"line":220}}}}}]}
    x=evaluate(joined,model,five,jc)
    m=x["games"][0]["markets"]
    assert abs(m["JINGCAI_WIN"]["selected_side_probability"]-.6)<1e-9
    assert m["JINGCAI_HANDICAP"]["selected_side_probability"]>0.5
    assert m["CROWN_HANDICAP"]["selected_side_probability"]<0.5
    assert m["JINGCAI_TOTAL"]["selected_side_probability"]>0.5
    assert x["production_model_modified"] is False and x["pushplus_enabled"] is False
    print("NBA_DYNAMIC_FIVE_MARKET_SHADOW_SELFTEST_PASS")

def main():
    ap=argparse.ArgumentParser()
    for name in ("joined","model","five","jingcai","consensus","injury","previous","out"):
        ap.add_argument("--"+name,required=name in ("joined","model","five","jingcai","out"))
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:
        self_test(); return
    def load(path):
        return json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
    result=evaluate(load(a.joined),load(a.model),load(a.five),load(a.jingcai),
                    load(a.consensus),load(a.injury),load(a.previous))
    Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print("DYNAMIC_FIVE_MARKET_SHADOW",result["game_count"],result["validation_state"])
if __name__=="__main__": main()
