#!/usr/bin/env python3
"""Football-only frozen 21:30 final answer and 06:30 change disclosure.

Slot identity is based on GitHub scheduled cron, not approximate actual runner
start. A manually dispatched or delayed 06:30 run is NEVER allowed to overwrite
a previous 21:30 final. Compare by 007 match ID + JC number + teams + kickoff.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import argparse,copy,hashlib,json,sys
BJ=ZoneInfo("Asia/Shanghai")
MARKETS=("had","hhad","ttg")
def iso(t):
 d=datetime.fromisoformat(t.replace("Z","+00:00"))
 if d.tzinfo is None:raise ValueError("TIMEZONE_REQUIRED")
 return d.astimezone(timezone.utc)
def digest(obj):
 return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def id_key(row):
 return (str(row["match_id"]),str(row["jc_number"]),str(row["home_team"]),
         str(row["away_team"]),iso(row["kickoff_beijing"]))
def goals(row):
 m=(row.get("markets") or {}).get("ttg") or {}
 x=(m.get("goal_selection") or {}).get("goals")
 return tuple(x) if isinstance(x,list) and 1<=len(x)<=2 else None
def recommendation(row,market):
 m=(row.get("markets") or {}).get(market) or {}
 if market=="ttg":return goals(row)
 if market=="hhad":
  # A different official JC integer handicap is an actual changed event,
  # even if its direction label remains the same.
  return (m.get("signed_home_handicap"),m.get("direction"))
 return m.get("direction")
def describe(row,kind):
 if row is None:return "无有效判断"
 m=(row.get("markets") or {}).get(kind) or {}
 p=m.get("direction_probability")
 prob=f" {p*100:.1f}%" if type(p) in (float,int) else ""
 if kind=="ttg":
  x=goals(row)
  return " / ".join(x) if x else "无有效判断"
 if kind=="hhad":
  h=m.get("signed_home_handicap")
  sign=f"（主{h:+g}）" if type(h) is int else "（官方让球缺失）"
  return str(m.get("direction") or "无有效判断")+sign+prob
 return str(m.get("direction") or "无有效判断")+prob
def reason(now,old):
 parts=[]
 old_m=old.get("market_assimilation") or {}
 new_m=now.get("market_assimilation") or {}
 if old_m.get("status")!=new_m.get("status"):
  parts.append("机构亚盘可用性变化")
 if old_m.get("applied_home_minus_away_goals_shift")!=new_m.get("applied_home_minus_away_goals_shift"):
  parts.append("多家机构亚盘共识调整")
 old_l=old.get("goal_expectation") or {}
 new_l=now.get("goal_expectation") or {}
 if any(abs(float(new_l.get(s,0))-float(old_l.get(s,0)))>=.12 for s in ("home","away")):
  parts.append("双方近期数据或预期进球变化")
 o=old.get("data_quality") or {};n=now.get("data_quality") or {}
 if o.get("injury_verified")!=n.get("injury_verified"):
  parts.append("已核实伤停状态变化")
 if not parts:
  parts.append("模型概率与盘口综合判断改变；尚无单项原因证据")
 return "、".join(parts[:2])
def annotate(live,frozen,slot,run_id):
 if slot not in ("2130","0630","OTHER"):raise ValueError("INVALID_FOOTBALL_SLOT")
 result=copy.deepcopy(live)
 result["analysis_slot_beijing"]=slot
 result["scheduled_run_id"]=str(run_id)
 result["report_policy"]="FOOTBALL_SINGLE_FUSED_MODEL_2130_FINAL"
 result["model_ensemble"]="007_ACTUAL_AH_5_PREFERRED_INTEGRATED_SINGLE"
 result["scorecard_reference"]="FROZEN_2130_ONLY"
 result["report_is_final_for_grading"]=slot=="2130"
 result["scorecard_frozen_at_utc"]=result.get("generated_at_utc") if slot=="2130" else None
 result["final_snapshot_sha256"]=digest(live) if slot=="2130" else None
 result["0630_change_count"]=0
 if slot=="0630":
  if not isinstance(frozen,dict) or frozen.get("analysis_slot_beijing")!="2130" or not frozen.get("report_is_final_for_grading"):
   result["0630_comparison_status"]="NO_VERIFIED_2130_FROZEN_REPORT"
   for row in result.get("games",[]):row["change_from_2130_status"]="BASELINE_NOT_FOUND"
   return result
  frozen_stamp=iso(frozen["generated_at_utc"])
  if frozen_stamp>=iso(live["generated_at_utc"]):
   raise ValueError("FUTURE_2130_REFERENCE")
  prev={}
  for x in frozen["games"]:
   k=id_key(x)
   if k in prev:raise ValueError("DUPLICATE_FROZEN_2130_FIXTURE")
   prev[k]=x
  result["0630_comparison_status"]="VERIFIED_2130_REPORT"
  result["0630_reference_sha256"]=digest(frozen)
  result["0630_reference_generated_at_utc"]=frozen["generated_at_utc"]
  for row in result.get("games",[]):
   old=prev.get(id_key(row))
   if old is None:
    row["change_from_2130_status"]="MATCH_NOT_IN_2130_REPORT"
    continue
   changes={}
   for k in MARKETS:
    if recommendation(old,k)!=recommendation(row,k):
     changes[k]={"at_2130":describe(old,k),"at_0630":describe(row,k),
                 "basis":reason(row,old)}
   row["changes_from_2130"]=changes
   row["change_from_2130_status"]="REVERSED" if changes else "UNCHANGED"
   result["0630_change_count"]+=len(changes)
 elif slot=="2130":
  result["0630_comparison_status"]="NOT_APPLICABLE_FINAL_2130"
 return result
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--forecast",required=True)
 p.add_argument("--slot",choices=("2130","0630","OTHER"),required=True)
 p.add_argument("--frozen-2130")
 p.add_argument("--run-id",required=True)
 p.add_argument("--out",required=True)
 a=p.parse_args()
 live=json.loads(Path(a.forecast).read_text())
 frozen=json.loads(Path(a.frozen_2130).read_text()) if a.frozen_2130 else None
 out=annotate(live,frozen,a.slot,a.run_id)
 path=Path(a.out);path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
 print("FOOTBALL_SINGLE_2130_POLICY",out["analysis_slot_beijing"],
       "changes",out["0630_change_count"],"comparability",out.get("0630_comparison_status"))
if __name__=="__main__":main()
