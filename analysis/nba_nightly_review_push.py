#!/usr/bin/env python3
"""iPhone PushPlus 22:00 report from a pre-tip, frozen two-market forecast."""
import argparse,json,os,sys
from datetime import datetime
from html import escape
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from pushplus_mobile import send
def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def report(settled):
    day=settled["beijing_date"]
    out=["<div style='font-family:-apple-system,Arial,sans-serif;max-width:560px;margin:auto;color:#203149;font-size:14px;line-height:1.6'>",
         "<h2>NBA 22:00赛后复盘｜"+escape(day)+"</h2>",
         "<p>严格使用开赛前冻结的模型倾向与真实最终比分；盘口让分符号仍待独立验证，以下为研究结算而非可兑付收益。</p>"]
    labels={"HOME":"主队方向","AWAY":"客队方向","OVER":"大分","UNDER":"小分","UNASSESSABLE":"无法评估"}
    outcome={"HIT":"命中","MISS":"未中","PUSH":"走盘","UNSETTLED":"未结算"}
    for i,g in enumerate(settled["games"],1):
        h=g.get("home_points");a=g.get("away_points")
        score=(str(a)+" : "+str(h)) if h is not None and a is not None else "待核实"
        out.append("<div style='padding:11px;margin:9px 0;border:1px solid #dbe4f0;border-radius:9px'>"
          "<b>#"+str(i).zfill(2)+"　客队："+escape(str(g["away_team"]))+"　｜　主队："+escape(str(g["home_team"]))+"</b>"
          "<div>最终比分（客 : 主）："+escape(score)+"</div>")
        for key,label in (("SPREAD","全场让分"),("TOTAL","全场总分")):
            x=g["results"][key];d=labels.get(x.get("direction"),"无法评估")
            o=outcome.get(x["outcome"],"未结算")
            line=x.get("line")
            out.append("<div>"+label+"：<b>"+escape(d)+"</b>　参考盘 "+
              (escape(str(line)) if line is not None else "—")+"　｜　<b>"+o+"</b></div>")
        if g.get("reason"):out.append("<div style='color:#a86222'>原因："+escape(g["reason"])+"</div>")
        out.append("</div>")
    for k,label in (("SPREAD","让分"),("TOTAL","大小分")):
        q=settled["summary"][k]
        out.append("<div><b>"+label+"</b> 命中 "+str(q["HIT"])+" / 未中 "+str(q["MISS"])+
                   " / 走盘 "+str(q["PUSH"])+" / 未结算 "+str(q["UNSETTLED"])+"</div>")
    out.append("<p style='font-size:11px;color:#64748b'>22:00研究复盘；未验证实际可投注价格与盘口方向，不计算ROI。不会使用赛后赔率反推赛前预测。</p></div>")
    return "".join(out)
def test():
    s={"beijing_date":"2026-10-30","summary":{"SPREAD":{"HIT":1,"MISS":0,"PUSH":0,"UNSETTLED":0},"TOTAL":{"HIT":0,"MISS":1,"PUSH":0,"UNSETTLED":0}},
      "games":[{"home_team":"主","away_team":"客","home_points":112,"away_points":105,"results":{"SPREAD":{"direction":"HOME","line":-3.5,"outcome":"HIT"},"TOTAL":{"direction":"UNDER","line":220.5,"outcome":"MISS"}}}]}
    h=report(s);assert "客队：客" in h and "主队：主" in h and "命中" in h and "未中" in h
    print("NIGHTLY_2200_IPHONE_TEST_PASS")
def main():
    p=argparse.ArgumentParser();p.add_argument("--settlement");p.add_argument("--preview")
    p.add_argument("--status");p.add_argument("--send",action="store_true");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return test()
    if not all((a.settlement,a.preview,a.status)):raise SystemExit("MISSING_REPORT_ARGS")
    r=read(a.settlement)
    html=report(r)
    Path(a.preview).write_text(html,encoding="utf-8")
    state={"target":r["beijing_date"],"games":len(r["games"]),"state":"DRY_RUN_NOT_SENT"}
    if a.send:
        state.update(send({"title":"NBA每日22:00让分/大小分复盘｜"+r["beijing_date"],"html":html},
            os.environ.get("PUSHPLUS_TOKEN","")))
    Path(a.status).write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n")
    print("NIGHTLY_REVIEW_PUSHPLUS",state["state"],len(r["games"]))
if __name__=="__main__":main()
