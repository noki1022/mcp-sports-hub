#!/usr/bin/env python3
"""Score ONLY the frozen 21:30 integrated soccer forecast from 007 real finals.

No shadow comparison. A pending or unverified final is never treated as a
loss, miss, correct pick, or push. Official signed home JC handicap is a
three-way event, not an Asian two-way event. Total-goals may pick two
independent bins; scoring reports both the top-one and allowed 1/2 coverage.

Raw byte SHA verification is necessary but not sufficient to verify the FT
*meaning*. A future 007-native validated parser must generate the final file.
"""
from __future__ import annotations
import argparse,gzip,json,math,sys
from collections import Counter
from datetime import datetime,timezone
from html import escape as esc
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_jc_final_2130 as frozen
import football_jc_prospective_score as sources
import football_jc_probability as model

LABELS={"had":model.HAD,"hhad":model.HHAD,"ttg":model.TTG}
TITLES={"had":"胜平负","hhad":"让球胜平负","ttg":"总进球数"}
BJ=ZoneInfo("Asia/Shanghai")

def official_open(fact,kind):
    # Quote availability from final's original input may be stored in the
    # forecast market's jc_odds. A missing official market is not a miss.
    return fact is not None

def extract_probs(row,key):
    m=(row.get("markets") or {}).get(key) or {}
    p=m.get("probabilities")
    if not isinstance(p,dict) or set(p)!=set(LABELS[key]):return None
    arr=[p[x] for x in LABELS[key]]
    if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 or x>1 for x in arr):
        return None
    if abs(sum(arr)-1)>.00006:
        raise ValueError("INVALID_FINAL_PROBABILITY_MASS")
    return arr

def score_one(key,row,fact,final):
    m=(row.get("markets") or {}).get(key) or {}
    if m.get("jc_odds") is None:
        return {"status":"EXCLUDED_NOT_ON_SALE"}
    probs=extract_probs(row,key)
    if probs is None:
        return {"status":"EXCLUDED_NO_VALID_MODEL_PROBABILITY"}
    score_h,score_a=final["home_goals"],final["away_goals"]
    handicap=fact.get("official_home_handicap")
    if key=="hhad":
        if type(handicap) is not int:
            return {"status":"EXCLUDED_OFFICIAL_HANDICAP_MISSING"}
        d=score_h+handicap-score_a
        index=0 if d>0 else 1 if d==0 else 2
    elif key=="had":
        index=0 if score_h>score_a else 1 if score_h==score_a else 2
    else:index=min(score_h+score_a,7)
    event=LABELS[key][index]
    # Actual direction is frozen; no after-the-fact repick.
    if key=="ttg":
        picks=(m.get("goal_selection") or {}).get("goals") or []
        if not isinstance(picks,list) or not 1<=len(picks)<=2 or len(set(picks))!=len(picks) or any(x not in LABELS[key] for x in picks):
            return {"status":"EXCLUDED_INVALID_TTG_SELECTION"}
        hit=event in picks
        chosen=" / ".join(picks)
    else:
        chosen=m.get("direction")
        if chosen not in LABELS[key]:
            return {"status":"EXCLUDED_INVALID_DIRECTION"}
        hit=chosen==event
    p=probs[index]
    return {"status":"HIT" if hit else "MISS",
      "frozen_pick":chosen,"actual_market_result":event,
      "official_home_handicap":handicap if key=="hhad" else None,
      "actual_home_goals":score_h,"actual_away_goals":score_a,
      "top1_hit":int(max(range(len(probs)),key=probs.__getitem__)==index),
      "log_loss":-math.log(max(p,1e-12)),
      "brier":sum((v-float(i==index))**2 for i,v in enumerate(probs))}

def grade(lock,results,raw_evidence):
    if lock.get("schema_version")!=frozen.VERSION or lock.get("no_shadow_model") is not True or lock.get("scored_only_from_this_frozen_forecast") is not True:
        raise ValueError("ONLY_SINGLE_2130_FOOTBALL_FINAL_IS_GRADED")
    report=lock["forecast"]
    if frozen.sha(report)!=lock.get("final_forecast_sha256"):
        raise ValueError("LOCKED_2130_PREDICTION_TAMPERED")
    if report.get("model_version")!=frozen.FUSED_VERSION:
        raise ValueError("ONLY_INTEGRATED_MODEL_GRADED")
    verified=sources.validate_results(results,raw_evidence)
    facts={str(x["match_id"]):x for x in lock["snapshot_facts"]}
    totals={key:Counter() for key in LABELS}
    metrics={key:[] for key in LABELS}
    rows=[];rejected=[]
    for forecast in report["games"]:
        mid=str(forecast["match_id"])
        fact=facts.get(mid)
        if fact is None:raise ValueError("MISSING_LOCKED_FACT")
        row={"match_id":mid,"jc_number":fact["jc_number"],
          "home_team":fact["home_team"],"away_team":fact["away_team"],
          "kickoff_beijing":fact["kickoff_beijing"],"markets":{}}
        actual=verified.get(mid)
        if actual is None:
            row["status"]="AWAITING_VERIFIED_007_FT"
            for key in LABELS:
                row["markets"][key]={"status":"UNSETTLED"}
            rows.append(row);continue
        try:
            # Only score matches that were not yet underway when frozen.
            if frozen.as_dt(report["generated_at_utc"])>=frozen.as_dt(fact["kickoff_beijing"]):
                raise ValueError("2130_LOCK_CREATED_AFTER_MATCH_KICKOFF")
            sources.verify_join(fact,actual,frozen.as_dt(lock["actual_capture_utc"]))
        except (ValueError,KeyError) as e:
            rejected.append({"match_id":mid,"reason":str(e)})
            row["status"]="REJECTED_RESULT_OR_LOCK"
            for key in LABELS:row["markets"][key]={"status":"UNSETTLED"}
            rows.append(row);continue
        row["status"]="VERIFIED_FINAL_CONTRACT"
        row["home_goals"]=actual["home_goals"];row["away_goals"]=actual["away_goals"]
        for key in LABELS:
            data=score_one(key,forecast,fact,actual)
            row["markets"][key]=data
            totals[key][data["status"]]+=1
            if data["status"] in ("HIT","MISS"):
                metrics[key].append(data)
        rows.append(row)
    summary={}
    for key,counts in totals.items():
        good=counts["HIT"];bad=counts["MISS"];n=good+bad
        summary[key]={"hits":good,"misses":bad,"graded":n,
                      "hit_rate":round(good/n,4) if n else None,
                      "excluded":sum(v for k,v in counts.items() if k.startswith("EXCLUDED")),
                      "pending":sum(r["markets"][key]["status"]=="UNSETTLED" for r in rows),
                      "brier":round(sum(x["brier"] for x in metrics[key])/n,6) if n else None,
                      "log_loss":round(sum(x["log_loss"] for x in metrics[key])/n,6) if n else None}
    return {"schema_version":"football-jc-2130-single-review-v1",
       "slot_beijing_date":lock["slot_beijing_date"],
       "only_scoring_21_30_forecast_sha256":lock["final_forecast_sha256"],
       "never_score_0630_or_other_forecast":True,
       "finals_source_status":"RAW_HASH_AND_METADATA_ACCEPTED__REQUIRES_SEMANTIC_007_FT_PARSER",
       "summary":summary,"games":rows,"rejected_results":rejected,
       "no_unverified_result_counted":True}

def render_html(review):
    output=["<div style='max-width:540px;margin:auto;font-family:-apple-system,Arial,sans-serif;font-size:14px;color:#203149;line-height:1.6'>",
      "<h2>北京时间"+esc(review["slot_beijing_date"])+" 足球三玩法复盘</h2>",
      "<p style='font-size:12px;color:#64748b'>仅以21:30冻结答卷评分，06:30更新不计分。主队在左，客队在右；90分钟含伤停补时。</p>",
      "<h3>三玩法命中率</h3>"]
    for k in LABELS:
        s=review["summary"][k]
        rate=f'{s["hit_rate"]*100:.1f}%' if s["hit_rate"] is not None else "暂无有效样本"
        output.append("<div style='padding:5px 2px;border-bottom:1px solid #dfe6ef'><b>"+
                      esc(TITLES[k])+"</b> <b>"+rate+"</b>（"+str(s["hits"])+"/"+str(s["graded"])+
                      "） 未入样"+str(s["excluded"])+" · 待核实"+str(s["pending"])+"</div>")
    output.append("<h3>逐场复盘</h3>")
    for g in review["games"]:
        try:clock=frozen.as_dt(g["kickoff_beijing"]).astimezone(BJ).strftime("%m月%d日 %H:%M")
        except (ValueError,KeyError):clock="时间待核"
        score=f'{g["home_goals"]}:{g["away_goals"]}' if g.get("status")=="VERIFIED_FINAL_CONTRACT" else "待核实"
        output.append("<div style='padding:10px;margin:8px 0;border:1px solid #dbe4f0;border-radius:9px'>"
            "<b>"+esc(str(g["jc_number"]))+"　主："+esc(str(g["home_team"]))+
            "　客："+esc(str(g["away_team"]))+"</b><div>北京时间 "+clock+
            "｜比分（主:客）<b>"+score+"</b></div>")
        for key,title in TITLES.items():
            m=g["markets"][key];status=m["status"]
            if status in ("HIT","MISS"):
                label="命中" if status=="HIT" else "未中"
                signed=m.get("official_home_handicap")
                line=f"（主{signed:+d}）" if type(signed) is int else ""
                actual="；实际 "+str(m["actual_market_result"]) if status=="MISS" else ""
                line_info=" · 赛果 "+score if status=="MISS" else ""
                output.append("<div>"+esc(title)+line+"：<b>"+esc(str(m["frozen_pick"]))+"</b>　"+
                              label+esc(actual)+esc(line_info)+"</div>")
            else:output.append("<div>"+esc(title)+"：<b>未入样 / 赛果待核</b></div>")
        output.append("</div>")
    output.append("<p style='font-size:11px;color:#64748b'>缺少经过独立语义验证的007完场记录不能计分；不根据06:30或赛后盘口改写21:30预测。</p></div>")
    return "".join(output)

def cli():
    p=argparse.ArgumentParser()
    for name in ("locked","results","raw-dir","out","html"):
        p.add_argument("--"+name,required=True)
    a=p.parse_args()
    def read(path):
        b=Path(path).read_bytes()
        if len(b)>20_000_000:raise ValueError("INPUT_TOO_LARGE")
        return json.loads(b)
    results=read(a.results)
    raw_root=Path(a.raw_dir)
    evidence={}
    for r in results.get("results",[]):
        mid=str(r.get("match_id") or "")
        if not mid.isdecimal():raise ValueError("UNSAFE_007_ID")
        path=raw_root/(mid+".html.gz")
        with gzip.open(path,"rb") as fp:
            evidence[mid]=fp.read(2_000_001)
    report=grade(read(a.locked),results,evidence)
    dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    html=Path(a.html);html.parent.mkdir(parents=True,exist_ok=True)
    html.write_text(render_html(report),encoding="utf-8")
    print("FOOTBALL_2130_SINGLE_FINAL_GRADE",sum(x["graded"] for x in report["summary"].values()),
         "markets; unverified finals not counted")
if __name__=="__main__":cli()
