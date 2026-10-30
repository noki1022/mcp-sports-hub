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

def html_report(d):
    out=["<div style='max-width:540px;margin:auto;font-family:-apple-system,Arial,sans-serif;"
         "font-size:13px;line-height:1.55;color:#1f344b'><h2>NBA 五玩法赛后复盘 · "+
         e(d["beijing_date"])+"</h2>",
         "<p>仅对赛前锁定的判断计数；未开售、缺数据、赛后盘口和未完赛不算输。"
         "主队在左、客队在右。</p>"]
    out.append("<h3>五玩法独立命中率</h3>")
    for k in MARKETS:
        v=d["summary"][k]
        pct= f"{v['hit_rate']*100:.1f}%" if v["hit_rate"] is not None else "暂无有效样本"
        out.append("<div style='padding:5px 2px;border-bottom:1px solid #dfe6ef'>"+
          e(LABELS[k])+"　<b>"+e(pct)+"</b>　命中"+str(v["hits"])+"/"+
          str(v["graded"])+"　走盘"+str(v["pushes"])+
          "　未入样"+str(v["excluded"]+v["unsettled"])+"</div>")
    out.append("<h3>逐场结果（按竞彩编号）</h3>")
    rows=sorted(d.get("games",[]),key=lambda r:r.get("jingcai_number") or "周末999")
    for g in rows:
        label=g.get("jingcai_number") or "竞彩编号待核"
        hp,ap=g.get("home_points"),g.get("away_points")
        score=f"{hp}:{ap}" if hp is not None and ap is not None else "待确认"
        out.append("<div style='padding:10px;margin:8px 0;border:1px solid #dbe4f0;border-radius:8px'>"
          "<b>"+e(label)+"　主队："+e(str(g.get("home_team")))+"　｜　客队："+e(str(g.get("away_team")))+
          "</b><div>最终比分（主:客）："+e(score)+"</div>")
        for k in MARKETS:
            m=(g.get("markets") or {}).get(k) or {}
            out.append("<div>"+e(LABELS[k])+"　"+e(SIDE.get(m.get("direction"),"无有效方向"))+
                       "　"+e(format_line(m,k))+"　<b>"+e(OUTCOME.get(m.get("outcome"),"待核"))+"</b></div>")
        out.append("</div>")
    out.append("<p style='font-size:11px;color:#63758b'>"
       "命中率=命中÷(命中+未中)，走盘另记。研究表现不代表真实投注ROI。</p></div>")
    return "".join(out)

def self_test():
    s={"beijing_date":"2026-10-31",
       "summary":{k:{"hits":1,"misses":0,"pushes":0,"excluded":0,"unsettled":0,"graded":1,"hit_rate":1} for k in MARKETS},
       "games":[{"jingcai_number":"周五314","home_team":"主","away_team":"客",
          "home_points":108,"away_points":113,"markets":{
            k:{"direction":"AWAY_WIN" if k=="JINGCAI_WIN" else "HOME_COVER",
               "signed_home_handicap":7.5,"outcome":"HIT"} for k in MARKETS}}]}
    output=html_report(s)
    assert output.count("命中率")==2 and "周五314" in output
    assert "主队：主" in output and "客队：客" in output
    assert all(LABELS[k] in output for k in MARKETS)
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
