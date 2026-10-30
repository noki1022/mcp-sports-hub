#!/usr/bin/env python3
"""Small durable NBA/CBA hourly snapshots and same-game market movement.
Only raw market slots; no fabricated bookmaker side/orientation or picks.
Captures the full joined board BEFORE the 3–30 minute final-window filter.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from html import escape
import json
import math
import os
from pathlib import Path
import re
import tempfile

MARKETS=("full_spread","full_total","half_spread","half_total")
FIELDS=("line","first_side_water","second_side_water")
SCHEMA="titan007-market-snapshot-v1"
MAX_BYTES=128000

def utc(x):
    d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("NO_UTC_OFFSET")
    return d.astimezone(timezone.utc)

def number(x):
    try:
        if x is None or x=="":return None
        x=float(x)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None

def point(g,market,stage):
    r=((g.get("markets") or {}).get(market) or {}).get(stage) or {}
    return {k:number(r.get(k)) for k in FIELDS}

def normalized(board):
    target=str(board["requested_display_date"])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",target):raise ValueError("BAD_TARGET_DATE")
    datetime.strptime(target,"%Y-%m-%d")
    stamp=utc(board["captured_at_utc"]).isoformat()
    found=set();games=[]
    for g in board.get("nba_cba_games",[]):
        if g.get("league") not in ("NBA","CBA"):continue
        gid=str(g.get("game_id",""))
        if not re.fullmatch(r"\d{4,12}",gid) or gid in found:raise ValueError("BAD_OR_DUPLICATE_ID")
        found.add(gid)
        if g.get("display_date")!=target or not g.get("home_team") or not g.get("away_team") or g["home_team"]==g["away_team"]:
            raise ValueError("MATCH_IDENTITY_INCONSISTENCY")
        mk={k:{s:point(g,k,s) for s in ("opening","current")} for k in MARKETS}
        if not any(mk[k]["current"]["line"] is not None for k in ("full_spread","full_total")):
            raise ValueError("NO_VALID_FULL_MARKET")
        games.append({"game_id":gid,"league":g["league"],"display_date":target,
                      "display_clock":g.get("display_clock"),"home_team":g["home_team"],
                      "away_team":g["away_team"],"markets":mk})
    games.sort(key=lambda x:x["game_id"])
    result={"schema_version":SCHEMA,"target_date":target,"captured_at_utc":stamp,
            "source_url":board.get("odds_source"),
            "site_display_timezone":"UNVERIFIED","market_side_orientation":"UNVERIFIED_RAW_SLOTS",
            "games":games}
    if len(json.dumps(result,ensure_ascii=False).encode())>MAX_BYTES:raise ValueError("SNAPSHOT_TOO_LARGE")
    return result

def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")

def history(target,root,daily,before):
    out=[]
    for p in sorted((Path(root)/target).glob("*.json")):
        try:
            if p.stat().st_size>MAX_BYTES:continue
            obj=json.loads(p.read_text(encoding="utf-8"))
            t=utc(obj["captured_at_utc"])
            if obj.get("schema_version")==SCHEMA and obj.get("target_date")==target and t<before:
                out.append((t,str(p),obj))
        except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):continue
    # Existing daily 06/12/21 snapshots are allowed only for identical target dates.
    for p in sorted((Path(daily)/target).glob("*/titan007_three_joined.json")):
        try:
            if p.stat().st_size>2000000:continue
            obj=normalized(json.loads(p.read_text(encoding="utf-8")))
            t=utc(obj["captured_at_utc"])
            if t<before:out.append((t,str(p),obj))
        except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):continue
    return sorted(out,key=lambda x:x[0])

def diff(a,b):
    return round(b-a,5) if a is not None and b is not None else None

def devig(q):
    a,b=(number(q.get(x)) for x in ("first_side_water","second_side_water"))
    if a is None or b is None or not (0<a<=20 and 0<b<=20):return None
    x,y=1/(1+a),1/(1+b)
    return x/(x+y)

def line_trend(values):
    """Classify observed raw line movement, never infer a betting direction."""
    nums=[number(v) for v in values]
    if len(nums)<2 or any(v is None for v in nums):return "INSUFFICIENT_HISTORY"
    changes=[b-a for a,b in zip(nums,nums[1:]) if abs(b-a)>1e-8]
    if not changes:return "FLAT"
    signs=[1 if v>0 else -1 for v in changes]
    if len(set(signs))==1:return "RISING" if signs[0]>0 else "FALLING"
    if len(signs)>=2 and signs[-1]!=signs[-2]:return "REVERSAL"
    return "MIXED"

def analyze(cur,previous):
    rows=[];now=utc(cur["captured_at_utc"])
    old=[(t,p,s) for t,p,s in previous if t<now and s.get("target_date")==cur["target_date"]]
    for game in cur["games"]:
        same=[]
        for t,p,s in old:
            for g in s.get("games",[]):
                if g.get("game_id")==game["game_id"] and all(g.get(k)==game.get(k) for k in ("league","display_date","home_team","away_team")):
                    same.append((t,p,g))
        same.sort(key=lambda x:x[0])
        prev=same[-1] if same else None
        first=same[0] if same else None
        moves={};flags=[]
        recent=same[-3:]
        for market in MARKETS:
            q=game["markets"][market]["current"]
            p=prev[2]["markets"][market]["current"] if prev else {}
            initial=first[2]["markets"][market]["current"] if first else {}
            d=diff(p.get("line"),q.get("line"))
            w={k:diff(p.get(k),q.get(k)) for k in ("first_side_water","second_side_water")}
            pb=devig(p);pa=devig(q)
            same_line=(d is not None and abs(d)<1e-8)
            # Raw slot implied probabilities on different lines refer to
            # different events. Do not compare or raise water alarms across lines.
            dp=diff(pb,pa) if same_line else None
            if d is not None and abs(d)>=(1 if "spread" in market else 2.5):flags.append("LINE")
            if same_line and ((dp is not None and abs(dp)>=.03) or
                              any(v is not None and abs(v)>=.07 for v in w.values())):
                flags.append("WATER")
            trace=[{"captured_at_utc":t.isoformat(),
                    "line":g["markets"][market]["current"]["line"]}
                   for t,_,g in recent]
            trace.append({"captured_at_utc":cur["captured_at_utc"],"line":q.get("line")})
            gap_minutes=round((now-prev[0]).total_seconds()/60,1) if prev else None
            three_delta=(diff(recent[0][2]["markets"][market]["current"].get("line"),q.get("line"))
                         if len(recent)==3 else None)
            moves[market]={"opening":game["markets"][market]["opening"],"previous":p or None,
                "current":q,"first_snapshot":initial or None,
                "delta_line_previous":d,"delta_line_first":diff(initial.get("line"),q.get("line")),
                "delta_water_previous":w,"devig_raw_slot1":pa,"delta_devig_raw_slot1":dp,
                "same_line_water_comparable":same_line,
                "last_three_reference_delta_line":three_delta,
                "recent_trace":trace,"trend":line_trend([v["line"] for v in trace]),
                "minutes_since_previous_capture":gap_minutes,
                "previous_is_within_95_minutes":gap_minutes is not None and gap_minutes<=95}
        status="FIRST_SNAPSHOT" if not prev else ("LINE_AND_WATER_MOVE" if set(flags)=={"LINE","WATER"} else
            "LINE_MOVE" if "LINE" in flags else "WATER_MOVE" if "WATER" in flags else "STABLE_OR_MINOR_MOVE")
        rows.append({"game_id":game["game_id"],"league":game["league"],"home_team":game["home_team"],
                     "away_team":game["away_team"],"display_clock":game.get("display_clock"),
                     "status":status,"history_captures":len(same),
                     "previous_at_utc":prev[0].isoformat() if prev else None,
                     "previous_path":prev[1] if prev else None,"markets":moves,
                     "interpretation":"Market change observation only. No independent directional verification."})
    return {"schema_version":"titan007-market-movement-v1","target_date":cur["target_date"],
            "captured_at_utc":cur["captured_at_utc"],"history_snapshots":len(old),
            "games":rows,"decision":"NO_BET",
            "warnings":["Quote timestamp is collection time, not verified bookmaker publication time.",
                        "Raw market water-side orientation and website displayed timezone are unverified."]}

def fmt(x):
    return "—" if x is None else f"{x:+.2f}" if isinstance(x,(int,float)) else escape(str(x))

def render(report,model):
    m={str(x.get("game_id")):x for x in (model or {}).get("games",[])}
    names={"full_spread":"全场让分","full_total":"全场总分","half_spread":"半场让分","half_total":"半场总分"}
    cards=[]
    for g in report["games"]:
        lines=[]
        for k,v in g["markets"].items():
            p=v["previous"] or {};q=v["current"]
            if p.get("line") is None and q.get("line") is None:continue
            d=v["delta_devig_raw_slot1"]
            lines.append("<div class='market'><b>"+names[k]+"</b><div>盘口 "+
                escape(str(p.get("line","—")))+" → "+escape(str(q.get("line")))+
                "　变化 "+fmt(v["delta_line_previous"])+"</div><small>水位1 "+
                escape(str(p.get("first_side_water","—")))+" → "+escape(str(q.get("first_side_water")))+
                "；水位2 "+escape(str(p.get("second_side_water","—")))+" → "+
                escape(str(q.get("second_side_water")))+
                "；去水槽位1概率变动 "+(fmt(d*100)+"个百分点" if d is not None else "—")+"</small></div>")
        pred=m.get(str(g["game_id"]),{})
        probs=pred.get("model_probability") or {}
        def pct(v):
            try:return f"{float(v)*100:.1f}%" if v is not None else "—"
            except (ValueError,TypeError):return "—"
        modeltext="<div class='model'>独立模型：主胜 "+pct(probs.get("home"))+" / 客胜 "+pct(probs.get("away"))+\
            "；主队净胜分 "+fmt(pred.get("margin_mean_home_minus_away"))+\
            "；预计总分 "+fmt(pred.get("total_mean"))+\
            "；数据状态 "+escape(str(pred.get("model_status","NO_MODEL_DATA")))+\
            "。未确认盘口方向，不进行投注推断。</div>"
        cards.append("<section><div class='header'><b>"+escape(g["home_team"])+" vs "+
            escape(g["away_team"])+"</b><span>"+escape(str(g["display_clock"]))+"</span></div>"+
            "<div class='small'>"+escape(g["league"])+" #"+escape(g["game_id"])+"　"+
            escape(g["status"])+"　已有 "+str(g["history_captures"])+" 次此前采样</div>"+
            "".join(lines)+modeltext+"</section>")
    css="body{max-width:760px;margin:auto;padding:14px;background:#f3f5f9;font:14px -apple-system,BlinkMacSystemFont,sans-serif;color:#152033}section{background:white;border-radius:14px;padding:14px;margin:12px 0}.header{display:flex;justify-content:space-between;gap:12px}.small,small{display:block;color:#65758a;font-size:12px;line-height:1.6;margin:6px 0}.market{border-top:1px solid #e8ecf1;padding:10px 0;line-height:1.8}.model{background:#f3f5fa;border-radius:8px;padding:10px;line-height:1.8}h1{font-size:21px}"
    return "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>"+css+"</style></head><body><h1>NBA / CBA 每小时盘口波动＋模型</h1><p>目标日期 "+escape(report["target_date"])+"，市场数据采样 "+str(report["history_snapshots"])+" 次。盘口方向和站点时区未核验，NO_BET。</p>"+"".join(cards)+"</body></html>"

def capture(args):
    current=normalized(json.loads(Path(args.current).read_text(encoding="utf-8")))
    hist=history(current["target_date"],args.root,args.daily_root,utc(current["captured_at_utc"]))
    report=analyze(current,hist)
    write(args.out_movement,report)
    if current["games"]:
        rid=re.sub("[^0-9]","",os.environ.get("GITHUB_RUN_ID","")) or "local"
        clock=utc(current["captured_at_utc"]).strftime("%Y%m%dT%H%M%SZ")
        path=Path(args.root)/current["target_date"]/(clock+"-"+rid+".json")
        if path.exists():raise FileExistsError("IMMUTABLE_SNAPSHOT_COLLISION")
        write(path,current)
        print("HOURLY_SNAPSHOT_SAVED",path,"games",len(current["games"]),"prior",len(hist))
    else:
        print("HOURLY_NO_MATCHED_GAMES_NO_SNAPSHOT")
    print("HOURLY_MOVEMENT_ANALYZED",len(report["games"]))

def selftest():
    m={"full_spread":{"current":{"line":-2.5,"first_side_water":.9,"second_side_water":.9}},
       "full_total":{"current":{"line":220.5,"first_side_water":.9,"second_side_water":.9}}}
    g={"game_id":"746353","league":"NBA","display_date":"2026-10-31","display_clock":"07:00",
       "home_team":"主队","away_team":"客队","markets":m}
    def board(g,at):return normalized({"requested_display_date":"2026-10-31","captured_at_utc":at,
                                        "nba_cba_games":[g]})
    before=board(g,"2026-10-30T13:00:00Z")
    assert analyze(before,[])["games"][0]["status"]=="FIRST_SNAPSHOT"
    later=json.loads(json.dumps(g));later["markets"]["full_total"]["current"]["line"]=224.0
    later["markets"]["full_spread"]["current"]["first_side_water"]=.79
    current=board(later,"2026-10-30T14:00:00Z")
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)/"hourly";p=root/"2026-10-31"/"a.json";write(p,before)
        newer=board(later,"2026-10-30T16:00:00Z");write(p.parent/"z.json",newer)
        h=history("2026-10-31",root,Path(tmp)/"daily",utc(current["captured_at_utc"]))
        assert len(h)==1
        a=analyze(current,h)
        assert a["games"][0]["status"]=="LINE_AND_WATER_MOVE"
        assert a["games"][0]["markets"]["full_total"]["delta_line_previous"]==3.5
        assert "独立模型" in render(a,None)
        assert a["games"][0]["markets"]["full_total"]["delta_devig_raw_slot1"] is None
        assert not a["games"][0]["markets"]["full_total"]["same_line_water_comparable"]
        # Consecutive snapshots vs a line reversal, with no fake price delta.
        mid=board(dict(g,markets={"full_total":{"current":{"line":222.5}},
                                 "full_spread":{"current":{"line":-2.5}}}),"2026-10-30T13:20:00Z")
        seq=analyze(current,[(utc(before["captured_at_utc"]),"a",before),
                            (utc(mid["captured_at_utc"]),"b",mid)])
        assert seq["games"][0]["markets"]["full_total"]["trend"]=="RISING"
        assert line_trend([220,225,221])=="REVERSAL"
        assert line_trend([220,221,222,223])=="RISING"
        assert seq["games"][0]["markets"]["full_total"]["minutes_since_previous_capture"]==40.0
        wrong=board(dict(g,home_team="不同队"),"2026-10-30T13:00:00Z")
        assert analyze(current,[(utc(wrong["captured_at_utc"]),"wrong",wrong)])["games"][0]["status"]=="FIRST_SNAPSHOT"
    print("HOURLY_SNAPSHOT_MOVEMENT_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    s=p.add_subparsers(dest="cmd",required=True)
    cap=s.add_parser("capture")
    cap.add_argument("--current",required=True)
    cap.add_argument("--root",default="reports/hourly")
    cap.add_argument("--daily-root",default="reports/daily")
    cap.add_argument("--out-movement",default="titan007_hourly_movement.json")
    rend=s.add_parser("render")
    rend.add_argument("--movement",required=True)
    rend.add_argument("--model",default="nba_model_analysis.json")
    rend.add_argument("--out-html",default="titan007_hourly_movement.html")
    s.add_parser("self-test")
    a=p.parse_args()
    if a.cmd=="self-test":return selftest()
    if a.cmd=="capture":return capture(a)
    report=json.loads(Path(a.movement).read_text(encoding="utf-8"))
    model=json.loads(Path(a.model).read_text(encoding="utf-8")) if Path(a.model).is_file() else None
    Path(a.out_html).write_text(render(report,model),encoding="utf-8")
    print("HOURLY_MOBILE_REPORT_READY",len(report["games"]))
if __name__=="__main__":main()
