#!/usr/bin/env python3
"""Five-market probability calibration and exact-line market comparison.

Research-only. Uses frozen pre-tip model probabilities and settlement locks.
Per-market calibration is fitted on earlier Beijing dates only; optional
multi-company price comparisons require the exact same line and a pre-tip quote
captured no later than the frozen forecast. Nothing here changes production.
"""
from __future__ import annotations
import argparse, json, math, random, subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

MARKETS = ("JINGCAI_WIN", "JINGCAI_HANDICAP", "JINGCAI_TOTAL",
           "CROWN_HANDICAP", "CROWN_TOTAL")
MIN_EVENTS, MIN_DAYS = 100, 24


def dt(v):
    try:
        x = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x if x.tzinfo else None
    except (TypeError, ValueError):
        return None


def num(v):
    try:
        if v is None or isinstance(v, bool): return None
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def archive_commit_time(path):
    # Old frozen reports predate the explicit generated-at field. Their Git
    # commit time is a conservative upper bound on when the archive existed.
    try:
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(["git","log","-1","--format=%cI","--",str(path)],
                              cwd=root,capture_output=True,text=True,timeout=5,check=False)
        value=result.stdout.strip()
        return value if result.returncode==0 and value else None
    except (OSError,subprocess.TimeoutExpired):
        return None


def load_tree(root, pattern):
    out=[]
    base=Path(root)
    if not base.exists(): return out
    for p in sorted(base.glob(pattern)):
        try:
            x=json.loads(p.read_text(encoding="utf-8"))
            if isinstance(x,dict):
                if not x.get("analysis_generated_at_utc"):
                    x["_archive_commit_time_utc"]=archive_commit_time(p)
                out.append((p,x))
        except (OSError,ValueError,TypeError):
            continue
    return out


def score(rows, pkey="p"):
    n=len(rows)
    if not n:
        return {"n":0,"accuracy":None,"brier":None,"log_loss":None,"ece_10":None}
    eps=1e-12
    acc=brier=ll=0.0
    for r in rows:
        p=min(1-eps,max(eps,float(r[pkey]))); y=int(r["y"])
        acc += int((p>=.5)==bool(y))
        brier += (p-y)**2
        ll -= y*math.log(p)+(1-y)*math.log(1-p)
    ece=0.0
    for i in range(10):
        bucket=[r for r in rows if i/10<=r[pkey]<(i+1)/10 or
                (i==9 and r[pkey]==1)]
        if bucket:
            ece += len(bucket)/n*abs(
                sum(r[pkey] for r in bucket)/len(bucket) -
                sum(r["y"] for r in bucket)/len(bucket))
    return {"n":n,"accuracy":round(acc/n,6),"brier":round(brier/n,7),
            "log_loss":round(ll/n,7),"ece_10":round(ece,7)}


def fit_platt(rows):
    # Logistic calibration on logit(raw probability), Newton updates.
    eps=1e-6
    xs=[math.log(min(1-eps,max(eps,r["p"])) /
                 (1-min(1-eps,max(eps,r["p"])))) for r in rows]
    ys=[int(r["y"]) for r in rows]
    a,b=0.0,1.0
    for _ in range(100):
        g0=g1=h00=h01=h11=0.0
        for x,y in zip(xs,ys):
            z=max(-30,min(30,a+b*x)); q=1/(1+math.exp(-z))
            d=q-y; w=max(1e-8,q*(1-q))
            g0+=d; g1+=d*x
            h00+=w; h01+=w*x; h11+=w*x*x
        det=h00*h11-h01*h01
        if det<1e-12: break
        da=(h11*g0-h01*g1)/det
        db=(-h01*g0+h00*g1)/det
        a-=da; b-=db
        if max(abs(da),abs(db))<1e-8: break
    return {"intercept":a,"slope":b}


def apply_platt(model,p):
    eps=1e-6
    x=math.log(min(1-eps,max(eps,p))/(1-min(1-eps,max(eps,p))))
    z=max(-30,min(30,model["intercept"]+model["slope"]*x))
    return 1/(1+math.exp(-z))


def fit_isotonic(rows):
    # Aggregate tied input probabilities first; PAV must not emit duplicate x knots.
    grouped=defaultdict(lambda:[0.0,0])
    for r in rows:
        grouped[float(r["p"])][0]+=float(r["y"])
        grouped[float(r["p"])][1]+=1
    blocks=[]
    for p,(wins,count) in sorted(grouped.items()):
        blocks.append([p*count,wins,count,p,p])
        while len(blocks)>1 and blocks[-2][1]/blocks[-2][2] > blocks[-1][1]/blocks[-1][2]:
            x,z=blocks[-2],blocks[-1]
            blocks[-2:]=[[x[0]+z[0],x[1]+z[1],x[2]+z[2],x[3],z[4]]]
    return [{"x":x[0]/x[2],"y":x[1]/x[2],"lo":x[3],"hi":x[4],"n":x[2]}
            for x in blocks]


def apply_isotonic(model,p):
    if not model:return p
    if p<=model[0]["x"]:return model[0]["y"]
    if p>=model[-1]["x"]:return model[-1]["y"]
    for a,b in zip(model,model[1:]):
        if p<=b["x"]:
            if b["x"]<=a["x"]:return b["y"]
            w=(p-a["x"])/(b["x"]-a["x"])
            return a["y"]+w*(b["y"]-a["y"])
    return model[-1]["y"]


def chronological_calibration(rows):
    days=sorted({r["day"] for r in rows})
    base={"status":"BLOCKED_INSUFFICIENT_CHRONOLOGICAL_OOS",
          "sample_count":len(rows),"distinct_days":len(days),
          "minimum_events":MIN_EVENTS,"minimum_distinct_days":MIN_DAYS,
          "production_calibration_enabled":False}
    if len(rows)<MIN_EVENTS or len(days)<MIN_DAYS:return base
    cut=max(1,int(len(days)*.60))
    train_days=set(days[:cut]);test_days=set(days[cut:])
    train=[r for r in rows if r["day"] in train_days]
    test=[r for r in rows if r["day"] in test_days]
    if len(train)<50 or len(test)<20 or len({r["y"] for r in train})<2:
        return {**base,"status":"BLOCKED_SPLIT_OR_CLASS_SUPPORT",
                "train_n":len(train),"test_n":len(test)}
    platt=fit_platt(train)
    iso=fit_isotonic(train)
    scored=[]
    for r in test:
        scored.append({**r,"platt":apply_platt(platt,r["p"]),
                       "isotonic":apply_isotonic(iso,r["p"])})
    return {**base,"status":"SHADOW_HOLDOUT_SCORED",
            "split":{"train_n":len(train),"test_n":len(test),
                     "train_end":days[cut-1],"test_start":days[cut]},
            "train_class_counts":{"zero":sum(r["y"]==0 for r in train),
                                  "one":sum(r["y"]==1 for r in train)},
            "holdout":{"raw":score(scored),"platt":score(scored,"platt"),
                       "isotonic":score(scored,"isotonic")},
            "calibration_parameters":{"platt":platt,"isotonic_blocks":iso},
            "production_calibration_enabled":False}


def blend_shadow(rows):
    days=sorted({r["day"] for r in rows})
    base={"status":"BLOCKED_INSUFFICIENT_MATCHED_MARKET_SAMPLE",
          "paired_events":len(rows),"distinct_days":len(days),
          "production_fusion_enabled":False}
    if len(rows)<MIN_EVENTS or len(days)<MIN_DAYS:return base
    a=max(1,int(len(days)*.60));b=max(a+1,int(len(days)*.80))
    train_days=set(days[:a]);valid_days=set(days[a:b]);test_days=set(days[b:])
    train=[r for r in rows if r["day"] in train_days]
    valid=[r for r in rows if r["day"] in valid_days]
    test=[r for r in rows if r["day"] in test_days]
    if len(valid)<20 or len(test)<20:return {**base,"status":"BLOCKED_SPLIT_TOO_SMALL"}
    def loss(xs,w):
        return sum((((1-w)*r["model"]+w*r["market"])-r["y"])**2 for r in xs)/len(xs)
    weight=min((i/20 for i in range(21)),key=lambda w:(loss(valid,w),w))
    scored=[{**r,"blend":(1-weight)*r["model"]+weight*r["market"]} for r in test]
    grouped=defaultdict(list)
    for r in scored:grouped[r["day"]].append(r)
    rng=random.Random(20261101); ds=sorted(grouped); deltas=[]
    for _ in range(1000):
        sample=[r for d in [rng.choice(ds) for _ in ds] for r in grouped[d]]
        if sample:
            m=sum((r["model"]-r["y"])**2 for r in sample)/len(sample)
            c=sum((r["blend"]-r["y"])**2 for r in sample)/len(sample)
            deltas.append(c-m)
    deltas.sort()
    ci=[round(deltas[int(.025*(len(deltas)-1))],7),
         round(deltas[int(.975*(len(deltas)-1))],7)]
    return {"status":"SHADOW_HOLDOUT_SCORED","paired_events":len(rows),
            "distinct_days":len(days),"split":{"train":len(train),"validation":len(valid),
            "holdout":len(test),"train_end":days[a-1],"validation_end":days[b-1],
            "holdout_start":days[b]},"market_weight_selected_on_validation":weight,
            "holdout":{"independent_model":score(scored,"model"),
                       "market_consensus":score(scored,"market"),
                       "shadow_blend":score(scored,"blend")},
            "holdout_brier_delta_blend_minus_model_95pct_day_bootstrap_ci":ci,
            "production_fusion_enabled":False}


def evaluate(intraday_root,settled_root):
    forecasts=load_tree(intraday_root,"*/*.json")
    settlements=load_tree(settled_root,"*/settlement.json")
    fidx=defaultdict(list)
    for _,doc in forecasts:
        if doc.get("schema_version")!="nba-five-markets-v1":continue
        day=str(doc.get("target_date") or "")
        for game in doc.get("games",[]):
            fidx[(day,str(game.get("game_id") or ""))].append((doc,game))
    direct=defaultdict(dict);market=defaultdict(dict);rejects=Counter()
    for _,settle in settlements:
        day=str(settle.get("beijing_date") or settle.get("target_date") or "")
        for sg in settle.get("games",[]):
            gid=str(sg.get("game_id") or "")
            if not gid:continue
            actual_h,actual_a=num(sg.get("home_points")),num(sg.get("away_points"))
            if actual_h is None or actual_a is None:rejects["NO_FINAL_SCORE"]+=1;continue
            tip_candidates=[]
            for doc,game in fidx.get((day,gid),[]):
                tip=dt(game.get("tipoff_beijing"))
                gen=dt(doc.get("analysis_generated_at_utc") or doc.get("_archive_commit_time_utc"))
                board=dt(doc.get("board_capture_utc"))
                if tip is None or gen is None or board is None or gen>=tip or board>=tip:
                    rejects["INVALID_FROZEN_REPORT_TIME"]+=1;continue
                tip_candidates.append((gen,doc,game,tip))
            if not tip_candidates:rejects["NO_FROZEN_FORECAST"]+=1;continue
            _,doc,game,tip=max(tip_candidates,key=lambda x:x[0])
            settled=sg.get("markets") or {};pred=game.get("markets") or {}
            for key in MARKETS:
                s=settled.get(key) or {};p=pred.get(key) or {}
                st=dt(s.get("frozen_capture_utc"));pt=dt(p.get("captured_at_utc"))
                if st is None or pt is None or st!=pt or st>=tip:
                    rejects["SOURCE_CAPTURE_LOCK_MISMATCH"]+=1;continue
                outcome=s.get("outcome")
                if outcome not in ("HIT","MISS"):continue
                probability=num(p.get("model_direction_probability"))
                if probability is None or not 0<=probability<=1:
                    rejects["INVALID_MODEL_DIRECTION_PROBABILITY"]+=1;continue
                event={"day":day,"game_id":gid,"y":int(outcome=="HIT"),"p":probability}
                ekey=(day,gid,key)
                if ekey not in direct[key]:direct[key][ekey]=event
                ctx=p.get("market_consensus") or {}
                line=num(p.get("line"))
                ref_line=num(ctx.get("price_reference_line"))
                mp=num(ctx.get("market_price_probability_for_model_direction"))
                mtime=dt(ctx.get("market_price_latest_source_capture_utc"))
                count=int(ctx.get("same_line_company_count") or 0)
                if (ctx.get("market_price_consensus_status")=="AVAILABLE_SAME_LINE_MEDIAN"
                    and ctx.get("direct_line_matches_price_reference") is True
                    and line is not None and ref_line is not None and abs(line-ref_line)<=1e-6
                    and mp is not None and 0<=mp<=1 and count>=3
                    and mtime is not None and mtime<tip and mtime<=gen
                    and 0<=(gen-mtime).total_seconds()<=900):
                    market[key][ekey]={**event,"model":probability,"market":mp,
                                       "company_count":count}
                elif key!="JINGCAI_WIN":
                    rejects["NO_EXACT_DIRECT_LINE_MARKET_PRICE_PAIR"]+=1
    results={}
    for key in MARKETS:
        rows=list(direct[key].values())
        paired=list(market[key].values())
        results[key]={
            "frozen_independent_probability":score(rows),
            "chronological_calibration_shadow":chronological_calibration(rows),
            "exact_same_line_market_comparison":{
                "sample_count":len(paired),
                "distinct_days":len({r["day"] for r in paired}),
                "model":score(paired,"model"),
                "market":score(paired,"market"),
                "blend_research":blend_shadow(paired),
                "note":"Only paired when direct JC/Crown line equals actual multi-company price reference line; no cross-line interpolation."},
        }
    return {"schema_version":"nba-five-market-calibration-shadow-v1",
            "source":"007 frozen five-market predictions, 007 same-line multi-company quotes, settled official scores",
            "markets":results,"rejections":dict(sorted(rejects.items())),
            "production_fusion_enabled":False,"production_calibration_enabled":False,
            "decision":"SHADOW_RESEARCH_ONLY",
            "limitations":[
              "No moneyline multi-company quotes are present in the current 007 top-ten spread/total capture.",
              "JC/Crown direct line comparisons require exact same line; no interpolation.",
              "All source timestamps must precede the game and the forecast freeze.",
              "Calibration and fusion parameters are never written into production."
            ]}


def self_test():
    rows=[{"day":f"2026-01-{i:02d}","p":.7,"y":int(i%2==0)} for i in range(1,31)]
    assert score(rows)["n"]==30
    assert chronological_calibration(rows)["status"]=="BLOCKED_INSUFFICIENT_CHRONOLOGICAL_OOS"
    assert blend_shadow([{"day":"2026-01-01","model":.7,"market":.6,"y":1}])["production_fusion_enabled"] is False
    assert abs(apply_isotonic(fit_isotonic(rows),.7)-.5)<1e-9
    assert 0<=apply_platt(fit_platt(rows),.7)<=1
    print("NBA_FIVE_MARKET_CALIBRATION_SHADOW_SELF_TEST_PASS")


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--intraday-root",default="reports/five-market-intraday")
    ap.add_argument("--settled-root",default="reports/five-market-settled")
    ap.add_argument("--out")
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:self_test()
    else:
        result=evaluate(a.intraday_root,a.settled_root)
        payload=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
        if a.out:
            Path(a.out).parent.mkdir(parents=True,exist_ok=True)
            Path(a.out).write_text(payload,encoding="utf-8")
        print(json.dumps({"decision":result["decision"],
                          "markets":{k:{"n":v["frozen_independent_probability"]["n"],
                          "brier":v["frozen_independent_probability"]["brier"],
                          "paired_market_n":v["exact_same_line_market_comparison"]["sample_count"],
                          "calibration":v["chronological_calibration_shadow"]["status"]}
                          for k,v in result["markets"].items()},
                          "rejections":result["rejections"]},ensure_ascii=False),flush=True)
