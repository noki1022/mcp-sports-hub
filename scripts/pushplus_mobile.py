#!/usr/bin/env python3
"""PushPlus delivery + compact HTML for iPhone NBA/CBA market/model reports.

No invented market orientation or betting tips. A HTTP 200 response is NOT enough:
only a parsed PushPlus JSON code==200 is API-accepted, not handset-delivered.
Secrets never written to HTML/status/logs. HTML uses simple inline styles for
WeChat's conservative renderer, readable at 320px. Dry-run needs no secrets.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
from html import escape
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from pushplus_mobile_v2 import render_v2,from_three

ENDPOINT="https://www.pushplus.plus/send"
TEMPLATE="html"
MAX_GAMES=16
MAX_BYTES=70000

def txt(value, fallback="—"):
    if value is None or value=="":return fallback
    return escape(str(value),quote=True)

def fmt(x, digits=1, sign=False):
    try:
        if x is None or x=="":return "—"
        x=float(x)
        if not (-10000<x<10000):return "—"
        return f"{x:+.{digits}f}" if sign else f"{x:.{digits}f}"
    except (ValueError,TypeError):return "—"

def pct(x):
    try:
        if x is None:return "—"
        v=float(x)
        return f"{v*100:.1f}%" if 0<=v<=1 else "—"
    except (ValueError,TypeError):return "—"

def read(path):
    if not path:return {}
    p=Path(path)
    if not p.is_file():return {}
    return json.loads(p.read_text(encoding="utf-8"))

def style(color="#24364b"):
    return f"font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;font-size:14px;line-height:1.65;color:{color};"

def p(body):
    return "<p style='margin:5px 0;font-size:14px;line-height:1.65;'>"+body+"</p>"

def section(title,subtitle,body):
    return ("<div style='margin:12px 0;padding:12px;border:1px solid #e5eaf1;border-radius:10px;background:#fff;'>"
            "<div style='font-size:16px;font-weight:700;color:#172a40;'>"+title+"</div>"
            "<div style='font-size:12px;color:#6d7b8c;margin:3px 0 9px;'>"+subtitle+"</div>"
            +body+"</div>")

def header(label,target,summary):
    return ("<div style='padding:13px 12px;background:#f1f5fa;border-radius:10px;'>"
            "<div style='font-size:19px;font-weight:700;color:#14283e;'>"+txt(label)+"</div>"
            "<div style='font-size:12px;color:#526479;margin-top:4px;'>北京时间 · "+txt(target)+
            " · "+txt(summary)+"</div></div>")

def footer():
    return ("<div style='margin-top:14px;border-top:1px solid #e5eaf1;padding:10px 2px;color:#64748b;font-size:12px;line-height:1.7;'>"
            "采样时刻不是博彩公司报价发布时间。盘口方向、部分站点显示时区及伤停尚未独立证实。"
            "<strong>未通过校准与盘口方向验收前：NO_BET。</strong></div>")

def model_map(model):
    return {str(x.get("game_id")):x for x in model.get("games",[])}

def model_line(item):
    if not item:return p("<span style='color:#69788a;'>独立模型：当前无可验证结果</span>")
    m=item.get("model_probability") or {}
    total=fmt(item.get("total_mean"))
    margin=fmt(item.get("margin_mean_home_minus_away"),sign=True)
    return p("模型 · 主胜 <strong>"+pct(m.get("home"))+"</strong> / 客胜 <strong>"+
             pct(m.get("away"))+"</strong>　净胜分 "+margin+"　总分 "+total)

def market_line(label,market):
    source=market or {}
    op=(source.get("opening") or {}).get("line")
    cur=(source.get("current") or {}).get("line")
    return p(txt(label)+"　<strong>"+fmt(op)+" → "+fmt(cur)+"</strong>")

def three_report(joined,model,movement):
    games=joined.get("nba_cba_games",[])[:MAX_GAMES]
    predictions=model_map(model)
    moves={str(x.get("game_id")):x for x in movement.get("games",[])}
    title="NBA/CBA 赛前模型｜"+str(joined.get("requested_display_date","未知日期"))
    body=[header("NBA / CBA 赛前分析",joined.get("requested_display_date"),
                 "共 "+str(len(joined.get("nba_cba_games",[])))+" 场")]
    for g in games:
        gid=str(g.get("game_id"))
        obj=moves.get(gid,{})
        parts=[model_line(predictions.get(gid))]
        for market,label in (("full_spread","让分"),("full_total","总分")):
            parts.append(market_line(label,(g.get("markets") or {}).get(market)))
            d=((obj.get("changes") or {}).get("spread" if market=="full_spread" else "total") or {}).get("delta")
            if d is not None:parts.append(p("较上次变化 "+fmt(d,sign=True)))
        if obj.get("status"):parts.append(p("盘口观察："+txt(obj["status"])))
        parts.append(p("<strong>结论：数据不足以确认投注优势 · NO_BET</strong>"))
        subtitle=txt(g.get("league"))+" · "+txt(g.get("display_clock"))+" · #"+txt(gid)
        body.append(section(txt(g.get("home_team"))+" vs "+txt(g.get("away_team")),subtitle,"".join(parts)))
    if not games:body.append(p("当前没有匹配的 NBA/CBA 比赛，未发送空消息。"))
    body.append(footer())
    return title,"".join(body),len(games)

def hourly_report(movement,model,final_window):
    allgames=movement.get("games",[])
    pmap=model_map(model)
    final_ids={str(g.get("game_id")) for g in final_window.get("nba_cba_games",[])}
    flagged={"LINE_MOVE","WATER_MOVE","LINE_AND_WATER_MOVE"}
    significant=[g for g in allgames if g.get("status") in flagged or str(g.get("game_id")) in final_ids]
    target=movement.get("target_date","未知日期")
    body=[header("NBA / CBA 盘口异动",target,str(len(significant))+" 场需要关注")]
    for g in significant[:MAX_GAMES]:
        gid=str(g.get("game_id"))
        parts=[]
        for market,label in (("full_spread","全场让分"),("full_total","全场总分")):
            m=(g.get("markets") or {}).get(market) or {}
            prev=m.get("previous") or {}
            curr=m.get("current") or {}
            parts.append(p(txt(label)+"　<strong>"+fmt(prev.get("line"))+" → "+
                           fmt(curr.get("line"))+"</strong>　("+fmt(m.get("delta_line_previous"),sign=True)+")"))
            if m.get("delta_devig_raw_slot1") is not None:
                parts.append(p("<span style='color:#526479;'>原始水位槽位1 去水概率变化 "+
                               fmt(float(m["delta_devig_raw_slot1"])*100,sign=True)+" 个百分点</span>"))
        parts.append(model_line(pmap.get(gid)))
        subtitle=(txt(g.get("league"))+" · "+txt(g.get("display_clock"))+" · "+
                  txt(g.get("status"))+(" · 临场" if gid in final_ids else ""))
        parts.append(p("<strong>模型与盘口结合判断：方向未核验，NO_BET</strong>"))
        body.append(section(txt(g.get("home_team"))+" vs "+txt(g.get("away_team")),subtitle,"".join(parts)))
    body.append(footer())
    return "NBA/CBA 盘口波动｜"+str(target),"".join(body),len(significant)

def parse_response(status,raw):
    if status!=200:raise RuntimeError("PUSHPLUS_HTTP_NOT_200")
    try:obj=json.loads(raw.decode("utf-8"))
    except (ValueError,UnicodeDecodeError) as exc:raise RuntimeError("PUSHPLUS_RESPONSE_NOT_JSON") from exc
    if not isinstance(obj,dict):raise RuntimeError("PUSHPLUS_RESPONSE_NOT_OBJECT")
    if obj.get("code")!=200:raise RuntimeError("PUSHPLUS_API_REJECTED_CODE_"+str(obj.get("code")))
    return {"state":"API_ACCEPTED_NOT_DEVICE_CONFIRMED","http_status":status,"api_code":200,
            "message_id":str(obj.get("data",""))[:100] if obj.get("data") is not None else None}

def send(payload,token):
    if not token:raise RuntimeError("PUSHPLUS_TOKEN_NOT_CONFIGURED")
    data=json.dumps({"token":token,"title":payload["title"],
                     "content":payload["html"],"template":TEMPLATE,
                     "channel":"wechat"},ensure_ascii=False).encode("utf-8")
    if len(data)>MAX_BYTES:raise ValueError("PUSHPLUS_PAYLOAD_TOO_LARGE")
    req=urllib.request.Request(ENDPOINT,data=data,headers={
        "Content-Type":"application/json; charset=utf-8","Accept":"application/json"
    },method="POST")
    try:
        with urllib.request.urlopen(req,timeout=18) as res:
            raw=res.read(8192)
            return parse_response(res.status,raw)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("PUSHPLUS_HTTP_ERROR_"+str(exc.code)) from None
    except urllib.error.URLError as exc:
        raise RuntimeError("PUSHPLUS_NETWORK_FAILURE") from None

def save_status(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--mode",choices=("three","hourly","smoke"),required=True)
    a.add_argument("--joined")
    a.add_argument("--movement")
    a.add_argument("--window")
    a.add_argument("--model")
    a.add_argument("--dynamic")
    a.add_argument("--top10")
    a.add_argument("--verdict")
    a.add_argument("--preview",default="pushplus_mobile_preview.html")
    a.add_argument("--status",default="pushplus_status.json")
    a.add_argument("--send",action="store_true")
    a.add_argument("--require-token",action="store_true")
    a.add_argument("--self-test",action="store_true")
    args=a.parse_args()
    if args.self_test:return selftest()
    if args.mode=="smoke":
        title="NBA 自动化通知链路测试"
        html=header("PushPlus 通知测试","2026-10-30","仅此一次，不是比赛预测")+p("如果你看到这条消息，说明 GitHub 已成功调用 PushPlus API。")+"<p>此消息不代表每场比赛模型已验证。</p>"
        count=1
    elif args.mode=="three":
        joined=read(args.joined)
        if args.dynamic:
            movement=read(args.movement)
            by_move={str(x.get("game_id")):x for x in movement.get("games",[])}
            by_review={str(x.get("game_id")):x for x in read(args.dynamic).get("games",[])}
            rows=[]
            for g in joined.get("nba_cba_games",[]):
                gid=str(g.get("game_id"))
                row=by_move.get(gid)
                if row is None:
                    raise RuntimeError("MISSING_DYNAMIC_SNAPSHOT_FOR_GAME_"+gid)
                rows.append({**row,"dynamic_review":by_review.get(gid)})
                if not rows[-1]["dynamic_review"]:
                    raise RuntimeError("MISSING_DYNAMIC_ANALYSIS_FOR_GAME_"+gid)
        else:
            rows=from_three(joined,read(args.model),read(args.movement))
        model={str(x.get("game_id")):x for x in read(args.model).get("games",[])}
        count=len(rows)
        title="NBA/CBA 赛前研判 V2｜"+str(joined.get("requested_display_date","未知"))
        html=render_v2(rows,model,"NBA/CBA 赛前研判 V2",joined.get("requested_display_date","未知"),"three")
    else:
        movement=read(args.movement)
        dynamic={str(g.get("game_id")):g for g in read(args.dynamic).get("games",[])}
        for row in movement.get("games",[]):
            row["dynamic_review"]=dynamic.get(str(row.get("game_id")))
        window=read(args.window)
        model={str(x.get("game_id")):x for x in read(args.model).get("games",[])}
        ids={str(x.get("game_id")) for x in window.get("nba_cba_games",[])}
        rows=[g for g in movement.get("games",[]) if g.get("status") in ("LINE_MOVE","WATER_MOVE","LINE_AND_WATER_MOVE") or str(g.get("game_id")) in ids]
        count=len(rows)
        title="NBA/CBA 盘口动态 V2｜"+str(movement.get("target_date","未知"))
        html=render_v2(rows,model,"NBA/CBA 盘口动态 V2",movement.get("target_date","未知"),"hourly")
    if (args.top10 or args.verdict) and args.mode!="smoke":
        multi=read(args.top10)
        top={str(x.get("game_id")):x for x in multi.get("games",[])}
        verdict={str(x.get("game_id")):x for x in read(args.verdict).get("games",[])}
        for row in rows:
            row["top10_comparison"]=top.get(str(row.get("game_id")))
            row["two_market_verdict"]=verdict.get(str(row.get("game_id")))
        html=render_v2(rows,model,title,joined.get("requested_display_date") if args.mode=="three" else movement.get("target_date"),args.mode)
    html="<div style='"+style()+"max-width:560px;margin:0 auto;'>"+html+"</div>"
    Path(args.preview).write_text(html,encoding="utf-8")
    state={"mode":args.mode,"games_considered":count,"template":"html","preview":args.preview}
    if count==0:
        state.update(state="SKIPPED_NO_RELEVANT_GAMES")
    elif not args.send:
        state.update(state="DRY_RUN_NOT_SENT")
    elif not os.environ.get("PUSHPLUS_TOKEN",""):
        state.update(state="NOT_CONFIGURED_NO_TOKEN")
        print("::warning::PUSHPLUS_NOT_CONFIGURED",flush=True)
        if args.require_token:
            save_status(args.status,state)
            raise RuntimeError("PUSHPLUS_TOKEN_NOT_CONFIGURED")
    else:
        try:state.update(send({"title":title,"html":html},os.environ["PUSHPLUS_TOKEN"]))
        except Exception as exc:
            state.update(state="SEND_FAILED",reason=str(exc)[:120])
            save_status(args.status,state)
            raise
    save_status(args.status,state)
    print("PUSHPLUS_DELIVERY_STATE",state["state"],"GAMES",count)

def selftest():
    board={"requested_display_date":"2026-10-31","nba_cba_games":[{
        "game_id":"7","league":"NBA","home_team":"<img src=x onerror=x>","away_team":"客队",
        "display_clock":"07:00","markets":{"full_spread":{"opening":{"line":-3.5},"current":{"line":-4.5}},
                                       "full_total":{"opening":{"line":219.5},"current":{"line":221.5}}}}]}
    name,html,count=three_report(board,{},{});assert count==1
    assert "&lt;img" in html and "<img src=x" not in html
    assert "NO_BET" in html and "219.5" in html
    sample={"target_date":"2026-10-31","games":[{"game_id":"7","league":"NBA",
        "home_team":"主队","away_team":"客队","display_clock":"07:00","status":"LINE_MOVE",
        "markets":{"full_spread":{"previous":{"line":-3.5},"current":{"line":-4.5},"delta_line_previous":-1.0},
                   "full_total":{"previous":{"line":220.5},"current":{"line":223.0},"delta_line_previous":2.5}}}]}
    _,html,count=hourly_report(sample,{},{});assert count==1 and "223.0" in html
    assert parse_response(200,b'{"code":200,"msg":"success","data":"abc"}')["state"]=="API_ACCEPTED_NOT_DEVICE_CONFIRMED"
    for status,body in ((200,b'{"code":500,"msg":"oops"}'),(500,b'{"code":200}'),(200,b'not json')):
        try:parse_response(status,body);raise AssertionError("WRONG_RESPONSE_ACCEPTED")
        except RuntimeError:pass
    assert not any(w in html.lower() for w in ("token","api_key"))
    from pushplus_mobile_v2 import self_test as v2_test
    v2_test()
    print("PUSHPLUS_IPHONE_FORMAT_AND_RESPONSE_SELF_TEST_PASS")

if __name__=="__main__":main()
