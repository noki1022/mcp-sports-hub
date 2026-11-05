#!/usr/bin/env python3
"""Compact iPhone display of the ONE latest-pretip per-match settlement ledger.

Read-only renderer; it does not fetch results or recompute scored predictions.
It shows actual final score for misses and never turns an unknown final into HIT.
"""
from __future__ import annotations
import argparse,json
from datetime import datetime
from html import escape as E
from pathlib import Path
from zoneinfo import ZoneInfo

MARKET_NAMES={
 "had":"竞彩胜平负","hhad":"竞彩让球胜平负","ttg":"竞彩总进球数",
 "JINGCAI_WIN":"竞彩胜负","JINGCAI_HANDICAP":"竞彩让分胜负",
 "JINGCAI_TOTAL":"竞彩大小分","CROWN_HANDICAP":"皇冠让分","CROWN_TOTAL":"皇冠大小分"}
SPORT_NAMES={"football":"竞彩足球","basketball":"NBA 篮球"}
MARKET_ORDER={
 "football":("had","hhad","ttg"),
 "basketball":("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")}
OUTCOME={"HIT":"命中","MISS":"未中","PUSH":"走盘","UNSETTLED":"待赛果核实"}
BJ=ZoneInfo("Asia/Shanghai")

def clock(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.astimezone(BJ).strftime("%m月%d日 %H:%M") if d.tzinfo else "开赛时间待核"
    except (ValueError,TypeError):
        return "开赛时间待核"

def result_score(sport,row):
    if sport=="football":
        score=row.get("actual_score")
        if not isinstance(score,dict):return "赛果待核实",None,None
        h,a=score.get("home"),score.get("away")
    else:
        h,a=row.get("home_points"),row.get("away_points")
    if type(h) is not int or type(a) is not int:return "赛果待核实",None,None
    return f"{h}:{a}",h,a

def predicted(market,data):
    direction=data.get("direction")
    if isinstance(direction,list):
        value="/".join(str(x) for x in direction if x is not None) or "暂无有效判断"
    elif isinstance(direction,str):value=direction
    else:value="暂无有效判断"
    signed=data.get("signed_home_handicap",data.get("official_home_handicap"))
    if market in ("hhad","JINGCAI_HANDICAP","CROWN_HANDICAP") and type(signed) in (int,float):
        value+=f"（主{signed:+g}）"
    elif market in ("JINGCAI_TOTAL","CROWN_TOTAL") and type(data.get("line")) in (int,float):
        value+=f"（总分{data['line']:g}）"
    return value

def actual_market(sport,k,data,h,a):
    if h is None or a is None:return None
    if sport=="football":return data.get("actual")
    if k=="JINGCAI_WIN":return "主胜" if h>a else "客胜" if a>h else "平"
    if k.endswith("HANDICAP"):
        n=data.get("signed_home_handicap")
        if type(n) not in (int,float):return None
        x=h-a+n
        return "走盘" if abs(x)<1e-9 else "主赢盘" if x>0 else "客赢盘"
    n=data.get("line")
    if type(n) not in (int,float):return None
    x=h+a-n
    return "走盘" if abs(x)<1e-9 else "大分" if x>0 else "小分"

def render(report):
    sport=report.get("sport")
    if sport not in MARKET_ORDER or report.get("schema_version")!="sports-latest-pretip-scoring-v1":
        raise ValueError("ONLY_VERIFIED_PER_MATCH_SCORECARD")
    if report.get("prediction_source")!="LATEST_VERIFIED_PREKICKOFF_PER_MATCH_IMMUTABLE":
        raise ValueError("REVIEW_SOURCE_NOT_PER_MATCH_PRETIP_FINAL")
    if report.get("historical_2130_not_graded_separately") is not True:
        raise ValueError("OLD_2130_MUST_NOT_BE_SECOND_SCORECARD")
    import hashlib
    body={k:v for k,v in report.items() if k!="review_sha256"}
    sha=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if report.get("review_sha256")!=sha:
        raise ValueError("SCORECARD_HASH_MISMATCH")
    out=[
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "</head><body style='margin:0 auto;max-width:620px;padding:12px;",
        "font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;",
        "font-size:14px;line-height:1.6;background:#f5f7fa;color:#1c2d42'>",
        "<h2 style='font-size:20px;margin:4px 0 7px'>北京时间 ",
        E(str(report.get("beijing_day") or ""))," ",SPORT_NAMES[sport],"逐场复盘</h2>",
        "<p style='font-size:12px;color:#5f7185;margin:0 0 12px'>",
        "仅按每场最新有效赛前冻结版评分，21:30留档不重复计分。主队在左；未核实赛果不入样。</p>"]
    summary=report.get("summary") or {}
    for market in MARKET_ORDER[sport]:
        d=summary.get(market) or {}
        hit=d.get("hits",0);n=d.get("graded",0)
        if type(n) is not int or n<0 or type(hit) is not int or not 0<=hit<=n:
            raise ValueError("INVALID_SCORECARD_DENOMINATOR")
        value=f"{100*hit/n:.1f}%（{hit}/{n}）" if n else "暂无有效样本"
        more=[]
        for key,label in (("pushes","走盘"),("excluded","未入样"),("unsettled","待核")):
            if d.get(key):more.append(f"{label}{d[key]}")
        out.append("<div style='background:white;padding:7px 9px;border-bottom:1px solid #e9edf4'>"
                   "<b>"+MARKET_NAMES[market]+"</b>　<b>"+E(value)+"</b>"+
                   ("　"+E("　".join(more)) if more else "")+"</div>")
    for row in sorted(report.get("matches") or [],key=lambda r:(str(r.get("kickoff_utc") or r.get("tipoff_beijing") or ""),str(r.get("match_id") or r.get("game_id") or ""))):
        score,h,a=result_score(sport,row)
        title=str(row.get("jc_number") or row.get("jingcai_number") or "官方编号未核实")
        home=str(row.get("home_team") or "主队待核")
        away=str(row.get("away_team") or "客队待核")
        tip=clock(row.get("kickoff_utc") or row.get("tipoff_beijing"))
        out.extend(["<section style='margin:9px 0;padding:11px;background:white;",
                   "border:1px solid #dae2eb;border-radius:11px'>",
                   "<b>"+E(title)+"　"+E(home)+"（主） vs "+E(away)+"（客）</b>",
                   "<div style='font-size:12px;color:#66798c'>"+E(tip)+"　比分 <b>"+E(score)+"</b></div>"])
        markets=row.get("markets") or {}
        for m in MARKET_ORDER[sport]:
            x=markets.get(m) or {}
            status=x.get("outcome",x.get("status","UNSETTLED"))
            label=OUTCOME.get(status,"未入样" if str(status).startswith("EXCLUDED") else "状态待核")
            assert status!="HIT" or h is not None, "NO_SCORE_CAN_BE_A_HIT"
            verdict=predicted(m,x)
            extra=""
            if status=="MISS":
                actual=actual_market(sport,m,x,h,a)
                extra="　实际："+str(actual or "赛果方向待核")+"｜比分"+score
            out.extend(["<div style='padding:5px 0;border-top:1px solid #ebeff4'>",
                       E(MARKET_NAMES[m])+"　"+E(verdict)+"　",
                       "<b>"+E(label)+"</b>"+E(extra)+"</div>"])
        out.append("</section>")
    out.append("<p style='font-size:11px;color:#687b8e'>仅回测已封存的赛前判断；缺失、走盘和未核实赛果均不计入方向命中率。</p></body></html>")
    return "".join(out)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--review",required=True)
    p.add_argument("--html",required=True)
    a=p.parse_args()
    review=json.loads(Path(a.review).read_text(encoding="utf-8"))
    target=Path(a.html)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(review),encoding="utf-8")
    print("PER_MATCH_REVIEW_IPHONE_HTML",review.get("sport"),len(review.get("matches",[])))

if __name__=="__main__":main()
