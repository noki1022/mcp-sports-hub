#!/usr/bin/env python3
"""Football-only PushPlus for immutable 21:00 grading baseline and twelve hourly reports.

The scheduled final's score source is never replaced by an update.
Requires a separate explicit phase and SHA-matching frozen reference.
Uses the same compact HTML sender interface as NBA, not its data/model.
"""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from html import escape
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_final_2130 as final
import football_jc_report as report
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pushplus_mobile import send, MAX_BYTES

def prepare(forecast,mode,lock=None,comparison=None,daytime_slot=None,movement=None):
    if forecast.get("model_version")!=final.FUSED_VERSION:
        raise ValueError("MUST_SEND_SINGLE_INTEGRATED_FOOTBALL_MODEL")
    if not forecast.get("games"):
        raise ValueError("NO_FOOTBALL_GAMES_TO_PUSH")
    if mode=="final":
        if not isinstance(lock,dict) or lock.get("schema_version")!=final.VERSION:
            raise ValueError("MUST_HAVE_FROZEN_FINAL")
        if final.sha(forecast)!=lock.get("final_forecast_sha256"):
            raise ValueError("FROZEN_FINAL_FORECAST_CONTENT_MISMATCH")
        label="21:30历史基准答卷"
    elif mode=="update":
        if not isinstance(lock,dict) or lock.get("schema_version")!=final.VERSION:
            raise ValueError("MUST_COMPARE_TO_ORIGINAL_FROZEN_FINAL")
        if not isinstance(comparison,dict) or comparison.get("schema_version")!="football-jc-0630-vs-final-v1":
            raise ValueError("MUST_HAVE_0630_COMPARISON")
        if comparison.get("compared_to_only_2130_sha256")!=lock.get("final_forecast_sha256"):
            raise ValueError("0630_WRONG_FINAL_COMPARISON")
        if final.sha(forecast)!=comparison.get("current_forecast_sha256"):
            raise ValueError("0630_CURRENT_FORECAST_MISMATCH")
        label="06:30更新｜对比21:30历史基准"
    elif mode=="morning-standalone":
        if lock is not None or comparison is not None:
            raise ValueError("MISSING_BASELINE_MODE_CANNOT_PRETEND_LOCKED")
        label="06:30赛前研判｜21:30基准缺失，不能对照"
    elif mode=="daytime":
        if lock is not None or comparison is not None:
            raise ValueError("DAYTIME_MUST_NOT_READ_YESTERDAY_BASELINE")
        if daytime_slot not in tuple(f"{h:02d}00" for h in range(12,24)):
            raise ValueError("UNRECOGNIZED_DAYTIME_CAPTURE_SLOT")
        label=daytime_slot[:2]+":00赛前研判"
    else:raise ValueError("INVALID_FOOTBALL_SEND_SLOT")
    title="北京时间"+str(forecast.get("beijing_date"))+" 足球球赛研判｜"+label
    html=report.render(forecast,comparison,mode if mode in ("final","update") else "research",movement)
    return {"title":title,"html":html}

def compact_html(forecast,comparison,mode,movement):
    """Small loss-aware layout: every match and all three JC verdicts remain visible."""
    e=lambda v: escape("—" if v is None else str(v),quote=True)
    parts=["<html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
           "<body style='font:14px/1.5 -apple-system,Arial;padding:8px'>",
           "<h3>北京时间 "+e(forecast.get("beijing_date"))+" 足球球赛研判</h3>"]
    for g in forecast.get("games",[]):
        parts.append("<div style='border-top:1px solid #ddd;padding:8px 0'><b>"+
                     e(g.get("jc_number"))+" "+e(g.get("league"))+" "+
                     e(g.get("home_team"))+"（主） vs "+e(g.get("away_team"))+"（客）</b>"+
                     "<div>北京时间 "+e(report.beijing_clock(g.get("kickoff_beijing")))+"</div>")
        for key,name in report.MARKETS:
            m=(g.get("markets") or {}).get(key) or {}
            direction=m.get("direction") or "暂无有效判断"
            probability=m.get("direction_probability")
            if key=="ttg" and (m.get("goal_selection") or {}).get("goals"):
                selection=m["goal_selection"]
                direction="/".join(map(str,selection["goals"]))
                probability=selection.get("combined_probability")
            handicap=m.get("signed_home_handicap")
            if key=="hhad":
                direction=str(direction)+"（主"+(f"{handicap:+g}" if isinstance(handicap,(int,float)) else "盘口待核")+"）"
            try: pct=f"{float(probability)*100:.1f}%" if probability is not None else "—"
            except (ValueError,TypeError): pct="—"
            parts.append("<div><b>"+e(name)+"：</b>"+e(direction)+" "+pct+"</div>")
        q=g.get("data_quality") or {}
        parts.append("<small>伤停："+("名单待核" if q.get("injury_listed_players_unconfirmed") else "待核实")+
                     "｜数据状态："+e(g.get("status"))+"</small></div>")
    parts.append("<small>概率未经充分回测校准；仅供研究。采集："+e(forecast.get("captured_at_utc"))+"</small></body></html>")
    return "".join(parts)

def payload_size(payload,token):
    return len(json.dumps({"token":token,"title":payload["title"],
                           "content":payload["html"],"template":"html",
                           "channel":"wechat"},ensure_ascii=False).encode("utf-8"))

def fit_payload(payload,forecast,comparison,mode,movement,token):
    if payload_size(payload,token)<=MAX_BYTES:return payload
    compact=compact_html(forecast,comparison,mode,movement)
    revised={**payload,"html":compact}
    if payload_size(revised,token)>MAX_BYTES:
        raise ValueError("FOOTBALL_COMPACT_PAYLOAD_TOO_LARGE_NO_MATCHES_DROPPED")
    return revised

def cli():
    ap=argparse.ArgumentParser()
    ap.add_argument("--forecast",required=True)
    ap.add_argument("--locked")
    ap.add_argument("--mode",required=True,choices=("final","update","daytime","morning-standalone"))
    ap.add_argument("--daytime-slot")
    ap.add_argument("--comparison")
    ap.add_argument("--movement")
    ap.add_argument("--html-out",required=True)
    ap.add_argument("--status-out",required=True)
    ap.add_argument("--send",action="store_true")
    ap.add_argument("--preflight",action="store_true",help="Validate payload before acquiring immutable send claim")
    a=ap.parse_args()
    def read(p):
        b=Path(p).read_bytes()
        if len(b)>25_000_000:raise ValueError("FOOTBALL_PUSH_INPUT_TOO_LARGE")
        return json.loads(b)
    forecast=read(a.forecast)
    lock=read(a.locked) if a.locked else None
    comparison=read(a.comparison) if a.comparison else None
    movement=read(a.movement) if a.movement else None
    payload=prepare(forecast,a.mode,lock,comparison,a.daytime_slot,movement)
    token=os.environ.get("FOOTBALL_PUSHPLUS_TOKEN") or ""
    payload=fit_payload(payload,forecast,comparison,a.mode,movement,token)
    out=Path(a.html_out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(payload["html"],encoding="utf-8")
    status={"status":"PREVIEW_ONLY","slot":a.mode,
            "payload_sha256":hashlib.sha256(payload["html"].encode()).hexdigest()}
    if a.send:
        if not token:raise ValueError("FOOTBALL_PUSHPLUS_TOKEN_MISSING")
        response=send(payload,token)
        status.update(status="API_ACCEPTED_NOT_DEVICE_CONFIRMED",api_response=response)
    path=Path(a.status_out);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n","utf-8")
    print("FOOTBALL_SINGLE_JC_PUSH",status["status"],a.mode,"bytes",payload_size(payload,token))
if __name__=="__main__":cli()
