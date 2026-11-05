#!/usr/bin/env python3
"""Football-only PushPlus sender: isolated token, explicit gate, no NBA imports."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from football_jc_report import render

ENDPOINT="https://www.pushplus.plus/send"
def verify_for_delivery(forecast):
    if forecast.get("source_status") != "LIVE_007_VERIFIED":
        raise ValueError("NOT_VERIFIED_LIVE_007_FOOTBALL")
    if forecast.get("model_status") not in ("RESEARCH_NOT_VALIDATED","PROSPECTIVE_VALIDATED"):
        raise ValueError("UNEXPECTED_FOOTBALL_MODEL_STATUS")
    rows=forecast.get("games",[])
    if not rows:raise ValueError("EMPTY_FOOTBALL_BOARD_NO_PUSH")
    if len(rows)>150:raise ValueError("FOOTBALL_BOARD_TOO_LARGE")
    seen=set()
    for row in rows:
        mid=str(row.get("match_id") or "")
        if not mid or mid in seen:raise ValueError("BAD_FOOTBALL_IDENTITY")
        seen.add(mid)
        if row.get("status")=="RESEARCH_READY":
            if not row.get("jc_number"):raise ValueError("MISSING_FOOTBALL_JC_NUMBER")
            m=row.get("markets") or {}
            for market in ("had","hhad","ttg"):
                if market not in m:raise ValueError("MISSING_FOOTBALL_JC_MARKET")
            picks=((m.get("ttg") or {}).get("goal_selection") or {}).get("goals") or []
            if len(picks)>2 or len(picks)!=len(set(picks)):
                raise ValueError("INVALID_TWO_GOALS")
    return True

def send(forecast, token):
    verify_for_delivery(forecast)
    if not token:raise ValueError("FOOTBALL_PUSHPLUS_TOKEN_NOT_SET")
    title="北京时间 "+str(forecast["beijing_date"])+" 竞彩足球球赛研判"
    content=render(forecast)
    if len(content.encode("utf-8"))>220000:raise ValueError("FOOTBALL_REPORT_TOO_LARGE")
    payload=json.dumps({"token":token,"title":title,"content":content,
                        "template":"html","channel":"wechat"},ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(ENDPOINT,data=payload,headers={"Content-Type":"application/json; charset=utf-8"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=18) as res:
            raw=res.read(10000)
            if res.status!=200:raise RuntimeError("PUSHPLUS_HTTP_"+str(res.status))
    except urllib.error.URLError as e:
        raise RuntimeError("FOOTBALL_PUSHPLUS_NETWORK_FAILURE") from e
    data=json.loads(raw)
    if data.get("code")!=200:raise RuntimeError("FOOTBALL_PUSHPLUS_API_NOT_ACCEPTED")
    return {"state":"API_ACCEPTED_NOT_DEVICE_CONFIRMED","model":"FOOTBALL_JC",
            "beijing_date":forecast["beijing_date"],
            "payload_sha256":hashlib.sha256(payload).hexdigest(),
            "accepted_at_utc":datetime.now(timezone.utc).isoformat(),
            "message_id":str(data.get("data") or "")[:80]}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--forecast",required=True)
    ap.add_argument("--preview",default="football_jc_preview.html")
    ap.add_argument("--status",default="football_jc_delivery_status.json")
    ap.add_argument("--send",action="store_true")
    a=ap.parse_args()
    forecast=json.loads(Path(a.forecast).read_text(encoding="utf-8"))
    Path(a.preview).write_text(render(forecast),encoding="utf-8")
    result={"state":"PREVIEW_ONLY","model":"FOOTBALL_JC"}
    if a.send:result=send(forecast,os.environ.get("FOOTBALL_PUSHPLUS_TOKEN"))
    Path(a.status).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_JC_PUSHPLUS",result["state"])

if __name__=="__main__":main()
