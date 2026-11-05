#!/usr/bin/env python3
"""Render compact, escaped, iPhone-friendly football Jingcai research HTML."""
from __future__ import annotations
import argparse
import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

MARKETS = (("had", "竞彩胜平负"), ("hhad", "竞彩让球胜平负"), ("ttg", "竞彩总进球数"))


def esc(v):
    return html.escape("—" if v is None or v == "" else str(v), quote=True)


def percent(p):
    return "—" if p is None else f"{100 * float(p):.1f}%"


def beijing_clock(raw):
    try:
        t=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        if t.tzinfo is None:return "时间待核"
        return t.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m月%d日 %H:%M")
    except (ValueError,TypeError):
        return "时间待核"

def signed_home(n):
    return "主"+(f"{n:+d}" if type(n) is int else "盘口待核")

def direction_label(key,direction,handicap=None):
    if key=="ttg":
        if isinstance(direction,(tuple,list)):return " / ".join(direction)
        return str(direction or "无有效判断")
    if key=="hhad":
        return str(direction or "无有效判断")+"（"+signed_home(handicap)+"）"
    return str(direction or "无有效判断")

def change_notes(comparison,mid):
    if not comparison:return ""
    item=next((x for x in comparison.get("games",[]) if x.get("match_id")==mid),None)
    if not item:return ""
    lines=[]
    for change in item.get("changes",[]):
        key=change["market"]
        name=dict(MARKETS)[key]
        old=direction_label(key,change["old"],change.get("old_home_handicap"))
        new=direction_label(key,change["new"],change.get("new_home_handicap"))
        lines.append("<div style='padding:6px 8px;background:#fff5e8;border-radius:6px;margin-top:5px;'>"
                     "<b>06:30变更｜"+esc(name)+"</b>　21:30 "+esc(old)+" → 现在 <b>"+esc(new)+
                     "</b><div style='font-size:12px;color:#80552d;'>依据："+esc(change["basis"])+"</div></div>")
    return "".join(lines)

def market_card(key, name, market):
    status = market.get("status", "UNAVAILABLE")
    probs = market.get("probabilities") or {}
    direction = esc(market.get("direction"))
    handicap = market.get("signed_home_handicap")
    suffix = ("（主队" + (f"+{handicap}" if handicap > 0 else str(handicap))
              + "球）") if key == "hhad" and handicap is not None else ""
    odds = market.get("jc_odds")
    values = " · ".join(f"{esc(side)} {percent(p)}" for side, p in probs.items()) if probs else "数据不足，不能计算"
    is_research = bool(probs)
    line = (f"<strong>{direction}　{percent(market.get('direction_probability'))}</strong>"
            if is_research else "<strong>暂无有效判断</strong>")
    if key == "ttg" and (market.get("goal_selection") or {}).get("goals"):
        chosen = market["goal_selection"]
        direction = esc(" / ".join(chosen["goals"]))
        line = ("<strong>进球数推荐：" + direction + "　合计概率 "
                + percent(chosen.get("combined_probability")) + "</strong>")
    availability = ("｜竞彩赔率缺失" if odds is None else "｜竞彩赔率 " + "/".join(esc(v) for v in odds))
    return (f"<div style='padding:7px 0;border-top:1px solid #edf1f5;'>"
            f"<div style='font-weight:650;color:#223;'> {esc(name)}{esc(suffix)}</div>"
            f"<div style='font-size:15px;color:#172a40;margin-top:3px;'>{line}</div>"
            f"<div style='font-size:12px;color:#657585;margin-top:3px;'>{values}</div>"
            f"<div style='font-size:11px;color:#8592a2;margin-top:2px;'>{esc(status)}{esc(availability)}</div></div>")


def render(report,comparison=None,mode=None):
    date = esc(report.get("beijing_date"))
    slot=report.get("analysis_slot_beijing")
    version_label="21:30最终评分版" if slot=="2130" else "06:30最新判断（评分仍以21:30为准）" if slot=="0630" else "模型研判"
    phase=mode or "research"
    tag={"final":"21:30最终评分版（已锁定）","update":"06:30动态更新｜以21:30为评分准绳"}.get(phase,"竞彩足球融合研判")
    cards = []
    for game in report.get("games", []):
        title = (esc(game.get("jc_number")) + " · " + esc(game.get("league"))
                 + "　" + esc(game.get("home_team")) + " vs " + esc(game.get("away_team")))
        kickoff = esc(beijing_clock(game.get("kickoff_beijing")))
        quality = game.get("data_quality") or {}
        details = "近5场 " + esc(quality.get("home_recent")) + "/" + esc(quality.get("away_recent"))
        listed = quality.get("injury_listed_players_unconfirmed")
        detail_injury = ("007伤停名单 "+esc(listed)+"人（出场待核实）") if isinstance(listed,int) and listed>0 else "伤停待核实"
        details += "　历史交锋 " + esc(quality.get("h2h")) + "　" + detail_injury
        expectations = game.get("goal_expectation") or {}
        score = game.get("top_score") or {}
        if expectations:
            context = ("模型进球预期：主 " + esc(expectations.get("home"))
                       + " / 客 " + esc(expectations.get("away"))
                       + "　候选比分 " + esc(score.get("home")) + ":" + esc(score.get("away")))
        else:
            context = "数据未达到建模要求：" + esc(game.get("reason", "未提供有效赛前统计"))
        change_html=""
        for k,label in MARKETS:
            item=(game.get("changes_from_2130") or {}).get(k)
            if item:
                change_html += ("<div style='border-left:3px solid #c47d23;padding:6px;font-size:12px'>"
                                +esc(label)+" 改判：21:30 "+esc(item["at_2130"])
                                +" → 06:30 "+esc(item["at_0630"])
                                +"<div>依据："+esc(item["basis"])+"</div></div>")
        if slot=="0630" and game.get("change_from_2130_status")=="BASELINE_NOT_FOUND":
            change_html="<div style='color:#a35d25'>21:30冻结答卷缺失，无法核对改判</div>"
        market_html = "".join(market_card(k, n, (game.get("markets") or {}).get(k) or {})
                              for k, n in MARKETS)
        cards.append(
            "<section style='background:white;margin:11px 0;padding:12px;border:1px solid #e4e9f0;border-radius:12px;'>"
            + "<div style='font-size:15px;font-weight:700;color:#18283b;'>" + title + "</div>"
            + "<div style='color:#607387;font-size:12px;margin:4px 0;'>北京时间 " + kickoff + "</div>"
            + "<div style='font-size:12px;color:#566a7e;line-height:1.5;margin:5px 0;'>"
            + context + "</div>"
            + market_html + change_html
            + change_notes(comparison,str(game.get("match_id")))
            + "<div style='color:#758497;font-size:11px;margin-top:6px;'>数据质量：" + details
            + "　状态：" + esc(game.get("status")) + "</div></section>")
    if not cards:
        cards.append("<p>当前没有通过验证的 007 足球赛前数据；不生成任何虚构推荐。</p>")
    if slot=="0630" and report.get("0630_comparison_status")!="VERIFIED_2130_REPORT":
        cards.insert(0,"<p style='color:#a35d25'>未取得21:30冻结版本，无法核实方向变化。</p>")
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>北京时间 " + date + " 竞彩足球球赛研判</title></head>"
        "<body style='font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;"
        "background:#f4f6f9;color:#24364a;margin:0;padding:12px;max-width:700px;'>"
        "<header style='padding:10px 4px;'><h1 style='font-size:20px;margin:0;'>北京时间 "
        + date + " 竞彩足球球赛研判</h1><b>"+esc(version_label)+"</b>"
        "<div style='font-size:12px;color:#5f7082;margin-top:6px;'>"
        + esc(tag) + "｜胜平负 / 让球胜平负 / 总进球数（三玩法）</div></header>"
        + "".join(cards)
        + "<footer style='font-size:12px;color:#738196;line-height:1.6;margin:12px 3px;'>"
        "模型尚未完成真实赛前样本回测和概率校准；方向和概率不代表盈利保证。"
        "未核验的伤停、竞彩赔率或让球数必须明确标注；仅输出竞彩足球三玩法。"
        "采集时间 " + esc(report.get("captured_at_utc")) + "　来源状态：" + esc(report.get("source_status")) + "</footer></body></html>"
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--forecast", required=True)
    p.add_argument("--comparison")
    p.add_argument("--mode",choices=("final","update","research"),default="research")
    p.add_argument("--html", default="football_jc_mobile.html")
    a = p.parse_args()
    data = json.loads(Path(a.forecast).read_text(encoding="utf-8"))
    if data.get("model_version", "").split("-")[0:2] != ["football", "jc"]:
        raise SystemExit("NOT_FOOTBALL_JC_FORECAST")
    dest = Path(a.html)
    dest.parent.mkdir(parents=True, exist_ok=True)
    comparison=json.loads(Path(a.comparison).read_text(encoding="utf-8")) if a.comparison else None
    if a.mode=="update" and comparison is None:raise SystemExit("0630_COMPARISON_REQUIRED")
    dest.write_text(render(data,comparison,a.mode), encoding="utf-8")
    print("FOOTBALL_JC_MOBILE_REPORT", len(data.get("games", [])))


if __name__ == "__main__":
    main()
