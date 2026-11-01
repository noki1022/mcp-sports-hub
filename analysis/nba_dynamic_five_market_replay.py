#!/usr/bin/env python3
"""Score frozen pre-tip five-market shadow probabilities against official finals.

One latest valid pre-tip snapshot per game/market is used for the primary
scorecard. Slot-specific scorecards remain separate; repeated hourly rows are
never pooled as independent games. No retraining, EV, ROI or production fusion.
"""
from __future__ import annotations
import argparse, json, math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

MARKETS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")

def stamp(x):
    try:
        d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
        return d if d.tzinfo is not None else None
    except (TypeError,ValueError): return None

def num(x):
    if x is None or isinstance(x,bool): return None
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (TypeError,ValueError): return None

def logloss(p,y):
    p=min(1-1e-12,max(1e-12,p))
    return -(y*math.log(p)+(1-y)*math.log(1-p))

def metric_rows(rows):
    n=len(rows)
    if not n:
        return {"n":0,"brier":None,"log_loss":None,"ece_10":None,
                "first_side_accuracy":None,"candidate_direction_accuracy":None,
                "frozen_direction_accuracy":None,"consensus_brier":None}
    brier=sum((r["p"]-r["y"])**2 for r in rows)/n
    ll=sum(logloss(r["p"],r["y"]) for r in rows)/n
    ece=0.0; bins=[]
    for i in range(10):
        group=[r for r in rows if i/10<=r["p"]<((i+1)/10 if i<9 else 1.0000001)]
        bins.append({"lower":i/10,"upper":(i+1)/10,"n":len(group),
            "mean_probability":round(sum(r["p"] for r in group)/len(group),6) if group else None,
            "realized_first_side_rate":round(sum(r["y"] for r in group)/len(group),6) if group else None})
        if group:
            ece+=len(group)/n*abs(sum(r["p"] for r in group)/len(group)-sum(r["y"] for r in group)/len(group))
    def direction_accuracy(key):
        subset=[r for r in rows if r.get(key) in ("HIT","MISS")]
        return {"n":len(subset),"hits":sum(r[key]=="HIT" for r in subset),
                "misses":sum(r[key]=="MISS" for r in subset),
                "accuracy":round(sum(r[key]=="HIT" for r in subset)/len(subset),6) if subset else None}
    consensus=[r for r in rows if r.get("consensus_p") is not None]
    return {
        "n":n,"brier":round(brier,7),"log_loss":round(ll,7),"ece_10":round(ece,7),
        "first_side_accuracy":round(sum(r["y"] for r in rows)/n,6),
        "candidate_direction_accuracy":direction_accuracy("candidate_outcome"),
        "frozen_direction_accuracy":direction_accuracy("frozen_outcome"),
        "consensus_benchmark":{"n":len(consensus),
            "brier":round(sum((r["consensus_p"]-r["y"])**2 for r in consensus)/len(consensus),7) if consensus else None,
            "log_loss":round(sum(logloss(r["consensus_p"],r["y"]) for r in consensus)/len(consensus),7) if consensus else None},
        "calibration_bins":bins}

def actual_first_side(key,market,home,away):
    margin=home-away
    total=home+away
    if key=="JINGCAI_WIN":
        if margin==0:return None,"PUSH"
        return int(margin>0),"SETTLED"
    if key.endswith("HANDICAP"):
        signed=num(market.get("signed_home_handicap"))
        if signed is None:return None,"INVALID_SIGNED_HANDICAP"
        adjusted=margin+signed
        if abs(adjusted)<1e-8:return None,"PUSH"
        return int(adjusted>0),"SETTLED"
    line=num(market.get("line"))
    if line is None:return None,"INVALID_TOTAL_LINE"
    delta=total-line
    if abs(delta)<1e-8:return None,"PUSH"
    return int(delta>0),"SETTLED"

def grade_direction(direction,key,market,home,away):
    if not direction or direction=="TIE": return None
    y,status=actual_first_side(key,market,home,away)
    if y is None:return None
    first={"JINGCAI_WIN":"HOME_WIN","JINGCAI_HANDICAP":"HOME_COVER",
           "CROWN_HANDICAP":"HOME_COVER","JINGCAI_TOTAL":"OVER","CROWN_TOTAL":"OVER"}[key]
    second={"JINGCAI_WIN":"AWAY_WIN","JINGCAI_HANDICAP":"AWAY_COVER",
            "CROWN_HANDICAP":"AWAY_COVER","JINGCAI_TOTAL":"UNDER","CROWN_TOTAL":"UNDER"}[key]
    if direction not in (first,second):return None
    return "HIT" if (direction==first)==bool(y) else "MISS"

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def collect(daily_root,settled_root):
    records=[]; rejected=Counter(); snapshot_count=0; settled_days=[]
    for day_dir in sorted(Path(settled_root).glob("*")):
        if not day_dir.is_dir():continue
        settlement_path=day_dir/"settlement.json"
        if not settlement_path.is_file():continue
        settlement=load_json(settlement_path)
        day=str(settlement.get("beijing_date") or day_dir.name)
        if day!=day_dir.name:rejected["SETTLEMENT_DAY_FOLDER_MISMATCH"]+=1;continue
        finals={}
        for g in settlement.get("games",[]):
            gid=str(g.get("game_id") or "")
            hp,ap=g.get("home_points"),g.get("away_points")
            if gid and isinstance(hp,int) and not isinstance(hp,bool) and isinstance(ap,int) and not isinstance(ap,bool):
                finals[gid]={"home_points":hp,"away_points":ap,"home_team":g.get("home_team"),"away_team":g.get("away_team")}
        if not finals:continue
        settled_days.append(day)
        snapshot_files=sorted((Path(daily_root)/day).glob("*/nba_dynamic_five_market_shadow.json"))
        for file in snapshot_files:
            snapshot_count+=1
            slot=file.parent.name
            try:doc=load_json(file)
            except Exception:
                rejected["SNAPSHOT_JSON_INVALID"]+=1;continue
            if doc.get("target_date")!=day:
                rejected["SNAPSHOT_DAY_MISMATCH"]+=1;continue
            for g in doc.get("games",[]):
                gid=str(g.get("game_id") or "")
                final=finals.get(gid)
                if not final:
                    rejected["NO_OFFICIAL_FINAL_MATCH"]+=1;continue
                if (g.get("home_team"),g.get("away_team"))!=(final.get("home_team"),final.get("away_team")):
                    rejected["SETTLEMENT_TEAM_IDENTITY_MISMATCH"]+=1;continue
                tip=stamp(g.get("tipoff_beijing"))
                asof=stamp(g.get("decision_asof_utc"))
                if not tip or not asof or asof>=tip:
                    rejected["SNAPSHOT_NOT_STRICTLY_PRETIP"]+=1;continue
                home,away=final["home_points"],final["away_points"]
                for key in MARKETS:
                    market=(g.get("markets") or {}).get(key) or {}
                    if market.get("market_data_status")!="PRETIP_VALID" or market.get("probability_status")!="PRETIP_VALID":
                        rejected["MARKET_NOT_PRETIP_VALID"]+=1;continue
                    quote=stamp(market.get("quote_capture_utc"))
                    if not quote or quote>=tip:
                        rejected["MARKET_QUOTE_NOT_PRETIP"]+=1;continue
                    p=num(market.get("first_side_probability"))
                    if p is None or not 0<=p<=1:
                        rejected["MODEL_FIRST_SIDE_PROBABILITY_MISSING"]+=1;continue
                    y,state=actual_first_side(key,market,home,away)
                    if y is None:
                        if state=="PUSH":rejected["PUSH_EXCLUDED"]+=1
                        else:rejected[state]+=1
                        continue
                    candidate=grade_direction(market.get("candidate_direction"),key,market,home,away)
                    frozen=grade_direction(market.get("frozen_direction"),key,market,home,away)
                    consensus_p=None
                    mc=market.get("market_consensus") or {}
                    cp=num(mc.get("first_side_probability"))
                    cc=stamp(mc.get("latest_source_capture_utc"))
                    if (mc.get("eligible_same_line_benchmark") is True and cp is not None
                        and 0<=cp<=1 and cc is not None and cc<tip and cc<=asof
                        and mc.get("direct_line_matches_price_reference") is True):
                        consensus_p=cp
                    records.append({"day":day,"slot":slot,"game_id":gid,"market":key,
                        "asof":asof.isoformat(),"tip":tip.isoformat(),"p":p,"y":y,
                        "candidate_outcome":candidate,"frozen_outcome":frozen,
                        "consensus_p":consensus_p,"line":market.get("line"),
                        "candidate_direction":market.get("candidate_direction"),
                        "frozen_direction":market.get("frozen_direction")})
    return records,rejected,snapshot_count,sorted(set(settled_days))

def summarize(records):
    by_market={};by_slot={}
    for key in MARKETS:
        by_market[key]=metric_rows([r for r in records if r["market"]==key])
    slots=sorted({r["slot"] for r in records})
    for slot in slots:
        by_slot[slot]={key:metric_rows([r for r in records if r["slot"]==slot and r["market"]==key]) for key in MARKETS}
    # Latest valid pre-tip probability per game and market; repeated hourly
    # captures are not treated as independent observations.
    latest={}
    for r in records:
        key=(r["day"],r["game_id"],r["market"])
        if key not in latest or r["asof"]>latest[key]["asof"]:
            latest[key]=r
    latest_rows=list(latest.values())
    latest_by_market={key:metric_rows([r for r in latest_rows if r["market"]==key]) for key in MARKETS}
    return by_market,by_slot,latest_by_market,len(latest_rows)

def run(daily_root,settled_root):
    records,rejected,snapshot_count,days=collect(daily_root,settled_root)
    by_market,by_slot,latest_by_market,latest_rows=summarize(records)
    sample=sum(v["n"] for v in latest_by_market.values())
    distinct_days=len({r["day"] for r in []})
    distinct_days=max((v.get("distinct_days",0) for v in latest_by_market.values()),default=0)
    return {
        "schema_version":"nba-dynamic-five-market-replay-v1",
        "settled_days":days,"settled_day_count":len(days),
        "archived_shadow_snapshot_count":snapshot_count,
        "valid_pretip_market_snapshot_rows":len(records),
        "latest_game_market_rows":latest_rows,
        "by_market_all_snapshots":by_market,
        "by_slot":by_slot,
        "latest_pretip_by_market":latest_by_market,
        "sample_readiness":{"graded_latest_market_rows":sample,
            "minimum_events_for_research_review":100,
            "minimum_distinct_days_for_research_review":24,
            "distinct_days":distinct_days,
            "status":"READY_FOR_RESEARCH_REVIEW" if sample>=100 and distinct_days>=24 else "INSUFFICIENT_CHRONOLOGICAL_SAMPLE"},
        "rejections":dict(sorted(rejected.items())),
        "scoring_policy":"One latest valid pre-tip probability per game/market for primary metrics; per-slot metrics separate; pushes excluded; official final scores only",
        "production_model_modified":False,"probability_fusion_enabled":False,
        "betting_ev_or_roi_claimed":False}

def self_test():
    import tempfile
    from datetime import timezone
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);daily=root/"daily";settled=root/"settled";day="2026-11-01"
        slotdir=daily/day/"1800";slotdir.mkdir(parents=True)
        sd=settled/day;sd.mkdir(parents=True)
        keys={
          "JINGCAI_WIN":{"line":None,"signed_home_handicap":None,"first_side_probability":.6,"candidate_direction":"HOME_WIN","frozen_direction":"HOME_WIN"},
          "JINGCAI_HANDICAP":{"line":5.5,"signed_home_handicap":5.5,"first_side_probability":.8,"candidate_direction":"HOME_COVER","frozen_direction":"HOME_COVER"},
          "JINGCAI_TOTAL":{"line":215.5,"signed_home_handicap":None,"first_side_probability":.7,"candidate_direction":"OVER","frozen_direction":"OVER"},
          "CROWN_HANDICAP":{"line":5.5,"signed_home_handicap":-5.5,"first_side_probability":.4,"candidate_direction":"AWAY_COVER","frozen_direction":"AWAY_COVER"},
          "CROWN_TOTAL":{"line":205.5,"signed_home_handicap":None,"first_side_probability":.8,"candidate_direction":"OVER","frozen_direction":"OVER"}}
        games={}
        for key,m in keys.items():
            m.update({"market_data_status":"PRETIP_VALID","probability_status":"PRETIP_VALID",
                "quote_capture_utc":"2026-10-31T10:00:00+00:00",
                "market_consensus":{"eligible_same_line_benchmark":True,"first_side_probability":.55,
                  "latest_source_capture_utc":"2026-10-31T10:00:00+00:00","direct_line_matches_price_reference":True}})
            games[key]=m
        shadow={"target_date":day,"games":[{"game_id":"g1","home_team":"H","away_team":"A",
          "tipoff_beijing":"2026-11-01T08:00:00+08:00","decision_asof_utc":"2026-10-31T10:01:00+00:00","markets":games}]}
        (slotdir/"nba_dynamic_five_market_shadow.json").write_text(json.dumps(shadow))
        # Later post-tip snapshot is rejected and cannot replace the valid 18:00 sample.
        late=daily/day/"2100";late.mkdir(parents=True)
        bad=json.loads(json.dumps(shadow));bad["games"][0]["decision_asof_utc"]="2026-11-01T00:01:00+00:00"
        (late/"nba_dynamic_five_market_shadow.json").write_text(json.dumps(bad))
        settlement={"beijing_date":day,"games":[{"game_id":"g1","home_team":"H","away_team":"A","home_points":110,"away_points":100}]}
        (sd/"settlement.json").write_text(json.dumps(settlement))
        out=run(daily,settled)
        assert out["archived_shadow_snapshot_count"]==2
        assert out["latest_pretip_by_market"]["JINGCAI_WIN"]["n"]==1
        assert out["latest_pretip_by_market"]["JINGCAI_WIN"]["candidate_direction_accuracy"]["accuracy"]==1
        assert out["latest_pretip_by_market"]["JINGCAI_TOTAL"]["candidate_direction_accuracy"]["accuracy"]==0
        assert out["latest_pretip_by_market"]["CROWN_HANDICAP"]["candidate_direction_accuracy"]["accuracy"]==0
        assert out["latest_pretip_by_market"]["JINGCAI_WIN"]["consensus_benchmark"]["n"]==1
        assert out["production_model_modified"] is False and out["probability_fusion_enabled"] is False
        print("NBA_DYNAMIC_FIVE_MARKET_REPLAY_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--daily-root",default="reports/daily")
    p.add_argument("--settled-root",default="reports/five-market-settled")
    p.add_argument("--out",default="nba_dynamic_five_market_scorecard.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    try:result=run(a.daily_root,a.settled_root)
    except Exception as exc:
        result={"schema_version":"nba-dynamic-five-market-replay-v1",
          "status":"REPLAY_UNAVAILABLE","error_type":type(exc).__name__,"error":str(exc),
          "production_model_modified":False,"probability_fusion_enabled":False}
        print("NBA_DYNAMIC_FIVE_MARKET_REPLAY_UNAVAILABLE",type(exc).__name__,str(exc))
    Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_DYNAMIC_FIVE_MARKET_REPLAY",result.get("sample_readiness",{}).get("status",result.get("status")),
          result.get("latest_game_market_rows",0))
if __name__=="__main__":main()
