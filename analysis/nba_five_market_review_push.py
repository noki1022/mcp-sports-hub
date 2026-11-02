#!/usr/bin/env python3
"""Compact PushPlus iPhone retrospective of all five separately scored markets."""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
from html import escape as e
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from pushplus_mobile import send
from nba_five_markets import MARKETS,LABELS

SIDE={"HOME_WIN":"主胜","AWAY_WIN":"客胜","HOME_COVER":"主队赢盘",
      "AWAY_COVER":"客队赢盘","OVER":"大分","UNDER":"小分"}
OUTCOME={"HIT":"命中","MISS":"未中","PUSH":"走盘",
         "EXCLUDED_NOT_ON_SALE":"未开售","EXCLUDED_NO_DIRECTION":"缺数据/无有效判断",
         "EXCLUDED_INVALID_PRETIP_LOCK":"赛前锁定失效","UNSETTLED":"未结算"}
def format_line(q,k):
    if k.endswith("HANDICAP"):
        s=q.get("signed_home_handicap")
        return ("主队"+f"{float(s):+g}" if isinstance(s,(int,float)) else "盘口待核")
    v=q.get("line")
    return "总分"+str(v) if k.endswith("TOTAL") and isinstance(v,(int,float)) else ""

def missed_actual(g, market):
    """Every miss carries the official home:away score and the exact factual result."""
    if market.get("outcome") != "MISS":
        return ""
    hp, ap = g.get("home_points"), g.get("away_points")
    valid_score = (
        isinstance(hp, int) and not isinstance(hp, bool) and hp >= 0 and
        isinstance(ap, int) and not isinstance(ap, bool) and ap >= 0
    )
    if not valid_score:
        return " · 实际赛果待核（官方比分缺失）"

    score = f"实际比分{hp}:{ap}"
    direction = market.get("direction")
    if direction in ("OVER", "UNDER"):
        total = hp + ap
        line = market.get("line")
        if not isinstance(line, (int, float)) or isinstance(line, bool):
            return f" · {score}（实际总分{total}；大小盘线待核）"
        actual_side = "大分" if total > line else "小分" if total < line else "走盘"
        return f" · {score}（实际总分{total}，{actual_side}）"
    if direction in ("HOME_WIN", "AWAY_WIN"):
        winner = "主队胜" if hp > ap else "客队胜" if ap > hp else "平局"
        return f" · {score}（实际结果：{winner}）"
    if direction in ("HOME_COVER", "AWAY_COVER"):
        signed = market.get("signed_home_handicap")
        if not isinstance(signed, (int, float)) or isinstance(signed, bool):
            return f" · {score}（主队净胜{hp-ap:+d}分；盘口待核）"
        cover_margin = hp - ap + signed
        actual_cover = "主队赢盘" if cover_margin > 0 else "客队赢盘" if cover_margin < 0 else "走盘"
        return f" · {score}（主队净胜{hp-ap:+d}分；{actual_cover}）"
    return f" · {score}"

def market_exceptions(d, key):
    """Only display nonzero exceptions; summarize directly from frozen
    settlement rows so never silently call a missing result a push."""
    v = d["summary"][key]
    push = int(v.get("pushes") or 0)
    excluded = int(v.get("excluded") or 0)
    unsettled = int(v.get("unsettled") or 0)
    if min(push, excluded, unsettled) < 0:
        raise ValueError("NEGATIVE_FIVE_MARKET_SETTLEMENT_COUNT")
    extra = []
    if push:
        extra.append(f"走盘{push}")
    omitted = excluded + unsettled
    if omitted:
        reasons = [
            ("EXCLUDED_NOT_ON_SALE", "未开售"),
            ("EXCLUDED_NO_DIRECTION", "赛前判断缺失"),
            ("EXCLUDED_INVALID_PRETIP_LOCK", "赛前锁定失效"),
            ("UNSETTLED", "官方赛果待确认"),
        ]
        counts = {name: sum(
            (g.get("markets") or {}).get(key, {}).get("outcome") == name
            for g in d.get("games", [])
        ) for name, _ in reasons}
        details = [f"{label}{counts[name]}" for name, label in reasons if counts[name]]
        remainder = omitted - sum(counts.values())
        if remainder < 0:
            raise ValueError("REVIEW_EXCLUDED_COUNTS_DO_NOT_MATCH_GAME_ROWS")
        if remainder:
            details.append(f"其他未入样{remainder}")
        extra.append(f"未入样{omitted}（{'、'.join(details)}）")
    return "　" + "　".join(extra) if extra else ""


def html_report(d):
    out = [
        "<div style='max-width:540px;margin:auto;font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;"
        "font-size:14px;line-height:1.5;color:#20354d'>",
        "<h2 style='margin:0 0 8px'>NBA 五玩法复盘｜" + e(d["beijing_date"]) + "</h2>",
        "<p style='margin:0 0 14px;color:#64748b;font-size:12px'>"
        "仅统计赛前锁定、有效结算的判断；主队在左，客队在右。</p>",
        "<h3 style='margin:12px 0 6px'>五玩法命中率</h3>"
    ]
    for k in MARKETS:
        v = d["summary"][k]
        pct = f"{v['hit_rate']*100:.1f}%" if v["hit_rate"] is not None else "暂无有效样本"
        count = f"（{v['hits']}/{v['graded']}）" if v["graded"] else ""
        out.append(
            "<div style='padding:6px 2px;border-bottom:1px solid #dfe6ef'>"
            f"<b>{e(LABELS[k])}</b>　<b>{e(pct)}</b>{e(count)}"
            f"{e(market_exceptions(d, k))}</div>"
        )

    out.append("<h3 style='margin:16px 0 8px'>逐场结果</h3>")
    rows = sorted(d.get("games", []), key=lambda r: r.get("jingcai_number") or "周末999")
    for g in rows:
        label = g.get("jingcai_number") or "竞彩编号待核"
        hp, ap = g.get("home_points"), g.get("away_points")
        valid_score = (
            isinstance(hp, int) and not isinstance(hp, bool) and hp >= 0 and
            isinstance(ap, int) and not isinstance(ap, bool) and ap >= 0
        )
        score = f"{hp}:{ap}" if valid_score else "官方比分待确认"
        out.append(
            "<div style='padding:10px;margin:8px 0;border:1px solid #dbe4f0;border-radius:9px'>"
            f"<b>{e(str(label))}　主：{e(str(g.get('home_team') or '待核'))}　｜　"
            f"客：{e(str(g.get('away_team') or '待核'))}</b>"
            f"<div style='font-size:17px;font-weight:700;margin:3px 0 6px'>最终比分（主:客）：{e(score)}</div>"
        )
        for k in MARKETS:
            m = (g.get("markets") or {}).get(k) or {}
            outcome = m.get("outcome")
            outcome_label = OUTCOME.get(outcome, "待核")
            color = "#16834a" if outcome == "HIT" else "#c0392b" if outcome == "MISS" else "#64748b"
            actual = missed_actual(g, m)
            out.append(
                "<div style='padding:4px 0;border-top:1px solid #edf1f6'>"
                f"<b>{e(LABELS[k])}</b>　{e(SIDE.get(m.get('direction'), '无有效方向'))}"
                f"　{e(format_line(m,k))}　"
                f"<b style='color:{color}'>{e(outcome_label)}</b>"
                f"<span style='color:#52657b'>{e(actual)}</span></div>"
            )
        out.append("</div>")
    out.append(
        "<p style='font-size:11px;color:#63758b;margin-top:12px'>"
        "命中率=命中÷(命中+未中)；走盘及未入样不计入命中率。"
        "仅在发生异常时显示数量与原因；所有未中项均附官方主:客比分及赛果。</p></div>"
    )
    return "".join(out)

def self_test():
    s={"beijing_date":"2026-10-31",
       "summary":{k:{"hits":1,"misses":0,"pushes":0,"excluded":0,"unsettled":0,"graded":1,"hit_rate":1} for k in MARKETS},
       "games":[{"jingcai_number":"周五314","home_team":"主","away_team":"客",
          "home_points":108,"away_points":113,"markets":{
            k:{"direction":"AWAY_WIN" if k=="JINGCAI_WIN" else "HOME_COVER",
               "signed_home_handicap":7.5,"outcome":"HIT"} for k in MARKETS}}]}
    output=html_report(s)
    assert "五玩法命中率" in output and "周五314" in output
    assert "主：主" in output and "客：客" in output
    assert all(LABELS[k] in output for k in MARKETS)
    assert "竞彩胜负" in output and "100.0%" in output and "（1/1）" in output
    assert "走盘0" not in output and "未入样0" not in output
    # All true exceptional cases must be counted without inflating accuracy.
    s["summary"]["JINGCAI_HANDICAP"].update(
        {"pushes":1,"excluded":2,"unsettled":1})
    s["games"][0]["markets"]["JINGCAI_HANDICAP"]["outcome"]="PUSH"
    s["games"].extend([
        {"jingcai_number":"周五315","markets":{"JINGCAI_HANDICAP":{
            "outcome":"EXCLUDED_NOT_ON_SALE"}}},
        {"jingcai_number":"周五316","markets":{"JINGCAI_HANDICAP":{
            "outcome":"EXCLUDED_NO_DIRECTION"}}},
        {"jingcai_number":"周五317","markets":{"JINGCAI_HANDICAP":{
            "outcome":"UNSETTLED"}}},
    ])
    exceptional = html_report(s)
    assert "走盘1" in exceptional and "未入样3" in exceptional
    assert "未开售1" in exceptional and "赛前判断缺失1" in exceptional
    assert "官方赛果待确认1" in exceptional
    assert "走盘0" not in exceptional and "未入样0" not in exceptional
    assert "竞彩胜负" in exceptional and "（1/1）" in exceptional
    assert market_exceptions({"summary":{"JINGCAI_WIN":{
        "pushes":0,"excluded":0,"unsettled":0}},"games":[]}, "JINGCAI_WIN") == ""
    s["summary"]["JINGCAI_TOTAL"].update({"excluded":1})
    s["games"][2]["markets"]["JINGCAI_TOTAL"] = {
        "outcome":"EXCLUDED_INVALID_PRETIP_LOCK"}
    assert "赛前锁定失效1" in html_report(s)
    assert missed_actual({"home_points":115,"away_points":115},{"outcome":"MISS","direction":"OVER","line":232})==" · 实际比分115:115（实际总分230，小分）"
    assert missed_actual({"home_points":115,"away_points":115},{"outcome":"HIT","direction":"UNDER"})==""
    assert "大小盘线待核" in missed_actual({"home_points":115,"away_points":115},{"outcome":"MISS","direction":"OVER"})
    assert "走盘" in missed_actual({"home_points":115,"away_points":115},{"outcome":"MISS","direction":"OVER","line":230})
    assert missed_actual({"home_points":108,"away_points":100},{"outcome":"MISS","direction":"AWAY_WIN"}).startswith(" · 实际比分108:100（实际结果：主队胜）")
    assert "实际比分103:100（主队净胜+3分；客队赢盘）" in missed_actual({"home_points":103,"away_points":100},{"outcome":"MISS","direction":"HOME_COVER","signed_home_handicap":-5.5})
    assert "实际比分90:112（主队净胜-22分；客队赢盘）" in missed_actual({"home_points":90,"away_points":112},{"outcome":"MISS","direction":"HOME_COVER","signed_home_handicap":8.5})
    assert missed_actual({"home_points":None,"away_points":100},{"outcome":"MISS","direction":"OVER"})==" · 实际赛果待核（官方比分缺失）"
    demo={"beijing_date":"2026-10-31","summary":{k:{"hits":0,"misses":1,"pushes":0,"excluded":0,"unsettled":0,"graded":1,"hit_rate":0} for k in MARKETS},
      "games":[{"jingcai_number":"周六308","home_team":"爵士","away_team":"开拓者","home_points":90,"away_points":112,
        "markets":{k:{"direction":"OVER","line":234.5,"outcome":"MISS"} for k in MARKETS}}]}
    preview=html_report(demo)
    assert preview.count("实际比分90:112") >= 5, "EVERY_MISS_MUST_SHOW_FULL_SCORE"
    assert "周六308" in preview and "最终比分（主:客）：90:112" in preview
    print("NBA_FIVE_MARKET_IPHONE_REVIEW_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--settlement");p.add_argument("--preview");p.add_argument("--status")
    p.add_argument("--send",action="store_true");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not all((a.settlement,a.preview,a.status)):raise SystemExit("MISSING_REVIEW_ARGS")
        obj=json.loads(Path(a.settlement).read_text(encoding="utf-8"))
        h=html_report(obj)
        Path(a.preview).write_text(h,encoding="utf-8")
        state={"date":obj["beijing_date"],"games":len(obj["games"]),"state":"DRY_RUN_NOT_SENT"}
        if a.send:
            state.update(send({"title":"NBA 竞彩+皇冠五玩法复盘｜"+obj["beijing_date"],"html":h},os.environ.get("PUSHPLUS_TOKEN","")))
        Path(a.status).write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_FIVE_MARKET_PUSHPLUS",state["state"],state["games"])
