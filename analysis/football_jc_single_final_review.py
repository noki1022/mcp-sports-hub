#!/usr/bin/env python3
"""NBA-style concise football JC 3-market review of ONLY frozen 21:00 answer.

Requires independently verified 007 full-time result source raw bytes.
Never re-run model, rewrite frozen answer, infer FT status or grade 06:30.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
from html import escape as E
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse,gzip,json,hashlib,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_jc_final_2130 as final
import football_jc_prospective_score as source

BJ=ZoneInfo("Asia/Shanghai")
KEYS=("had","hhad","ttg")
LABELS={"had":"竞彩胜平负","hhad":"竞彩让球胜平负","ttg":"竞彩总进球数"}
def signed(v):
 return f"主{v:+d}" if type(v) is int else "官方让球待核"
def actual(market,h,a,line):
 if market=="had":return "主胜" if h>a else "平" if h==a else "客胜"
 if market=="hhad":
  if type(line)is not int:return None
  d=h+line-a
  return "让胜" if d>0 else "让平" if d==0 else "让负"
 return (str(h+a)+"球") if h+a<7 else "7+球"
def picks(row,key):
 market=(row.get("markets") or {}).get(key) or {}
 if not isinstance(market.get("probabilities"),dict):return []
 if key=="ttg":
  selected=(market.get("goal_selection") or {}).get("goals")
  return selected if isinstance(selected,list) and 1<=len(selected)<=2 and len(set(selected))==len(selected) else []
 d=market.get("direction")
 return [d] if isinstance(d,str) and d else []
def review(locked,results,raw_evidence):
 if locked.get("schema_version")!=final.VERSION or not locked.get("scored_only_from_this_frozen_forecast"):
  raise ValueError("ONLY_FROZEN_2100_FINAL_COUNTS")
 forecast=locked.get("forecast") or {}
 if locked.get("final_forecast_sha256")!=final.sha(forecast):
  raise ValueError("2100_FROZEN_FORECAST_TAMPERED")
 finals=source.validate_results(results,raw_evidence)
 byid={str(row["match_id"]):row for row in locked["snapshot_facts"]}
 metrics={k:Counter() for k in KEYS}
 rows=[]
 for f in forecast["games"]:
  mid=str(f["match_id"])
  orig=byid[mid]
  outcome=finals.get(mid)
  entry={"match_id":mid,"jc_number":orig["jc_number"],"home_team":orig["home_team"],
         "away_team":orig["away_team"],"kickoff_beijing":orig["kickoff_beijing"],
         "home_goals":None,"away_goals":None,"markets":{}}
  if outcome is not None:
   # Check all identity and timeframe fields. A 007 provenance digest alone
   # does not independently prove source FT semantics: status must be verified
   # by an audited 007 parser before supplying results.
   source.verify_join({
      "match_id":mid,"jc_number":orig["jc_number"],
      "kickoff_beijing":orig["kickoff_beijing"],
      "home_team_id_007":orig["home_team_id_007"],
      "away_team_id_007":orig["away_team_id_007"]},
      outcome,final.as_dt(locked["actual_capture_utc"]))
   if final.as_dt(forecast["generated_at_utc"])>=final.as_dt(orig["kickoff_beijing"]):
    outcome=None
  if outcome:
   h,a=outcome["home_goals"],outcome["away_goals"]
   entry["home_goals"]=h;entry["away_goals"]=a
  for key in KEYS:
   predicted=picks(f,key)
   if outcome is None:
    entry["markets"][key]={"status":"UNSETTLED","predicted":predicted,"actual":None}
    metrics[key]["unsettled"]+=1
    continue
   line=orig.get("official_home_handicap")
   # Market on sale recorded at 21:00, not whatever odds show today.
   if key=="hhad" and type(line)is not int:
    entry["markets"][key]={"status":"EXCLUDED_NO_OFFICIAL_LINE","predicted":predicted,"actual":None}
    metrics[key]["excluded"]+=1
    continue
   target=actual(key,h,a,line)
   if not predicted:
    entry["markets"][key]={"status":"EXCLUDED_NO_DIRECTION","predicted":[],"actual":target}
    metrics[key]["excluded"]+=1
    continue
   outcome_name="HIT" if target in predicted else "MISS"
   metrics[key][outcome_name]+=1
   entry["markets"][key]={"status":outcome_name,"predicted":predicted,"actual":target,
                         "signed_home_handicap":line if key=="hhad" else None}
  rows.append(entry)
 summary={}
 for k,v in metrics.items():
  graded=v["HIT"]+v["MISS"]
  summary[k]={"hits":v["HIT"],"misses":v["MISS"],"excluded":v["excluded"],
              "unsettled":v["unsettled"],"graded":graded,
              "hit_rate":round(v["HIT"]/graded,6) if graded else None}
 return {"schema_version":"football-jc-2100-single-official-review-v1",
         "final_date_beijing":locked["slot_beijing_date"],
         "reference_only_frozen_2100_sha256":locked["final_forecast_sha256"],
         "source_result_manifest_sha256":final.sha(results),
         "summary":summary,"games":rows,
         "scoring_source":"ONLY_2100_FUSED_FROZEN_FORECAST",
         "no_0630_scoring":True,"no_unverified_results_grading":True}
def render(report):
 html=["<div style='max-width:540px;margin:auto;font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;"
       "font-size:14px;line-height:1.6;color:#20354d'>",
       "<h2 style='margin:0 0 8px'>北京时间"+E(report["final_date_beijing"])+" 竞彩足球复盘</h2>",
       "<div style='font-size:12px;color:#64748b'>仅按21:00冻结版评分｜主队在左、客队在右｜90分钟含补时，不含加时</div>"]
 for key in KEYS:
  v=report["summary"][key]
  val=f'{v["hit_rate"]*100:.1f}%（{v["hits"]}/{v["graded"]}）' if v["graded"] else "尚无有效样本"
  extra=f'　未入样{v["excluded"]}' if v["excluded"] else ""
  if v["unsettled"]:extra+=f'　未结算{v["unsettled"]}'
  html.append("<div style='border-bottom:1px solid #e5ebf0;padding:7px 0'><b>"+
              E(LABELS[key])+"</b>　<b>"+E(val)+"</b>"+E(extra)+"</div>")
 for g in report["games"]:
  h,a=g["home_goals"],g["away_goals"]
  exclusions={"007_KICKOFF_MISMATCH":"开赛时间冲突，未入样",
              "NO_PREKICKOFF_2100_PREDICTION":"21:00前已开赛，未入样",
              "REGULATION_STAGE_NOT_VERIFIED":"90分钟赛果口径未核实，未入样",
              "REGULATION_SCORE_AMBIGUOUS":"90分钟比分未核实，未入样"}
  score=f"{h}:{a}" if type(h)is int and type(a)is int else exclusions.get(g.get("exclusion_reason"),"赛果待核实")
  kickoff=final.as_dt(g["kickoff_beijing"]).astimezone(BJ).strftime("%m月%d日 %H:%M")
  html.append("<div style='border:1px solid #dbe4f0;border-radius:10px;margin:10px 0;padding:10px'>"
              "<b>"+E(g["jc_number"])+"　"+E(g["home_team"])+"（主） vs "+E(g["away_team"])+"（客）</b>"
              "<div style='font-size:12px;color:#64748b'>北京时间 "+E(kickoff)+"</div>"
              "<div>最终比分（主:客）：<b>"+E(score)+"</b></div>")
  for key in KEYS:
   info=g["markets"][key]
   sign="（"+signed(info["signed_home_handicap"])+"）" if key=="hhad" and type(info.get("signed_home_handicap"))is int else ""
   predicted=" / ".join(info["predicted"]) if info["predicted"] else "无有效判断"
   status={"HIT":"命中","MISS":"未中","UNSETTLED":"待赛果核实",
           "EXCLUDED_NO_OFFICIAL_LINE":"官方让球缺失，未入样",
           "EXCLUDED_NO_DIRECTION":"无有效判断，未入样","EXCLUDED_RESULT_EVIDENCE":"未入样"}.get(info["status"],"待核")
   extra="　实际："+str(info.get("actual"))+"｜比分"+score if info["status"]=="MISS" else ""
   color="#16834a" if info["status"]=="HIT" else "#c0392b" if info["status"]=="MISS" else "#64748b"
   html.append("<div style='border-top:1px solid #edf1f5;padding:4px 0'>"
               +E(LABELS[key])+"　"+E(predicted+sign)+"　<b style='color:"+color+"'>"
               +E(status)+"</b>"+E(extra)+"</div>")
  html.append("</div>")
 html.append("<p style='color:#64748b;font-size:11px'>命中率以21:00冻结版和已核验的90分钟赛果计算。</p></div>")
 return "".join(html)
def main():
 p=argparse.ArgumentParser()
 for name in ("locked","results","raw-dir","out","html"):p.add_argument("--"+name,required=True)
 a=p.parse_args()
 def read(path):
  b=Path(path).read_bytes()
  if len(b)>30_000_000:raise ValueError("REVIEW_INPUT_TOO_LARGE")
  return json.loads(b)
 locked,results=read(a.locked),read(a.results)
 raw={}
 for r in results.get("results",[]):
  mid=str(r["match_id"])
  path=Path(a.raw_dir)/(mid+".html.gz")
  if not path.is_file() or path.stat().st_size>1_000_000:
   raise ValueError("MISSING_VERIFIED_RAW_FT_ARCHIVE")
  with gzip.open(path,"rb") as file:body=file.read(2_000_001)
  if len(body)>2_000_000:raise ValueError("OVERSIZED_FT_EVIDENCE")
  raw[mid]=body
 result=review(locked,results,raw)
 d=Path(a.out);d.parent.mkdir(parents=True,exist_ok=True)
 d.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
 h=Path(a.html);h.parent.mkdir(parents=True,exist_ok=True)
 h.write_text(render(result))
 print("FOOTBALL_ONLY_2100_REVIEW",sum(x["graded"] for x in result["summary"].values()))
if __name__=="__main__":main()
