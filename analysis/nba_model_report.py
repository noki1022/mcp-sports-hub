#!/usr/bin/env python3
"""Render a mobile NBA model analysis report from joined data and predictions."""
from __future__ import annotations
import argparse, html, json
from pathlib import Path

def render(joined, gate, out_json, out_html, injury_context=None):
    injuries={str(x.get("game_id")):x for x in (injury_context or {}).get("games",[])}
    games = {str(g.get("game_id")): g for g in joined.get("nba_cba_games", [])}
    preds = {str(g.get("game_id")): g for g in gate.get("game_predictions", [])}
    gate_rows = {}
    for row in gate.get("predictions", []):
        gate_rows.setdefault(str(row.get("game_id")), []).append(row)
    rows = []
    sections = []
    for gid, game in games.items():
        p = preds.get(gid, {})
        quality = p.get("data_quality", {})
        intervals = p.get("prediction_intervals", {})
        empirical = p.get("empirical_prediction_intervals", {})
        markets = {m.get("market"): m for m in p.get("markets", [])}
        decision = gate_rows.get(gid, [])
        reasons = sorted({reason for r in decision for reason in r.get("model_reasons", [])})
        record = {
            "game_id": gid, "display_date": game.get("display_date"),
            "display_clock": game.get("display_clock"),
            "home_team": game.get("home_team"), "away_team": game.get("away_team"),
            "model_status": p.get("status", "DISABLED"),
            "model_probability": {"home": p.get("moneyline_home_probability"), "away": p.get("moneyline_away_probability")},
            "model_probability_raw": {"home": p.get("moneyline_home_probability_raw")},
            "margin_sigma": p.get("margin_sigma"),
            "model_version": p.get("model_version"),
            "margin_mean_home_minus_away": p.get("margin_mean_home_minus_away"),
            "total_mean": p.get("total_mean"),
            "prediction_intervals": intervals,
            "data_quality": quality,
            "markets": markets,
            "gate_reasons": reasons or ["INDEPENDENT_MODEL_MISSING"],
            "pregame_context": p.get("pregame_context"),
            "injury_context": injuries.get(gid,{"quality":"NOT_PROVIDED","player_adjustment":"DISABLED_NOT_BACKTESTED"}),
            "recommendation": "NO_BET",
        }
        rows.append(record)
        margin = record["margin_mean_home_minus_away"]
        total = record["total_mean"]
        home_prob = p.get("moneyline_home_probability")
        away_prob = p.get("moneyline_away_probability")
        raw_home_prob = p.get("moneyline_home_probability_raw")
        mi = intervals.get("margin_home_minus_away", {})
        ti = intervals.get("total", {})
        emi = empirical.get("margin_home_minus_away", {})
        eti = empirical.get("total", {})
        spread = markets.get("full_spread", {}).get("settlement", {})
        total_settle = markets.get("full_total", {}).get("settlement", {})
        def fmt(x):
            return "—" if x is None else f"{float(x):.1f}"
        quality_text = quality.get("quality", "NO_MODEL_DATA")
        sections.append(
            "<section><h2>" + html.escape(str(game.get("display_clock", "—"))) + " "
            + html.escape(str(game.get("home_team", "—"))) + " vs "
            + html.escape(str(game.get("away_team", "—"))) + "</h2>"
            + "<p>独赢模型概率：主胜 <b>" + fmt(home_prob * 100 if home_prob is not None else None) + "%</b>；客胜 <b>" + fmt(away_prob * 100 if away_prob is not None else None) + "%</b>"
            + "；校准前主胜 " + fmt(raw_home_prob * 100 if raw_home_prob is not None else None) + "%</p>"
            + "<p>模型分差（主−客）：<b>" + fmt(margin) + "</b>；正态80%区间 "
            + "[" + fmt((mi.get("80") or {}).get("low")) + ", " + fmt((mi.get("80") or {}).get("high")) + "]；经验80%区间 "
            + "[" + fmt((emi.get("80") or {}).get("low")) + ", " + fmt((emi.get("80") or {}).get("high")) + "]</p>"
            + "<p>模型总分：<b>" + fmt(total) + "</b>；正态80%区间 "
            + "[" + fmt((ti.get("80") or {}).get("low")) + ", " + fmt((ti.get("80") or {}).get("high")) + "]；经验80%区间 "
            + "[" + fmt((eti.get("80") or {}).get("low")) + ", " + fmt((eti.get("80") or {}).get("high")) + "]</p>"
            + "<p>样本质量：" + html.escape(str(quality_text))
            + "；近五场 " + str(quality.get("home_recent_games", "—")) + "/"
            + str(quality.get("away_recent_games", "—")) + "；交锋 "
            + str(quality.get("h2h_games", "—")) + " 场</p>"
            + "<p>让分结算概率：全赢 " + fmt(spread.get("full_win")) + "，半赢 "
            + fmt(spread.get("half_win")) + "，走盘 " + fmt(spread.get("push"))
            + "，半输 " + fmt(spread.get("half_loss")) + "，全输 " + fmt(spread.get("full_loss")) + "</p>"
            + "<p>大小分结算概率：全赢 " + fmt(total_settle.get("full_win")) + "，半赢 "
            + fmt(total_settle.get("half_win")) + "，走盘 " + fmt(total_settle.get("push"))
            + "，半输 " + fmt(total_settle.get("half_loss")) + "，全输 " + fmt(total_settle.get("full_loss")) + "</p>"
            + "<p>背靠背/交锋扩展：仅供研究，未通过回测，不改变本次胜率。伤停质量：" + html.escape(str(record["injury_context"].get("quality"))) + "；球员影响尚未定量校准。</p>"
            + "<p class='gate'>闸门：" + html.escape(", ".join(reasons or ["NO_BET"]))
            + "；结论：<b>NO_BET</b></p></section>"
        )
    report = {"target_display_date": joined.get("requested_display_date"),
              "generated_at_utc": gate.get("generated_at_utc"),
              "games": rows, "decision": "NO_BET"}
    Path(out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    doc = ("<!doctype html><html lang='zh'><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           "<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f2f4f7;color:#17202a;padding:10px}"
           "section{background:#fff;border-radius:14px;padding:14px;margin:10px 0;box-shadow:0 1px 4px #ccd}"
           "h1{font-size:22px}h2{font-size:18px;margin:0 0 8px}p{font-size:14px;line-height:1.5;margin:7px 0}.gate{color:#a33}</style>"
           "<h1>NBA 独立模型分析</h1><p>目标日期：" + html.escape(str(joined.get("requested_display_date", "—")))
           + "；模型输出仅供统计分析，当前统一 NO_BET。</p>" + "".join(sections) + "</html>")
    Path(out_html).write_text(doc, encoding="utf-8")
    print("NBA_MODEL_REPORT", len(rows), "games")

def self_test():
    joined = {"requested_display_date": "2026-10-30", "nba_cba_games": [{
        "game_id": "1", "display_clock": "07:00", "home_team": "主队", "away_team": "客队"}]}
    gate = {"game_predictions": [], "predictions": []}
    render(joined, gate, "/tmp/model.json", "/tmp/model.html")
    assert "NO_BET" in Path("/tmp/model.html").read_text()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--joined"); ap.add_argument("--predictions"); ap.add_argument("--injury-context")
    ap.add_argument("--out-json", default="nba_model_analysis.json")
    ap.add_argument("--out-html", default="nba_model_analysis.html")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test(); print("NBA_MODEL_REPORT_SELF_TEST_PASS")
    else:
        if not a.joined or not a.predictions: raise SystemExit("--joined and --predictions are required")
        render(json.loads(Path(a.joined).read_text(encoding="utf-8")),
               json.loads(Path(a.predictions).read_text(encoding="utf-8")),
               a.out_json, a.out_html, json.loads(Path(a.injury_context).read_text(encoding="utf-8")) if a.injury_context and Path(a.injury_context).exists() else None)
