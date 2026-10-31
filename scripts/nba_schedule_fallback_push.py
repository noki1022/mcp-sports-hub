#!/usr/bin/env python3
"""Fail-safe fixture-only PushPlus when the full 007 analysis failed.

Never invent prices, probabilities or treat this as a completed model report.
Separate dedup namespace allows a later recovered full model report to send.
"""
import argparse
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from titan007_join_beijing_verified import fetch_schedule
from pushplus_mobile import send

def build(fixtures, target, slot):
    lines=["<div style='font-family:-apple-system,Arial;max-width:520px;line-height:1.65;color:#263548'>",
           "<h3>NBA 赛程保底通知｜正式盘口分析失败</h3>",
           f"<p>北京时间 {escape(slot[:2]+':'+slot[2:])}，比赛日期 {escape(target)}。</p>",
           "<p><b>007 盘口匹配或后续模型流水线未通过校验。</b>以下仅为官方赛程，"
           "没有真实盘口、模型概率或投注判断。五玩法均标记数据未就绪，不应据此下注。</p>"]
    for g in fixtures:
        tip=datetime.fromisoformat(g["beijing_tip"])
        if tip.date().isoformat()!=target:
            raise RuntimeError("FALLBACK_WRONG_BEIJING_DATE")
        lines.append("<p style='padding:7px 0;border-bottom:1px solid #ddd'>"
                     +escape(tip.strftime("%H:%M"))+"　"
                     +escape(g["home"])+"（主） vs "+escape(g["away"])+"（客）"
                     +"<br><small>竞彩胜负 / 让分 / 大小分；皇冠让分 / 大小分：数据未就绪</small></p>")
    lines.append("<p>系统将按后续计划重新抓取 007。此通知不替代正式分析。</p></div>")
    return "".join(lines)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--target",required=True)
    p.add_argument("--slot",required=True)
    p.add_argument("--marker-root",default="reports/schedule-fallback-sent")
    p.add_argument("--status",default="schedule_fallback_status.json")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        sample=[{"beijing_tip":"2026-11-01T08:00:00+08:00","home":"HOU","away":"OKC"}]
        assert "五玩法" in build(sample,"2026-11-01","1200")
        print("SCHEDULE_FALLBACK_SELF_TEST_PASS")
        return
    if args.slot not in ("1200","1400","1500","1800","2100"):
        raise RuntimeError("NOT_A_REGULAR_REPORT_SLOT")
    if datetime.fromisoformat(args.target).date() < datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise RuntimeError("EXPIRED_TARGET_DATE")
    marker=Path(args.marker_root)/args.target/(args.slot+".json")
    if marker.exists():
        state=json.loads(marker.read_text())
        if state.get("state")=="API_ACCEPTED_NOT_DEVICE_CONFIRMED":
            print("FALLBACK_ALREADY_API_ACCEPTED")
            return
    fixtures,_=fetch_schedule(args.target)
    if not fixtures:
        raise RuntimeError("NO_VERIFIED_OFFICIAL_FIXTURES_FOR_FALLBACK")
    token=os.environ.get("PUSHPLUS_TOKEN","")
    result=send({"title":f"NBA {args.slot[:2]}:{args.slot[2:]} 赛程保底通知｜盘口分析失败",
                 "html":build(fixtures,args.target,args.slot)},token)
    Path(args.status).write_text(json.dumps({"state":result["state"],"target":args.target,
        "slot":args.slot,"games":len(fixtures)},ensure_ascii=False))
    if result["state"]!="API_ACCEPTED_NOT_DEVICE_CONFIRMED":
        raise RuntimeError("FALLBACK_PUSHPLUS_NOT_ACCEPTED")
    marker.parent.mkdir(parents=True,exist_ok=True)
    marker.write_text(json.dumps({"state":result["state"],"target_date":args.target,
        "slot":args.slot,"games":len(fixtures),"run_id":os.environ.get("GITHUB_RUN_ID")})+"\n")
    print("FALLBACK_API_ACCEPTED_NOT_DEVICE_CONFIRMED",len(fixtures))

if __name__=="__main__":
    main()
