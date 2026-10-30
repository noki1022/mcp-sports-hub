#!/usr/bin/env python3
"""A/B/C NBA timestamped-odds comparison. Research only, NEVER pick bets.

A: independent pre-target-date ridge + calibration (no bookmaker odds).
B: explicitly oriented, contemporaneous The Odds API no-vig quotes.
C: convex fusion with its weight fitted on earlier validation DAYS only.
Require enough distinct days AND matched independent predictions for promotion.
Current archived sample is tiny (12 games, 1 Beijing date), so C is blocked.

Only same-event, same-market, same-line outcomes compared. Market prices have
verified snapshot and price-update instants before tipoff. Source historical
team-results publication times are NOT archived, hence retrospective A scores
are research diagnostics, not verified historical trading signals.
"""
from __future__ import annotations
import argparse,json,math,statistics,sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analysis"))
from historical_odds_validator import NBA_TEAMS
from nba_independent_predictions import generate

MARKETS=("h2h","spreads","totals")
DAYS_MIN=24
EVENTS_MIN=300
MIN_TRAIN=120
MIN_VALID=60
MIN_TEST=60
GRID=(0.0,.10,.20,.30,.40,.50,.60,.70,.80,.90,1.0)
BJ=ZoneInfo("Asia/Shanghai")

def utc(s):
    x=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    if x.tzinfo is None:raise ValueError("NO_TIMEZONE")
    return x.astimezone(timezone.utc)

def valid_number(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def quote_events(settlement,scores):
    """Return event/market consensus; reject stale or incompatible quotes."""
    games={str(g["event_id"]):g for g in scores.get("games",[])
           if g.get("completed") and valid_number(g.get("home_points")) is not None
           and valid_number(g.get("away_points")) is not None}
    grouped=defaultdict(list); rejects=Counter(); unique=set()
    for snapshot in settlement.get("snapshot_reports",[]):
        for r in snapshot.get("rows",[]):
            eid=str(r.get("event_id",""));typ=r.get("market")
            if typ not in MARKETS:rejects["INVALID_MARKET"]+=1;continue
            g=games.get(eid)
            if g is None:rejects["MISSING_COMPLETED_SCORE"]+=1;continue
            try:
                tip=utc(r["commence_time_utc"])
                qtime=utc(r["price_last_update_utc"])
                stime=utc(r["snapshot_time_utc"])
                official_tip=utc(g["commence_time"])
                if abs((tip-official_tip).total_seconds())>180:
                    rejects["TIPOFF_TIME_MISMATCH"]+=1;continue
                if min((tip-qtime).total_seconds(),(tip-stime).total_seconds())<=0:
                    rejects["QUOTE_NOT_PRETIP"]+=1;continue
                if (stime-qtime).total_seconds() < -5:
                    rejects["QUOTE_AFTER_SNAPSHOT"]+=1;continue
                if (stime-qtime).total_seconds()>90*60:
                    rejects["STALE_QUOTE"]+=1;continue
                if (tip-stime).total_seconds()>48*3600 or (tip-stime).total_seconds()<30*60:
                    rejects["UNUSABLE_LEAD_WINDOW"]+=1;continue
                if r.get("snapshot_phase")!="PRE_GAME_FIXED":
                    rejects["PHASE_NOT_FIXED"]+=1;continue
                home,away=r["home"],r["away"]
                if home not in NBA_TEAMS or away not in NBA_TEAMS:
                    rejects["UNKNOWN_TEAM"]+=1;continue
                if NBA_TEAMS[home].lower()!=str(g.get("home_team","")).lower() or NBA_TEAMS[away].lower()!=str(g.get("away_team","")).lower():
                    rejects["TEAM_MISMATCH"]+=1;continue
                if r.get("first_side")!=("over" if typ=="totals" else "home") or r.get("second_side")!=("under" if typ=="totals" else "away"):
                    rejects["DIRECTION_UNVERIFIED"]+=1;continue
                p=valid_number(r.get("p_first_no_vig"))
                price=valid_number(r.get("first_price_decimal"))
                other_price=valid_number(r.get("second_price_decimal"))
                if p is None or not 0<p<1 or price is None or price<=1 or other_price is None or other_price<=1:
                    rejects["PRICE_INVALID"]+=1;continue
                recalc=(1/price)/(1/price+1/other_price)
                if abs(recalc-p)>1e-6:
                    rejects["DEVIG_RECONCILIATION_FAILED"]+=1;continue
                line=0.0 if typ=="h2h" else valid_number(r.get("total_point" if typ=="totals" else "home_handicap_point"))
                if line is None or (typ!="h2h" and abs(4*line-round(4*line))>1e-8):
                    rejects["LINE_INVALID"]+=1;continue
                if abs(float(r.get("home_points"))-float(g["home_points"]))>1e-8 or abs(float(r.get("away_points"))-float(g["away_points"]))>1e-8:
                    rejects["RESULT_MISMATCH"]+=1;continue
                row={**r,"line":line,"tip":tip.isoformat(),"quote_time":qtime.isoformat(),
                     "snapshot_time":stime.isoformat(),"p":p,
                     "date_bj":tip.astimezone(BJ).date().isoformat()}
                grouped[(eid,typ)].append(row);unique.add(eid)
            except (KeyError,TypeError,ValueError,OverflowError):
                rejects["MALFORMED_ODDS_ROW"]+=1
    out={}
    for (eid,typ),rows in grouped.items():
        # Use only latest strictly eligible quote PER BOOK to avoid duplicate weighting.
        bybook={}
        for r in rows:
            b=r.get("bookmaker")
            if not b:continue
            if b not in bybook or utc(r["snapshot_time"])>utc(bybook[b]["snapshot_time"]):
                bybook[b]=r
        byline=defaultdict(list)
        for r in bybook.values():byline[r["line"]].append(r)
        if not byline:rejects["NO_BOOKMAKER"]+=1;continue
        max_books=max(len(v) for v in byline.values())
        eligible=[(line,arr) for line,arr in byline.items() if len(arr)==max_books]
        if len(eligible)!=1 or max_books<3:
            rejects["LINE_CONSENSUS_AMBIGUOUS_OR_UNDER3"]+=1;continue
        line,quotes=eligible[0]
        first=quotes[0]
        g=games[eid]
        margin=float(g["home_points"])-float(g["away_points"])
        val=margin if typ=="h2h" else margin+line if typ=="spreads" else float(g["home_points"])+float(g["away_points"])-line
        result=None if abs(val)<1e-9 else int(val>0)
        out[(eid,typ)]={"event_id":eid,"market":typ,"date_bj":first["date_bj"],"tip":first["tip"],
                "home":first["home"],"away":first["away"],"line":line,
                "market_p":float(statistics.median(q["p"] for q in quotes)),
                "books":len(quotes),"settlement":"PUSH" if result is None else "FIRST_WIN" if result else "FIRST_LOSS",
                "label":result,"quote_time_latest":max(q["quote_time"] for q in quotes),
                "orientation":"THE_ODDS_API_CANONICAL_VERIFIED"}
    return out,dict(rejects),len(unique)

def a_predictions(grouped,with_a):
    if not with_a:return {},{"status":"DISABLED"}
    dates=sorted({v["date_bj"] for v in grouped.values()})
    byday=defaultdict(dict)
    for (eid,market),r in grouped.items():
        if market=="h2h":byday[r["date_bj"]][eid]=r
    pred={};errors=[]
    for day in dates:
        fixtures=[]
        for eid,r in byday[day].items():
            totals=grouped.get((eid,"totals"))
            spreads=grouped.get((eid,"spreads"))
            fixtures.append({"game_id":eid,"date":day,"home":r["home"],"away":r["away"],
                "season":"2026-27",
                "spread_line":-spreads["line"] if spreads else None,
                "total_line":totals["line"] if totals else None})
        if not fixtures:continue
        try:
            out=generate({"target_display_date":day,"games":fixtures})
            cutoff=out.get("data_cutoff_date")
            for p in out.get("predictions",[]):
                if p.get("status") not in ("OK","PARTIAL"):continue
                if not cutoff or not cutoff<day or not p.get("feature_cutoff_date","")<day:continue
                pred[p["game_id"]]=p
        except (ValueError,RuntimeError,OSError) as exc:
            errors.append({"date":day,"error":type(exc).__name__})
    return pred,{"status":"RETROSPECTIVE_PRIOR_DAY_RESULTS_NOT_PUBLICATION_AUDITED",
                 "unique_days":len(dates),"predicted_games":len(pred),"errors":errors,
                 "odds_as_features":False}

def collect(grouped,pred):
    data=defaultdict(list)
    for (eid,m),r in sorted(grouped.items()):
        if r["label"] is None:continue  # pushes are not binary outcomes
        a=pred.get(eid)
        ap=None
        if a:
            if m=="h2h":ap=valid_number(a.get("moneyline_home_probability"))
            else:
                k="full_total" if m=="totals" else "full_spread"
                market=next((x for x in a.get("markets",[]) if x.get("market")==k),None)
                if market:
                    exact=r["line"] if m=="totals" else -r["line"]
                    if abs(float(market["line"])-exact)<1e-8:ap=valid_number(market.get("p_side1"))
        data[m].append({**r,"A":ap,"B":r["market_p"]})
    return data

def score(rows,key):
    rows=[r for r in rows if r.get(key) is not None]
    if not rows:return {"n":0,"Brier":None,"LogLoss":None,"ECE_5":None}
    y=[r["label"] for r in rows];p=[min(1-1e-8,max(1e-8,float(r[key]))) for r in rows]
    n=len(rows)
    brier=sum((v-o)**2 for v,o in zip(p,y))/n
    logloss=-sum(o*math.log(v)+(1-o)*math.log(1-v) for v,o in zip(p,y))/n
    ece=sum(sum(1 for v in p if i/5<=v<(i+1)/5)/n *
            abs(sum(y[j] for j in range(n) if i/5<=p[j]<(i+1)/5) /
                sum(1 for v in p if i/5<=v<(i+1)/5) -
                sum(p[j] for j in range(n) if i/5<=p[j]<(i+1)/5) /
                sum(1 for v in p if i/5<=v<(i+1)/5))
            for i in range(5) if any(i/5<=v<(i+1)/5 for v in p))
    return {"n":n,"Brier":round(brier,7),"LogLoss":round(logloss,7),"ECE_5":round(ece,7)}

def chronology(rows):
    dates=sorted({r["date_bj"] for r in rows})
    if len(rows)<EVENTS_MIN or len(dates)<DAYS_MIN:
        return None,{"status":"INSUFFICIENT_DISTINCT_DAYS_OR_EVENTS",
                     "required_events":EVENTS_MIN,"required_beijing_days":DAYS_MIN,
                     "events":len(rows),"days":len(dates)}
    cut1=max(1,int(len(dates)*.60));cut2=max(cut1+1,int(len(dates)*.80))
    train=[r for r in rows if r["date_bj"] in dates[:cut1]]
    valid=[r for r in rows if r["date_bj"] in dates[cut1:cut2]]
    test=[r for r in rows if r["date_bj"] in dates[cut2:]]
    if min(len(train)/MIN_TRAIN,len(valid)/MIN_VALID,len(test)/MIN_TEST)<1:
        return None,{"status":"INSUFFICIENT_CHRONOLOGICAL_SPLIT",
                     "train":len(train),"validation":len(valid),"test":len(test)}
    return (train,valid,test),{"status":"SPLIT_OK","train":len(train),"validation":len(valid),"test":len(test),
                              "train_end":dates[cut1-1],"validation_end":dates[cut2-1],"test_start":dates[cut2]}

def fusion(rows,provenance):
    matched=[r for r in rows if r["A"] is not None and r["B"] is not None]
    split,meta=chronology(matched)
    if split is None:return {"status":"BLOCKED","reason":meta,"C_weight":None,"C_metrics":None}
    if provenance.get("status")!="POINT_IN_TIME_VERIFIED":
        return {"status":"BLOCKED","reason":"INDEPENDENT_FEATURE_PUBLICATION_TIME_NOT_ARCHIVED","split":meta}
    train,validation,test=split
    # No test labels are used in tuning. Weight is selected on PRIOR validation days.
    def loss(w,items):
        return sum(((1-w)*r["A"]+w*r["B"]-r["label"])**2 for r in items)/len(items)
    weight=min(GRID,key=lambda w:(loss(w,validation),w))
    out=[{**r,"C":(1-weight)*r["A"]+weight*r["B"]} for r in test]
    return {"status":"RESEARCH_HOLDOUT_NO_VALUE_CLAIMS","weight_market":weight,"split":meta,
            "holdout":{"A":score(out,"A"),"B":score(out,"B"),"C":score(out,"C")},
            "value_policy":"NO_BET"}

def run(settlements,scores,out,include_a=False):
    grouped,rejects,raw_events=quote_events(read_json(settlements),read_json(scores))
    predictions,provenance=a_predictions(grouped,include_a)
    markets=collect(grouped,predictions)
    data={}
    for market in MARKETS:
        rows=markets.get(market,[])
        same=[r for r in rows if r["A"] is not None]
        data[market]={"settled_nonpush_events":len(rows),
                      "pushes":sum(x["label"] is None for (eid,m),x in grouped.items() if m==market),
                      "bookmaker_market_B_descriptive":score(rows,"B"),
                      "paired_A_descriptive":score(same,"A"),
                      "paired_B_descriptive":score(same,"B"),
                      "C":fusion(rows,provenance),
                      "sample_days":len({r["date_bj"] for r in rows})}
    report={"schema_version":"nba-abc-fusion-research-v1",
            "generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "source":"The Odds API settled normalized pretip snapshots; NOT Titan007 raw side slots",
            "input_unique_events":raw_events,"eligible_event_market_rows":len(grouped),
            "rejections":rejects,"independent_A_provenance":provenance,
            "comparisons":data,"production_fusion_enabled":False,
            "decision":"NO_BET",
            "limitations":["All Brier/LogLoss here are retrospective descriptive until enough separate event DAYS exist.",
                "Independent historical result publication timestamps are not archived; no true point-in-time A/C promotion.",
                "No executable matched-price ROI, bookmaker limits or closing-line benefit proven.",
                "Consensus compares same quoted line with multiple distinct bookmakers, never mixtures of lines."]}
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("NBA_ABC_TIMESTAMPED_RESEARCH "+json.dumps({
        "events":raw_events,"market_rows":len(grouped),
        "A":provenance,"comparisons":data,"decision":report["decision"]},ensure_ascii=False),flush=True)
    return report

def self_test():
    from datetime import timedelta
    tip=datetime(2026,10,29,0,tzinfo=timezone.utc)
    eid="SYN"
    base={"event_id":eid,"market":"h2h","home":"IND","away":"PHI",
          "first_side":"home","second_side":"away","first_price_decimal":2.0,
          "second_price_decimal":2.0,"p_first_no_vig":.5,
          "commence_time_utc":tip.isoformat(),"price_last_update_utc":(tip-timedelta(hours=3)).isoformat(),
          "snapshot_time_utc":(tip-timedelta(hours=2)).isoformat(),
          "snapshot_phase":"PRE_GAME_FIXED","bookmaker":"a","home_points":120,"away_points":100}
    score_board={"games":[{"event_id":eid,"completed":True,"home_team":"Indiana Pacers",
                     "away_team":"Philadelphia 76ers","home_points":120,"away_points":100,"commence_time":tip.isoformat()}]}
    snap={"snapshot_reports":[{"rows":[{**base,"bookmaker":b} for b in ("a","b","c")]}]}
    selected,rejects,n=quote_events(snap,score_board)
    assert n==1 and len(selected)==1 and not rejects
    assert collect(selected,{})["h2h"][0]["label"]==1
    changed={"snapshot_reports":[{"rows":[{**base,"bookmaker":b,"first_side":"away"} for b in ("a","b","c")]}]}
    assert quote_events(changed,score_board)[0]=={}
    assert chronology([{"date_bj":"2026-10-29","A":.51,"B":.5,"label":1}]*400)[0] is None
    assert score([{"label":1,"B":.5}],"B")["Brier"]==.25
    print("NBA_ABC_ASOF_DIRECTION_AND_NO_DATA_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--settlements",default="reports/odds/latest_settlement.json")
    p.add_argument("--scores",default="data/results/odds_api_scores.json")
    p.add_argument("--out",default="nba_abc_market_fusion_report.json")
    p.add_argument("--include-a",action="store_true")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:run(a.settlements,a.scores,a.out,a.include_a)
