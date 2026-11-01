#!/usr/bin/env python3
"""Official NBA pre-tip injury change monitor, safe for iPhone PushPlus.

No inferred player value, no fabricated odds, no retroactive tipoff data.
The report PDF's capture timestamp is a collection timestamp, not release proof.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo

from titan007_ev_analysis import NAMES

UTC=timezone.utc
BJ=ZoneInfo("Asia/Shanghai")
MARKETS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL",
         "CROWN_HANDICAP","CROWN_TOTAL")
LABELS=("竞彩胜负","竞彩让分","竞彩大小分","皇冠让分","皇冠大小分")
DIRECTION={"HOME_WIN":"主胜","AWAY_WIN":"客胜","HOME_COVER":"主队方向",
           "AWAY_COVER":"客队方向","OVER":"大分","UNDER":"小分"}
CODES={code:full for code,full in NAMES.values()}
MEDICAL=("injury/illness","injury","illness","rest","personal")
MIN_LEFT_TO_ALERT=2.0

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
def save(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")

def as_utc(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if d.tzinfo is None:return None
        return d.astimezone(UTC)
    except (ValueError,TypeError):return None

def now_utc(value=None):
    if value:
        d=as_utc(value)
        if d is None:raise ValueError("TIMEZONE_AWARE_NOW_REQUIRED")
        return d
    return datetime.now(UTC)

def _cohort_games(cohort):
    games=cohort.get("official_games") or {}
    result={}
    for event,rec in games.items():
        tip=as_utc(rec.get("utc_tip") or rec.get("tip"))
        if not tip:continue
        # NBA game ids are stable across dated 007 quote snapshots.
        gid=str(event)
        home=str(rec.get("home") or "")
        away=str(rec.get("away") or "")
        if gid in result or home not in CODES or away not in CODES or home==away:
            continue
        result[gid]={"tip":tip,"home":home,"away":away,
                     "seven_id":str((cohort.get("first_available_007") or
                                   cohort.get("priced_nba_to_007") or {}).get(gid) or "")}
    return result

def select(cohort_root,now=None):
    clock=now_utc(now)
    local=clock.astimezone(BJ)
    local_time=local.time().replace(tzinfo=None)
    if local_time<time(6,30) or local_time>time(21,30):
        return {"state":"SKIP_OUTSIDE_BEIJING_MONITOR_WINDOW",
                "time_utc":clock.isoformat(),"time_beijing":local.isoformat(),
                "monitor_window_beijing":"06:30-21:30"}
    root=Path(cohort_root)
    candidates=[]
    for i in (-1,0,1,2):
        day=(clock.astimezone(BJ).date()+timedelta(days=i)).isoformat()
        for sub in ("noon-cohorts","overnight-cohorts"):
            slot="1200.json" if sub=="noon-cohorts" else "2130.json"
            path=root/sub/day/slot
            if not path.is_file():continue
            try:obj=load(path)
            except (ValueError,OSError):continue
            if obj.get("target_beijing_date",obj.get("target_date"))!=day:
                continue
            active={k:round((x["tip"]-clock).total_seconds()/60,2)
                    for k,x in _cohort_games(obj).items()
                    if MIN_LEFT_TO_ALERT < (x["tip"]-clock).total_seconds()/60<=70}
            if active:
                candidates.append((len(active),sub=="noon-cohorts",day,path,active))
    if not candidates:
        return {"state":"SKIP_NO_IMMINENT_OFFICIAL_GAME","time_utc":clock.isoformat()}
    # Prefer the broad noon official slate, not the source order of betting lines.
    _,_,day,path,active=max(candidates,key=lambda x:(x[0],x[1]))
    return {"state":"WATCH","date":day,"cohort_path":str(path),
            "active_official_game_ids":sorted(active),"minutes_to_tip":active,
            "time_utc":clock.isoformat()}

def _players(teams,side):
    vals=teams.get(side)
    if not isinstance(vals,dict) or vals.get("report_state")!="PUBLISHED":return None
    result={}
    for p in vals.get("players") or []:
        status=p.get("status")
        name=str(p.get("name") or "").strip()
        if status not in ("Out","Doubtful","Questionable","Probable","Available") or not name:
            return None
        norm=" ".join(re.sub(r"[^a-z0-9]+"," ",name.casefold()).split())
        if not norm or norm in result:return None
        result[norm]={"name":name,"status":status,"reason":str(p.get("reason") or "")}
    return result

def extract(cohort,official,active,clock):
    board=_cohort_games(cohort)
    if not isinstance(official,dict) or not official.get("source_url"):
        raise ValueError("NO_OFFICIAL_SOURCE_URL")
    src=str(official["source_url"])
    # Official NBA index publishes legacy hour-only and current hour-minute filenames.
    if not re.fullmatch(
        r"https://ak-static\.cms\.nba\.com/referee/injury/"
        r"Injury-Report_\d{4}-\d{2}-\d{2}_\d{2}(?:_\d{2})?(?:AM|PM)\.pdf",
        src,
    ):
        raise ValueError("UNVERIFIED_OFFICIAL_PDF_LINK")
    capture=as_utc(official.get("captured_at_utc"))
    if not capture or capture>clock+timedelta(minutes=2) or clock-capture>timedelta(minutes=20):
        raise ValueError("MISSING_OR_STALE_CAPTURE_TIME")
    if not isinstance(official.get("matchups"),dict):raise ValueError("INVALID_OFFICIAL_MATCHUPS")
    ambiguous={(str(x.get("matchup")),str(x.get("team"))) for x in official.get("ambiguous_player_rows",[]) if isinstance(x,dict)}
    result={}
    for gid,record in board.items():
        tip=record["tip"]
        if capture>=tip or gid not in active:continue
        matchup=record["away"]+"@"+record["home"]
        sides=(("home",record["home"]),("away",record["away"]))
        names=official["matchups"].get(matchup)
        if not isinstance(names,dict):continue
        game={}
        for side,abbr in sides:
            fullname=CODES[abbr]
            if (matchup,fullname) in ambiguous:break
            row=next((val for key,val in names.items() if key.casefold()==fullname.casefold()),None)
            members=_players({"x":row},"x")
            if members is None:break
            game[side]={"team":abbr,"players":members}
        if len(game)!=2:continue
        result[gid]={"tip_utc":tip.isoformat(),"seven_id":record["seven_id"],
                     "home":game["home"],"away":game["away"]}
    return result

def _is_medical(before,after):
    texts=(str((before or {}).get("reason") or "")+" "+str((after or {}).get("reason") or "")).lower()
    return (not texts.strip() or any(x in texts for x in MEDICAL)
            or not any(x in texts for x in ("g league","two-way","two way","suspension","assignment")))

def diff(current,previous,active):
    events=[]
    if not previous:return events
    for gid in active:
        old=(previous.get("games") or {}).get(gid)
        new=current.get(gid)
        if not old or not new:continue
        for side in ("home","away"):
            o=old[side]["players"];n=new[side]["players"]
            for player in sorted(set(o)|set(n)):
                before=o.get(player);after=n.get(player)
                x=before.get("status") if before else "NOT_LISTED"
                y=after.get("status") if after else "NOT_LISTED"
                if x==y or not _is_medical(before,after):continue
                events.append({"nba_game_id":gid,"seven_id":new["seven_id"],
                               "side":side,"team":new[side]["team"],
                               "player":(after or before)["name"],
                               "from":x,"to":y,
                               "reason":(after or before).get("reason",""),
                               "newly_listed":before is None,
                               "removed_from_report":after is None})
    return events

def scan(cohort,official,previous,selection,now=None):
    clock=now_utc(now)
    active=selection.get("active_official_game_ids") or []
    if not active:return {"state":"SKIP_NO_ACTIVE_GAMES","events":[]}
    latest=extract(cohort,official,active,clock)
    if not latest:return {"state":"UNKNOWN_OFFICIAL_SIDES_NOT_COMPARABLE","events":[]}
    valid_previous=(previous if isinstance(previous,dict) and
                    previous.get("target_date")==selection.get("date") else None)
    if valid_previous and valid_previous.get("captured_at_utc"):
        last=as_utc(valid_previous["captured_at_utc"])
        cap=as_utc(official["captured_at_utc"])
        if not last or (cap and cap<last):
            return {"state":"STALE_OFFICIAL_CAPTURE_REJECTED","events":[]}
    events=diff(latest,valid_previous,active)
    merged=dict((valid_previous or {}).get("games") or {})
    merged.update(latest)
    snap={"schema_version":"nba-injury-pretip-monitor-v1",
          "target_date":selection["date"],
          "captured_at_utc":official["captured_at_utc"],
          "official_pdf_url":official["source_url"],
          "games":merged}
    event_id=hashlib.sha256(json.dumps(events,sort_keys=True).encode()).hexdigest()[:16] if events else None
    return {"state":"CHANGED" if events else "BASELINE_OR_UNCHANGED",
            "events":events,"event_id":event_id,"snapshot":snap,
            "monitored_games":len(latest),
            "initial_baseline":valid_previous is None,
            "active_official_game_ids":active}

def _fmtprob(x):
    try:return "%.1f%%"%(100*float(x))
    except (ValueError,TypeError):return "—"

def render_alert(scan_result,model,five,now=None):
    clock=now_utc(now)
    docs={str(x.get("nba_game_id")):x for x in model.get("games",[])}
    forecasts={str(x.get("nba_game_id")):x for x in five.get("games",[])}
    rows=[]
    for gid in sorted({x["nba_game_id"] for x in scan_result.get("events",[])}):
        p=docs.get(gid);f=forecasts.get(gid)
        if not p or not f:raise ValueError("MISSING_RECOMPUTED_MODEL_OR_FIVE_MARKETS_"+gid)
        if p.get("model_status") not in ("OK","PARTIAL"):raise ValueError("MISSING_INDEPENDENT_MODEL_"+gid)
        tip=as_utc(f.get("tipoff_beijing"))
        if not tip or (tip-clock).total_seconds()/60 <= MIN_LEFT_TO_ALERT:
            raise ValueError("ALERT_TIME_PAST_SAFE_TIPOFF_"+gid)
        if not set(MARKETS).issubset(f.get("markets") or {}):
            raise ValueError("INCOMPLETE_FIVE_MARKET_BOARD_"+gid)
        adj=p.get("injury_adjustment") or {}
        if adj.get("adjusted") is True and adj.get("status")!="PLAYER_IMPACT_APPLIED_EXPERIMENTAL":
            raise ValueError("UNVERIFIED_ADJUSTMENT_FLAG")
        ev=[x for x in scan_result["events"] if x["nba_game_id"]==gid]
        detail="；".join(html.escape(e["player"]+" "+e["from"]+" → "+e["to"])
                        for e in ev)
        s="<section style='border:1px solid #e1e4e8;border-radius:10px;padding:12px;margin:10px 0'>"
        s+="<b>"+html.escape(str(f.get("jingcai_number") or "编号未核验"))+" "+html.escape(str(f.get("home_team")))+" vs "+html.escape(str(f.get("away_team")))+"</b>"
        s+="<p>官方伤停变化："+detail+"</p>"
        s+="<p>独立模型主胜 "+_fmtprob((p.get("model_probability") or {}).get("home"))+"，客胜 "+_fmtprob((p.get("model_probability") or {}).get("away"))+"</p>"
        if adj.get("adjusted") is True:
            s+="<p><b>球员影响已计算（实验）</b>：修正前主胜 "+_fmtprob(adj.get("preinjury_home_probability"))+" → 修正后 "+_fmtprob(adj.get("postinjury_home_probability"))+"</p>"
        else:
            s+="<p><b>伤停概率修正未启用：</b>缺少经过独立回测的球员影响参数；本次独赢概率不可解释为伤停引起的变化。</p>"
        for key,label in zip(MARKETS,LABELS):
            m=f["markets"][key]
            d=DIRECTION.get(m.get("direction"),"无可核验方向")
            if key.endswith("HANDICAP"):
                hand=m.get("signed_home_handicap")
                d+="（主 "+("%+.1f"%hand if isinstance(hand,(float,int)) else "盘口未核实")+"）"
            elif key.endswith("TOTAL"):
                line=m.get("line")
                d+="（"+str(line) if isinstance(line,(int,float)) else "（盘口未核实"
                d+="）"
            prob=m.get("model_direction_probability")
            d+=" · "+_fmtprob(prob) if isinstance(prob,(int,float)) else " · 概率待校验"
            s+="<p>"+label+"："+html.escape(d)+"</p>"
        rows.append(s+"</section>")
    return ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<body style='font-family:-apple-system,Arial,sans-serif;font-size:14px;line-height:1.45;color:#182231'>"
            "<h3>NBA 临场伤停变更 · 五玩法复核</h3>"
            "<p>官方报告更新触发重新抓取 007 并运行独立模型。未验证的球员影响绝不推算为胜率。</p>"
            +"".join(rows)+"<p style='color:#777;font-size:12px'>北京时间；机构皇冠严格仅使用 007 ID3；推送 API 接收不代表手机已送达。</p></body>")

def self_test():
    from tempfile import TemporaryDirectory
    from copy import deepcopy
    with TemporaryDirectory() as tmp:
        d=Path(tmp);root=d/"reports"
        j={"target_beijing_date":"2026-11-01","official_games":{"401":{
            "home":"ATL","away":"MIA","utc_tip":"2026-11-01T00:00:00Z"}},
            "first_available_007":{"401":"778899"}}
        p=root/"noon-cohorts/2026-11-01/1200.json";save(p,j)
        sel=select(root,"2026-10-31T23:30:00Z")
        assert sel["state"]=="WATCH" and sel["active_official_game_ids"]==["401"]
        assert select(root,"2026-11-01T00:05:00Z")["state"].startswith("SKIP")
        # A next-day 22:00 Beijing tip is deliberately not monitored after 21:30.
        late={"target_beijing_date":"2026-10-31","official_games":{
            "402":{"home":"ATL","away":"MIA","utc_tip":"2026-10-31T14:00:00Z"}},
            "first_available_007":{"402":"778900"}}
        save(root/"noon-cohorts/2026-10-31/1200.json",late)
        assert select(root,"2026-10-31T13:35:00Z")["state"]=="SKIP_OUTSIDE_BEIJING_MONITOR_WINDOW"
        # The cutoff is inclusive at exactly 21:30 Beijing.
        boundary=select(root,"2026-10-31T13:30:00Z")
        assert boundary["state"]=="WATCH" and boundary["active_official_game_ids"]==["402"]
        def record(status):
            return {"report_state":"PUBLISHED","players":[{"name":"A, B","status":status,"reason":"Injury/Illness - Strain"}]}
        valid_urls=("https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_05PM.pdf",
                    "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_05_00PM.pdf")
        for url in valid_urls:
            probe={"source_url":url,"captured_at_utc":"2026-10-31T23:30:00Z","matchups":{}}
            assert isinstance(extract(j,probe,{"401":1},now_utc("2026-10-31T23:30:00Z")),dict)
        for url in ("https://example.com/referee/injury/Injury-Report_2026-10-31_05_00PM.pdf",
                    "https://ak-static.cms.nba.com.evil.test/referee/injury/Injury-Report_2026-10-31_05_00PM.pdf",
                    "https://ak-static.cms.nba.com/referee/injury/not-an-injury-report.pdf"):
            try: extract(j,{"source_url":url,"captured_at_utc":"2026-10-31T23:30:00Z","matchups":{}},{"401":1},now_utc("2026-10-31T23:30:00Z"))
            except ValueError as exc: assert str(exc)=="UNVERIFIED_OFFICIAL_PDF_LINK"
            else: raise AssertionError("UNVERIFIED_INJURY_SOURCE_ACCEPTED: "+url)
        official={"source_url":valid_urls[0],
                  "captured_at_utc":"2026-10-31T23:30:00Z",
                  "matchups":{"MIA@ATL":{"Atlanta Hawks":record("Questionable"),
                                       "Miami Heat":{"report_state":"PUBLISHED","players":[]}}}}
        a=scan(j,official,None,sel,"2026-10-31T23:30:00Z")
        assert a["state"]=="BASELINE_OR_UNCHANGED" and not a["events"]
        official["captured_at_utc"]="2026-10-31T23:35:00Z"
        official["matchups"]["MIA@ATL"]["Atlanta Hawks"]=record("Out")
        b=scan(j,official,a["snapshot"],sel,"2026-10-31T23:35:00Z")
        assert b["state"]=="CHANGED" and len(b["events"])==1
        assert b["events"][0]["from"]=="Questionable" and b["events"][0]["to"]=="Out"
        # Ignore arbitrary G League designation-only churn.
        official["matchups"]["MIA@ATL"]["Atlanta Hawks"]["players"].append(
            {"name":"C, D","status":"Out","reason":"G League - Two-Way"})
        c=scan(j,official,a["snapshot"],sel,"2026-10-31T23:35:00Z")
        assert len(c["events"])==1
        # Keep the last valid report through NOT_SUBMITTED; do not assume healthy.
        official["matchups"]["MIA@ATL"]["Atlanta Hawks"]["report_state"]="NOT_SUBMITTED"
        d0=scan(j,official,a["snapshot"],sel,"2026-10-31T23:35:00Z")
        assert d0["state"]=="UNKNOWN_OFFICIAL_SIDES_NOT_COMPARABLE"
        # Real forecasts must exist; no fabricated directions.
        try:render_alert(b,{"games":[]},{"games":[]},"2026-10-31T23:35:00Z")
        except ValueError as e:assert "MISSING_RECOMPUTED" in str(e)
        else:raise AssertionError("ALERT_WITHOUT_MODEL")
        try:as_utc("2026-11-01T00:00:00")
        except ValueError:pass
        assert as_utc("2026-11-01T00:00:00") is None
        print("NBA_INJURY_WATCH_PIT_CHANGE_AND_NO_FABRICATION_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",required=True,choices=("select","scan","render","self-test"))
    p.add_argument("--cohort-root",default="reports")
    p.add_argument("--cohort");p.add_argument("--official");p.add_argument("--previous")
    p.add_argument("--selection");p.add_argument("--scan");p.add_argument("--model");p.add_argument("--five")
    p.add_argument("--out",default="nba_injury_watch.json");p.add_argument("--snapshot")
    p.add_argument("--now")
    a=p.parse_args()
    if a.mode=="self-test":return self_test()
    if a.mode=="select":o=select(a.cohort_root,a.now)
    elif a.mode=="scan":
        selection=load(a.selection)
        o=scan(load(a.cohort),load(a.official),
               load(a.previous) if a.previous and Path(a.previous).exists() else None,
               selection,a.now)
        if o.get("snapshot") is not None and a.snapshot:save(a.snapshot,o["snapshot"])
    else:
        html_doc=render_alert(load(a.scan),load(a.model),load(a.five),a.now)
        Path(a.out).write_text(html_doc,encoding="utf-8")
        print("NBA_INJURY_ALERT_RENDERED")
        return
    save(a.out,o)
    print("NBA_INJURY_WATCH",o.get("state"),"events",len(o.get("events",[])))
if __name__=="__main__":main()
