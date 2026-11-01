#!/usr/bin/env python3
"""Compact five-market iPhone delivery. Source is frozen, timestamped evidence.

Never invent missing Crown quotes or calibrated Crown probabilities.
A user-confirmed lottery label is shown with its provenance, never promoted
to automated-source verification. Source JSON and research remain unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
import math
from pathlib import Path
import re


MARKETS = (
    ("JINGCAI_WIN", "胜负"),
    ("JINGCAI_HANDICAP", "让分"),
    ("JINGCAI_TOTAL", "大小"),
    ("CROWN_HANDICAP", "让分"),
    ("CROWN_TOTAL", "大小"),
)
# Scope the correction strictly to this fixture, not to another season/date.
MANUAL_NUMBER = {
    ("2026-11-01", "728884", "休斯顿火箭", "俄克拉荷马城雷霆"): "周六316"
}


def esc(value):
    return escape("—" if value is None else str(value), quote=True)


def number(value):
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        value = float(value)
        return value if math.isfinite(value) and abs(value) < 100000 else None
    except (TypeError, ValueError):
        return None


def fmt(value, signed=False):
    value = number(value)
    if value is None:
        return "—"
    return f"{value:+.1f}" if signed else f"{value:.1f}"


def percent(value):
    n = number(value)
    return f"{100*n:.1f}%" if n is not None and 0 <= n <= 1 else "—"


def match_label(game, target):
    forecast = game.get("five_market_forecast") or {}
    value = forecast.get("jingcai_number")
    if (forecast.get("jingcai_number_status") == "VERIFIED"
            and isinstance(value, str)
            and re.fullmatch(r"周[一二三四五六日天]\d{3}", value)):
        return value, ""
    # Existing identity pipeline is optional for fallback, but must be VERIFIED.
    value = game.get("jc_match_label")
    if (game.get("jc_match_identity_status") == "VERIFIED_JC_NUMBER"
            and isinstance(value, str)
            and re.fullmatch(r"周[一二三四五六日天]\d{3}", value)):
        return value, ""
    key = (str(target), str(game.get("game_id")),
           game.get("home_team"), game.get("away_team"))
    if key in MANUAL_NUMBER:
        return MANUAL_NUMBER[key], "用户确认"
    return "编号待核", ""


def report_time(game):
    t = (game.get("five_market_forecast") or {}).get("tipoff_beijing") or game.get("start_time_beijing")
    try:
        from zoneinfo import ZoneInfo
        d=datetime.fromisoformat(str(t).replace("Z","+00:00"))
        if d.tzinfo is None:return "时间待核"
        return d.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
    except (TypeError, ValueError):
        return "时间待核"


def market_row(key, obj):
    obj = obj or {}
    if obj.get("status") == "NOT_ON_SALE_USER_CONFIRMED":
        return "未开售"
    if obj.get("status") != "DIRECTION_ISSUED":
        return "盘口未核实" if key.startswith("CROWN_") else "方向待核"
    direction = obj.get("direction")
    if key == "JINGCAI_WIN":
        label = {"HOME_WIN": "主胜", "AWAY_WIN": "客胜"}.get(direction)
    elif key.endswith("HANDICAP"):
        signed_home = number(obj.get("signed_home_handicap"))
        if signed_home is None:
            return "让分正负号待核"
        if direction == "HOME_COVER":
            label = "主" + fmt(signed_home, signed=True) + " 赢盘"
        elif direction == "AWAY_COVER":
            label = "客" + fmt(-signed_home, signed=True) + " 赢盘"
        else:
            label = None
    else:
        line = number(obj.get("line"))
        label = (("大" if direction == "OVER" else "小") + fmt(line)
                 if direction in ("OVER", "UNDER") and line is not None else None)
    if not label:
        return "方向待核"
    # Keep the final push outcome-only. Multi-book consensus, same-line
    # counts, market-implied probabilities and model-market gaps remain in
    # the frozen source JSON for research, but are intentionally not rendered.
    label += " · " + percent(obj.get("model_direction_probability"))
    if key.startswith("CROWN_"):
        label += "（参考）"
    if obj.get("quote_freshness") == "ARCHIVED_PRIOR_NOT_LIVE":
        label += " · 历史盘口口"
    return label


def small_move(game):
    """Only verified same-market JC initial->current changes; never use raw Crown as JC."""
    observed = ((game.get("jc_007_price_shadow") or {}).get("markets") or {})
    parts = []
    for k, title in (("handicap", "竞彩让分"), ("total", "竞彩总分")):
        r = observed.get(k) or {}
        if r.get("status") != "OBSERVED":
            continue
        data = r.get("data") or {}
        opening = number((data.get("opening") or {}).get("line"))
        current = number((data.get("current") or {}).get("line"))
        if opening is None or current is None or opening == current:
            continue
        parts.append(title + " " + fmt(opening, signed=(k == "handicap")) + "→"
                     + fmt(current, signed=(k == "handicap")))
    return "　".join(parts[:2])


def render_compact(games, model_map, title, target, mode, snapshot_utc=None, official_fixtures=None):
    """A single view; one card per game, Jingcai 70% visual priority, Crown 30%.

    model_map is preserved for the scheduled runner API; the five-market
    forecast is the canonical frozen decision and probability source.
    """
    rows = sorted(
        games, key=lambda g: (
            0 if match_label(g, target)[0] != "编号待核" else 1,
            int(match_label(g, target)[0][-3:])
            if match_label(g, target)[0] != "编号待核" else 999,
            report_time(g), str(g.get("game_id"))
        )
    )
    synthetic = "模拟" in str(title)
    css = ("font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;"
           "font-size:14px;line-height:1.5;color:#233348;max-width:540px;margin:0 auto;")
    date_label = str(target)
    stamp = ""
    if snapshot_utc:
        try:
            from zoneinfo import ZoneInfo
            t = datetime.fromisoformat(str(snapshot_utc).replace("Z", "+00:00"))
            stamp = " · " + t.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M") + "快照"
        except (TypeError, ValueError):
            pass
    head = (
        "<div style='background:#edf3fa;border-radius:9px;padding:11px 12px;'>"
        "<div style='font-weight:750;font-size:18px;'>NBA赛前五玩法 · " + esc(date_label) + "</div>"
        "<div style='font-size:12px;color:#5f7085;'>北京时间 · " + str(len(rows)) +
        "场 · 竞彩优先" + esc(stamp) + (" · 模拟" if synthetic else "") + "</div></div>"
    )
    # First capture already carries verified official UTC fixture tipoffs.
    # Show earliest tip on every push so users need not spot an early game manually.
    tips=[]
    # Complete official fixture set includes early NBA games without 007 prices.
    if official_fixtures is not None:
        if not official_fixtures:raise RuntimeError("EMPTY_OFFICIAL_SCHEDULE_CANNOT_ANNOUNCE")
        fixture_times=[x.get("utc_tip") for x in official_fixtures]
    else:
        fixture_times=[(g.get("five_market_forecast") or {}).get("tipoff_beijing") or
                       g.get("start_time_beijing") for g in rows]
    for raw in fixture_times:
        try:
            d=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
            if d.tzinfo is None:raise ValueError("NO_TIMEZONE")
            tips.append(d)
        except (ValueError,TypeError):
            raise RuntimeError("NBA_EARLIEST_TIP_UNVERIFIED")
    from zoneinfo import ZoneInfo
    earliest=min(tips).astimezone(ZoneInfo("Asia/Shanghai"))
    if earliest.date().isoformat()!=str(target):raise RuntimeError("OFFICIAL_EARLIEST_GAME_WRONG_DAY")
    head+=("<div style='font-size:12px;padding:5px 10px;color:#8a4e16;'>"
           "最早开赛：北京时间 "+earliest.strftime("%H:%M")+
           " · 完整赛前判断必须早于此时冻结</div>")
    output = ["<div style='" + css + "'>" + head]
    for game in rows:
        fcast = game.get("five_market_forecast") or {}
        if report_time(game)=="时间待核":raise RuntimeError("NBA_BEIJING_TIPOFF_NOT_VERIFIED")
        mk = fcast.get("markets") or {}
        label, provenance = match_label(game, target)
        home = esc(game.get("home_team"))
        away = esc(game.get("away_team"))
        info = "<span style='color:#a66a20;font-size:11px;'>（" + esc(provenance) + "）</span>" if provenance else ""
        body = (
            "<div style='margin:10px 0;border:1px solid #e2e9f1;border-radius:10px;"
            "padding:10px 11px;background:white;'>"
            "<div style='font-size:12px;color:#687b92;font-weight:650;'>" + esc(label) + info
            + "　北京时间 " + esc(report_time(game)) + " 开赛</div>"
            "<div style='font-size:15px;line-height:1.4;font-weight:750;margin:3px 0 7px;'>"
            + home + " <span style='font-size:11px;color:#7b8998;font-weight:400;'>主</span>　"
            + away + " <span style='font-size:11px;color:#7b8998;font-weight:400;'>客</span></div>"
            "<div style='border-radius:7px;background:#edf4fc;padding:7px 9px;'>"
            "<div style='font-size:11px;color:#527399;font-weight:700;margin-bottom:2px;'>竞彩 · 3玩法</div>"
        )
        for key, name in MARKETS[:3]:
            body += ("<div style='padding:3px 0;font-size:13px;'><span style='color:#536a82;'>"
                     + esc(name) + "　</span><b>" + esc(market_row(key, mk.get(key))) + "</b></div>")
        body += ("</div><div style='border-radius:7px;background:#f6f7fa;padding:6px 9px;margin-top:6px;'>"
                 "<div style='font-size:11px;color:#718094;font-weight:650;'>皇冠ID3 · 2玩法</div>")
        for key, name in MARKETS[3:]:
            body += ("<div style='padding:2px 0;font-size:12px;'><span style='color:#68788b;'>"
                     + esc(name) + "　</span>" + esc(market_row(key, mk.get(key))) + "</div>")
        if game.get("quote_freshness") == "ARCHIVED_PRIOR_NOT_LIVE":
            snapshot = game.get("quote_captured_at_utc")
            try:
                from zoneinfo import ZoneInfo
                checked = datetime.fromisoformat(str(snapshot).replace("Z", "+00:00"))
                if checked.tzinfo is None:raise ValueError("NO_TIMESTAMP_ZONE")
                stamp = checked.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")
            except (TypeError, ValueError):
                raise RuntimeError("ARCHIVED_QUOTE_TIMESTAMP_NOT_VERIFIED")
            body += ("<div style='color:#a36516;font-size:11px;margin-top:4px;'>"
                     "007盘口含历史快照（" + esc(stamp) +
                     "），非即时盘；不得当成最新赔率</div>")
        injury = game.get("injury_review") or {}
        gate = game.get("final_signal_status", "PROVISIONAL_INJURY_UNVERIFIED")
        if gate == "FINAL_INJURY_VERIFIED":
            injury_label = "已核，已纳入模型"
        elif gate == "PROVISIONAL_INJURY_UNADJUSTED":
            injury_label = "已核，尚未纳入模型（临时）"
        else:
            injury_label = "待核（临时判断）"
        body += "<div style='font-size:11px;color:#945b23;margin-top:5px;'>伤停：" + esc(injury_label) + "</div>"
        body += "</div>"
        p = number((mk.get("JINGCAI_WIN") or {}).get("model_direction_probability"))
        if p is not None and p >= 0.85:
            body += ("<div style='font-size:11px;color:#97531b;margin-top:4px;'>"
                     "高置信度输出需复核校准与伤停</div>")
        body += "</div>"
        output.append(body)
    output.append(
        "<div style='font-size:11px;color:#6d7c8d;padding:7px 2px 12px;'>"
        "让分均按主客队标注正负号；皇冠未校准概率会单独注明。"
        "</div></div>"
    )
    return "".join(output)


def cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--five", required=False)
    ap.add_argument("--preview", default="nba_five_compact_preview.html")
    ap.add_argument("--status", default="nba_five_compact_status.json")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.five:
        ap.error("--five is required")
    obj = json.loads(Path(args.five).read_text(encoding="utf-8"))
    games = obj.get("games") or []
    if not games or len(games) != obj.get("game_count"):
        raise RuntimeError("INCOMPLETE_FROZEN_FIVE_MARKET_BOARD")
    if len({str(x.get("game_id")) for x in games}) != len(games):
        raise RuntimeError("DUPLICATE_FIXTURE_ID")
    for g in games:
        if set((g.get("markets") or {})) != {key for key, _ in MARKETS}:
            raise RuntimeError("FIVE_MARKET_KEYS_MISSING")
    target = obj.get("target_date")
    rows = [{**g, "five_market_forecast": g} for g in games]
    title = "NBA 赛前五玩法 · 精简重发｜" + str(target)
    html = render_compact(rows, {}, title, target, "three", obj.get("board_capture_utc"))
    Path(args.preview).write_text(html, encoding="utf-8")
    state = {"target_date": target, "games_considered": len(games),
             "source_capture_utc": obj.get("board_capture_utc"), "template": "compact-v3"}
    if args.send:
        import os
        from pushplus_mobile import send
        state.update(send({"title": title, "html": html}, os.environ.get("PUSHPLUS_TOKEN")))
    else:
        state["state"] = "DRY_RUN_NOT_SENT"
    Path(args.status).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("COMPACT_V3_REPORT", state["state"], len(games))


def self_test():
    def mk(direction, **kwargs):
        return {"status": "DIRECTION_ISSUED", "direction": direction, **kwargs}
    fcast = {"jingcai_number": None, "jingcai_number_status": "UNVERIFIED_JC_LABEL",
             "markets": {
                 "JINGCAI_WIN": mk("HOME_WIN", model_direction_probability=0.555),
                 "JINGCAI_HANDICAP": mk("AWAY_COVER", signed_home_handicap=-4.5,
                                        model_direction_probability=0.562),
                 "JINGCAI_TOTAL": mk("OVER", line=221.5, model_direction_probability=0.633),
                 "CROWN_HANDICAP": mk("HOME_COVER", signed_home_handicap=-5.5,
                     model_direction_probability=.61,
                     market_consensus={"market_price_consensus_status":"AVAILABLE_SAME_LINE_MEDIAN",
                         "market_price_probability_for_model_direction":.56,
                         "same_line_company_count":5,"consensus_line":5.5,
                         "direct_line_matches_price_reference":True,
                         "model_minus_market_probability_for_model_direction":.05}),
                 "CROWN_TOTAL": mk("OVER", line=230.5, model_direction_probability=.61,
                     market_consensus={"market_price_consensus_status":"INSUFFICIENT_SAME_LINE_COMPANIES",
                         "same_line_company_count":2}),
             }}
    game = {"game_id": "728884", "home_team": "休斯顿火箭",
            "away_team": "俄克拉荷马城雷霆", "display_clock": "08:30",
            "five_market_forecast": fcast}
    assert match_label(game, "2026-11-01") == ("周六316", "用户确认")
    assert match_label(game, "2026-11-02")[0] == "编号待核"
    game["five_market_forecast"]["tipoff_beijing"]="2026-11-01T08:30:00+08:00"
    h = render_compact([game], {}, "赛前", "2026-11-01", "three")
    for v in ("北京时间 08:30 开赛", "周六316", "用户确认", "客+4.5 赢盘", "大221.5", "55.5%"):
        assert v in h, v
    for hidden in ("同线市场", "模型-市场", "多机构共识", "共识总分线", "共识主队盘口", "5家"):
        assert hidden not in h, hidden
    for bad in ("七步分析", "007多机构横向比较", "本小时动态研判", "模型 vs 盘口"):
        assert bad not in h, bad
    past={**game, "quote_freshness":"ARCHIVED_PRIOR_NOT_LIVE",
          "quote_captured_at_utc":"2026-10-31T13:30:00Z"}
    ph=render_compact([past], {}, "赛前", "2026-11-01", "three")
    assert "历史快照" in ph and "非即时盘" in ph and "10-31 21:30" in ph
    assert "皇冠ID3" in h and "竞彩 · 3玩法" in h
    injected = {**game, "home_team": "<script>alert(1)</script>"}
    h = render_compact([injected], {}, "赛前", "2026-11-01", "three")
    assert "<script>" not in h and "&lt;script&gt;" in h
    assert match_label(injected, "2026-11-01")[0] == "编号待核"
    early=[{"utc_tip":"2026-10-31T19:00:00+00:00"}]
    h=render_compact([game],{},"赛前","2026-11-01","three",official_fixtures=early)
    assert "最早开赛：北京时间 03:00" in h and "北京时间 08:30 开赛" in h
    sample = mk("AWAY_COVER", signed_home_handicap=6.5, model_direction_probability=.549)
    assert market_row("JINGCAI_HANDICAP", sample).startswith("客-6.5 赢盘")
    assert market_row("CROWN_HANDICAP", {"status": "CROWN_QUOTE_NOT_VERIFIED"}) == "盘口未核实"
    assert "61.0%（参考）" in market_row("CROWN_TOTAL",mk("OVER",line=230.5,model_direction_probability=.61))
    crown = market_row("CROWN_HANDICAP",fcast["markets"]["CROWN_HANDICAP"])
    assert crown.endswith("61.0%（参考）")
    assert "同线市场" not in crown and "模型-市场" not in crown
    assert "61.0%（参考）" in market_row("CROWN_TOTAL",fcast["markets"]["CROWN_TOTAL"])
    print("COMPACT_FIVE_MARKET_IPHONE_SELF_TEST_PASS")


if __name__ == "__main__":
    cli()
