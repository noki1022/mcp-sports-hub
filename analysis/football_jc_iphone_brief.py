#!/usr/bin/env python3
"""Compact NBA-style iPhone soccer JC briefing and 06:30 21:30 reversal notes.

The same display is used for 12:00/18:00/21:30/06:30.
Official JC integer three-way HHAD is not two-way Asian spread.
Only the 21:30 frozen answer is eligible for daily scorekeeping.
"""
from __future__ import annotations
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse,json,re

BJ=ZoneInfo("Asia/Shanghai")
LABELS={"had":"竞彩胜平负","hhad":"竞彩让球胜平负","ttg":"竞彩总进球数"}
def esc(x):
    return escape("—" if x is None else str(x),quote=True)
def percent(v):
    return "—" if v is None else f"{float(v)*100:.1f}%"
def clock(value):
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("UNVERIFIED_TIMEZONE")
    return d.astimezone(BJ).strftime("%m月%d日 %H:%M")
def signed(value):
    return "让球待核" if type(value) is not int else f"主{value:+d}"
def direction(m,k):
    if not isinstance(m,dict) or not isinstance(m.get("probabilities"),dict):
        return "暂无有效判断"
    if k=="ttg":
        v=m.get("goal_selection") or {}
        goals=v.get("goals") or []
        if not goals:return "进球数待核"
        return " / ".join(esc(x) for x in goals)+" · 合计"+percent(v.get("combined_probability"))
    return esc(m.get("direction"))+" · "+percent(m.get("direction_probability"))
def actual_market(m,k):
    market=m or {}
    suffix=("（"+signed(market.get("signed_home_handicap"))+"）") if k=="hhad" else ""
    prices=market.get("jc_odds")
    sale=(" · 竞彩未提供赔率" if prices is None else "")
    return f"<div style='padding:6px 0;border-top:1px solid #e5e9ef'><b>{LABELS[k]}{esc(suffix)}</b>　<b>{direction(market,k)}</b>{sale}</div>"
def key_tuple(row,key):
    if key=="ttg":
        d=(row.get("markets") or {}).get(key) or {}
        return tuple(sorted(((d.get("goal_selection") or {}).get("goals") or [])))
    return ((row.get("markets") or {}).get(key) or {}).get("direction")
def change_summary(comp):
    by_id={str(g["match_id"]):g for g in comp.get("games",[])}
    return by_id
def change_rows(comp,g):
    row=change_summary(comp).get(str(g.get("match_id"))) or {}
    lines=[]
    for c in row.get("changes",[]):
        k=c["market"]
        old=c.get("old")
        new=c.get("new")
        if isinstance(old,(list,tuple)):old=" / ".join(old)
        if isinstance(new,(list,tuple)):new=" / ".join(new)
        if k=="hhad":
            old=f"{old}（{signed(c.get('old_home_handicap'))}）"
            new=f"{new}（{signed(c.get('new_home_handicap'))}）"
        title=("竞彩让球变线" if c["type"]=="OFFICIAL_JC_HANDICAP_LINE_CHANGED" else "判断推翻")
        lines.append("<div style='margin-top:5px;padding:7px;background:#fff6e9;border-radius:7px'>"
          "<b>"+esc(title+" · "+LABELS[k])+"</b>"
          "<div>21:30 "+esc(old)+" → 06:30 "+esc(new)+"</div>"
          "<div style='font-size:12px;color:#68533c'>依据："+esc(c.get("basis"))+"</div></div>")
    return "".join(lines)
def render(report,mode="regular",comparison=None):
    if mode not in ("regular","final","update"):raise ValueError("INVALID_FOOTBALL_REPORT_MODE")
    if mode=="update" and not isinstance(comparison,dict):
        raise ValueError("MISSING_2130_COMPARISON")
    date=report.get("beijing_date")
    try:d=datetime.strptime(date,"%Y-%m-%d")
    except (ValueError,TypeError):raise ValueError("INVALID_BEIJING_DATE")
    label= "21:30 最终评分答卷" if mode=="final" else "06:30 临场更新" if mode=="update" else "赛前分析"
    result=[
      "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>",
      "<meta name='viewport' content='width=device-width,initial-scale=1'>",
      "<body style='font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;max-width:570px;margin:auto;background:#f4f6fa;padding:10px;font-size:14px;line-height:1.55;color:#23344a'>",
      f"<h2 style='font-size:19px;margin:8px 0'>北京时间{d.month}月{d.day}日 竞彩足球球赛研判</h2>",
      f"<p style='color:#51657d;font-size:12px;margin:5px 0'>"
      f"<b>{esc(label)}</b> · 竞彩胜平负 / 让球胜平负 / 总进球数</p>"
    ]
    if mode=="update":
        if comparison.get("schema_version")!="football-jc-0630-vs-final-v1" or not comparison.get("scoring_anchor_unchanged"):
            raise ValueError("INVALID_0630_VS_2130_PROVENANCE")
        n=comparison.get("reversals",0)
        m=comparison.get("changed_handicap_lines",0)
        result.append("<p style='font-size:12px'>较21:30：<b>"+esc(n)+"项判断推翻</b>，"
                      +esc(m)+"项官方让球改线。<b>赛后仅按21:30评分。</b></p>")
    if mode=="final":
        result.append("<p style='font-size:12px'>本版本冻结留档，赛后唯一评分依据；后续赔率变化不改写。</p>")
    for game in sorted(report.get("games",[]),key=lambda x:(str(x.get("jc_number")),str(x.get("kickoff_beijing")))):
        try:time=clock(game["kickoff_beijing"])
        except (KeyError,ValueError):time="比赛时间待核"
        info=game.get("data_quality") or {}
        m=game.get("markets") or {}
        h=(m.get("hhad") or {}).get("signed_home_handicap")
        goals=(game.get("goal_expectation") or {})
        assimilation=game.get("market_assimilation") or {}
        bookmakers=assimilation.get("company_count_used") if assimilation.get("status")=="APPLIED_BOUNDED_007_REAL_ASIAN" else 0
        result.append(
            "<section style='background:white;border:1px solid #e0e6f0;border-radius:10px;padding:11px;margin:9px 0'>"
            "<b>"+esc(game.get("jc_number"))+" · "+esc(game.get("league"))+"</b>"
            "<div style='font-weight:700;font-size:15px'>"
            +esc(game.get("home_team"))+"（主） vs "+esc(game.get("away_team"))+"（客）</div>"
            "<div style='font-size:12px;color:#63778c'>北京时间 "+esc(time)+" · 竞彩官方让球 "+esc(signed(h))+"</div>")
        if goals:
            result.append("<div style='font-size:12px;color:#64748b'>预期进球 主"+esc(goals.get("home"))
                          +" / 客"+esc(goals.get("away"))+" · 实盘亚盘采用"+esc(bookmakers)+"家有效机构</div>")
        for k in ("had","hhad","ttg"):
            result.append(actual_market(m.get(k),k))
        result.append("<div style='font-size:11px;color:#708095;margin-top:5px'>"
         "近五场 "+esc(info.get("home_recent"))+"/"+esc(info.get("away_recent"))
         +" · 交锋 "+esc(info.get("h2h"))+" · 伤停未经确认不作确定缺阵处理</div>")
        if mode=="update":result.append(change_rows(comparison,game))
        result.append("</section>")
    result.append("<footer style='font-size:11px;color:#66788d'>"
      "竞彩整数让球是三项玩法，非机构两项亚洲盘。主队在左、客队在右，所有时间为北京时间。"
      "模型概率尚未完成独立赛果校准。</footer></body></html>")
    return "".join(result)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--forecast",required=True)
    p.add_argument("--html",required=True)
    p.add_argument("--mode",choices=("regular","final","update"),default="regular")
    p.add_argument("--comparison")
    args=p.parse_args()
    forecast=json.loads(Path(args.forecast).read_text("utf-8"))
    if forecast.get("model_version")!="football-jc-poisson-asian-assimilation-v2":
        raise ValueError("ONLY_FUSED_FOOTBALL_FORECAST")
    comp=json.loads(Path(args.comparison).read_text("utf-8")) if args.comparison else None
    doc=render(forecast,args.mode,comp)
    path=Path(args.html);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(doc,"utf-8")
    print("FOOTBALL_JC_MOBILE_SINGLE_MODEL",args.mode,len(forecast.get("games",[])))
if __name__=="__main__":main()
