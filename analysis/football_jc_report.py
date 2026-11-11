#!/usr/bin/env python3
"""Render compact, escaped, iPhone-friendly football Jingcai research HTML."""
from __future__ import annotations
import argparse
import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

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

def movement_notes(movement,mid,forecast_capture):
    if not movement:return ""
    if movement.get("schema_version")!="football-007-asof-hourly-movement-v1":
        raise ValueError("UNVERIFIED_FOOTBALL_MOVEMENT_SCHEMA")
    item=next((x for x in movement.get("games",[]) if str(x.get("match_id"))==str(mid)),None)
    if not item:return ""
    if item.get("current_capture_utc")!=forecast_capture:
        raise ValueError("MOVEMENT_FROM_DIFFERENT_007_CAPTURE")
    if item.get("status")=="FIRST_VERIFIED_OBSERVATION_NO_PREVIOUS_SNAPSHOT":
        return "<div style='font-size:12px;color:#6b7280'>首次有效抓取：暂无上一时点可比，正常建立基准。</div>"
    labels={"MODEL_DIRECTION_REVERSED":"模型方向反转",
            "OFFICIAL_JC_ODDS_MOVED":"竞彩赔率变动",
            "MODEL_PROBABILITY_MOVEMENT_PP":"模型概率更新",
            "JC_HANDICAP_CHANGED":"竞彩让球改线",
            "CONFIRMED_INJURY_PLAYER_IDS":"核实伤停名单变化",
            "007_ASIAN_COMPANIES_FUSION_MARGIN_SHIFT":"多家亚洲盘口影响变化",
            "MODEL_EXPECTED_GOALS_HOME":"主队进球预期调整",
            "MODEL_EXPECTED_GOALS_AWAY":"客队进球预期调整"}
    texts=[]
    for change in item.get("changes",[]):
        kind=change.get("kind")
        if kind not in labels:continue
        market=dict(MARKETS).get(change.get("market"),"")
        if kind=="MODEL_DIRECTION_REVERSED":
            detail="（"+str(change.get("before"))+"→"+str(change.get("after"))+"）"
        elif kind=="JC_HANDICAP_CHANGED":
            detail="（主"+str(change.get("before"))+"→"+str(change.get("after"))+"）"
        else:detail=""
        texts.append(market+labels[kind]+detail)
        if len(texts)==3:break
    if not texts:return ""
    return "<div style='font-size:12px;color:#495f79;padding:5px 0'>与上次抓取相比：" + esc("；".join(texts)) + "</div>"

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


def render(report,comparison=None,mode=None,movement=None):
    date = esc(report.get("beijing_date"))
    phase=mode or "research"
    tag={"final":"21:30历史基准（独立保留）","update":"06:30动态更新｜21:30仅用于历史对照"}.get(phase,"竞彩足球融合研判")
    cards = []
    for game in report.get("games", []):
        title = (esc(game.get("jc_number")) + " · " + esc(game.get("league"))
                 + "　" + esc(game.get("home_team")) + "（主） vs " + esc(game.get("away_team")) + "（客）")
        kickoff = esc(beijing_clock(game.get("kickoff_beijing")))
        quality = game.get("data_quality") or {}
        details = "近5场 " + esc(quality.get("home_recent")) + "/" + esc(quality.get("away_recent"))
        listed = quality.get("injury_listed_players_unconfirmed")
        detail_injury = ("007伤停名单 "+esc(listed)+"人（出场待核实）") if isinstance(listed,int) and listed>0 else "伤停待核实"
        details += "　历史交锋 " + esc(quality.get("h2h")) + "　" + detail_injury
        expectations = game.get("goal_expectation") or {}
        if expectations:
            context = ("模型进球预期：主 " + esc(expectations.get("home"))
                       + " / 客 " + esc(expectations.get("away")))
        else:
            context = "数据未达到建模要求：" + esc(game.get("reason", "未提供有效赛前统计"))
        market_html = "".join(market_card(k, n, (game.get("markets") or {}).get(k) or {})
                              for k, n in MARKETS)
        cards.append(
            "<section style='background:white;margin:11px 0;padding:12px;border:1px solid #e4e9f0;border-radius:12px;'>"
            + "<div style='font-size:15px;font-weight:700;color:#18283b;'>" + title + "</div>"
            + "<div style='color:#607387;font-size:12px;margin:4px 0;'>北京时间 " + kickoff + "</div>"
            + "<div style='font-size:12px;color:#566a7e;line-height:1.5;margin:5px 0;'>"
            + context + "</div>"
            + market_html
            + change_notes(comparison,str(game.get("match_id")))
            + movement_notes(movement,str(game.get("match_id")),report.get("captured_at_utc"))
            + "<div style='color:#758497;font-size:11px;margin-top:6px;'>数据质量：" + details
            + "　状态：" + esc(game.get("status")) + "</div></section>")
    if not cards:
        cards.append("<p>当前没有通过验证的 007 足球赛前数据；不生成任何虚构推荐。</p>")
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>北京时间 " + date + " 竞彩足球球赛研判</title></head>"
        "<body style='font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;"
        "background:#f4f6f9;color:#24364a;margin:0;padding:12px;max-width:700px;'>"
        "<header style='padding:10px 4px;'><h1 style='font-size:20px;margin:0;'>北京时间 "
        + date + " 竞彩足球球赛研判</h1>"
        "<div style='font-size:12px;color:#5f7082;margin-top:6px;'>"
        + esc(tag) + "｜胜平负 / 让球胜平负 / 总进球数（三玩法）</div></header>"
        + "".join(cards)
        + "<footer style='font-size:12px;color:#738196;line-height:1.6;margin:12px 3px;'>"
        "模型尚未完成真实赛前样本回测和概率校准；方向和概率不代表盈利保证。"
        "未核验的伤停、竞彩赔率或让球数必须明确标注；仅输出竞彩足球三玩法。"
        "采集时间 " + esc(report.get("captured_at_utc")) + "　来源状态：" + esc(report.get("source_status")) + "</footer></body></html>"
    )



# The order is the 007竞彩 quote order, independent of the model's ranking.
PUSH_OPTIONS = {
    "had": ("主胜", "平", "客胜"),
    "hhad": ("让胜", "让平", "让负"),
    "ttg": tuple(f"{n}球" for n in range(7)) + ("7+球",),
}


def push_market_line(key, name, market):
    options = PUSH_OPTIONS[key]
    odds = market.get("jc_odds")
    probs = market.get("probabilities") or {}
    direction = market.get("direction")
    probability = market.get("direction_probability")
    prefix = f"<b>{name}</b>　"
    if key == "hhad":
        handicap = market.get("signed_home_handicap")
        prefix += (f"主队 {handicap:+d} 球，" if type(handicap) is int else "让球待核，")

    def quote(option):
        if isinstance(odds, (list, tuple)) and len(odds) == len(options) and option in options:
            value = odds[options.index(option)]
            if value is not None and value != "":
                return f"（赔率 {esc(value)}）"
        return "（赔率缺失）"

    if not direction or probability is None:
        return prefix + "暂无有效判断"
    if key == "ttg":
        selection = market.get("goal_selection") or {}
        goals = [str(goal) if str(goal).endswith("球") else f"{goal}球"
                 for goal in selection.get("goals", [])]
        if goals:
            picks = " / ".join(esc(goal) + quote(goal) for goal in goals)
            combined = selection.get("combined_probability")
            return prefix + picks + (f"，合计 <b>{percent(combined)}</b>" if combined is not None else "")
    line = prefix + f"<b>{esc(direction)} {percent(probability)}</b>" + quote(direction)
    if key == "had" and direction in options:
        alternatives = [(side, probs[side]) for side in options
                        if side != direction and probs.get(side) is not None]
        if alternatives:
            side, runner_up = max(alternatives, key=lambda entry: entry[1])
            if abs(probability - runner_up) < 0.03:
                line += f" / {side} {percent(runner_up)}{quote(side)}，方向接近"
    return line


def push_movement_note(movement, game, captured):
    if not movement:
        return ""
    if movement.get("schema_version") != "football-007-asof-hourly-movement-v1":
        raise ValueError("UNVERIFIED_FOOTBALL_MOVEMENT_SCHEMA")
    item = next((row for row in movement.get("games", [])
                 if str(row.get("match_id")) == str(game.get("match_id"))), None)
    if not item:
        return ""
    if item.get("current_capture_utc") != captured:
        raise ValueError("MOVEMENT_FROM_DIFFERENT_007_CAPTURE")
    notes = []
    for change in item.get("changes", []):
        key = change.get("market")
        name = dict(MARKETS).get(key)
        kind = change.get("kind")
        before, after = change.get("before"), change.get("after")
        if kind == "JC_HANDICAP_CHANGED" and type(before) is int and type(after) is int:
            notes.append(f"主队让球 {before:+d} → {after:+d}")
        elif kind == "MODEL_DIRECTION_REVERSED" and name and before and after:
            notes.append(f"{name} {before} → {after}")
        elif kind == "MODEL_PROBABILITY_MOVEMENT_PP" and name:
            market = (game.get("markets") or {}).get(key) or {}
            direction = market.get("direction")
            probability = market.get("direction_probability")
            delta = (change.get("percentage_point_change") or {}).get(direction)
            if probability is not None and delta is not None and abs(delta) >= 5:
                notes.append(f"{name} {direction} {percent(probability - delta / 100)} → {percent(probability)}")
    return "<div>较上次　" + esc(" · ".join(notes)) + "</div>" if notes else ""


def render_push(forecast, comparison=None, movement=None, *, include_notes=True):
    date = esc(forecast.get("beijing_date"))
    cards = []
    for game in forecast.get("games", []):
        title = f"{esc(game.get('jc_number'))}｜{esc(game.get('home_team'))}（主） vs {esc(game.get('away_team'))}（客）"
        kickoff = esc(beijing_clock(game.get("kickoff_beijing")))
        markets = game.get("markets") or {}
        if game.get("status") == "INSUFFICIENT_FORM":
            lines = "<div>007 赛前战绩不足，三个玩法均未生成判断。</div>"
        else:
            lines = "".join(f"<div>{push_market_line(key, name, markets.get(key) or {})}</div>"
                            for key, name in MARKETS)
        notes = change_notes(comparison, str(game.get("match_id")))
        archived_form = (game.get("data_quality") or {}).get("archived_form_007")
        if archived_form:
            observed = esc(beijing_clock(archived_form["observed_at_utc"]))
            notes += f"<div>近况和交锋沿用北京时间 {observed} 的 007 赛前资料。</div>"
        if include_notes:
            notes += push_movement_note(movement, game, forecast.get("captured_at_utc"))
        cards.append(f"<section style='margin:8px 0;padding:8px 0;border-top:1px solid #ddd'>"
                     f"<b>{title}</b><div>北京时间 {kickoff}</div>{lines}{notes}</section>")
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<body style='font:14px/1.5 -apple-system,Arial;padding:8px'>"
            f"<h3>北京时间 {date} 足球研判</h3>{''.join(cards)}</body></html>")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--forecast", required=True)
    p.add_argument("--comparison")
    p.add_argument("--movement")
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
    movement=json.loads(Path(a.movement).read_text(encoding="utf-8")) if a.movement else None
    dest.write_text(render(data,comparison,a.mode,movement), encoding="utf-8")
    print("FOOTBALL_JC_MOBILE_REPORT", len(data.get("games", [])))


if __name__ == "__main__":
    main()
