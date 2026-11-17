#!/usr/bin/env python3
"""Fail closed on cross-artifact identity mismatch before PushPlus."""
import argparse,json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
MARKETS={"JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL"}
def content_quality(five):
    rows=five.get("games") or []
    missing_labels=sum(not re.fullmatch(r"周[一二三四五六日天]\d{3}",str(g.get("jingcai_number") or "")) for g in rows)
    counts={k:sum((g.get("markets") or {}).get(k,{}).get("status")=="DIRECTION_ISSUED" for g in rows) for k in sorted(MARKETS)}
    missing_jc=sum((g.get("markets") or {}).get(k,{}).get("status") not in (
        "DIRECTION_ISSUED","NOT_ON_SALE_USER_CONFIRMED") for g in rows for k in MARKETS if k.startswith("JINGCAI_"))
    missing_crown=sum((g.get("markets") or {}).get(k,{}).get("status")!="DIRECTION_ISSUED"
                      for g in rows for k in MARKETS if k.startswith("CROWN_"))
    provisional=sum(g.get("final_signal_status")!="FINAL_INJURY_VERIFIED" for g in rows)
    return {"status":"COMPLETE" if rows and not (missing_labels or missing_jc or missing_crown or provisional) else "PARTIAL",
        "games":len(rows),"missing_jingcai_numbers":missing_labels,"missing_jingcai_directions":missing_jc,
        "missing_crown_directions":missing_crown,"provisional_injury_games":provisional,"ready_counts":counts}

def check(joined,movement,dynamic,five):
    target=joined.get("requested_display_date")
    games=joined.get("nba_cba_games") or []
    ids=[str(g.get("game_id")) for g in games]
    if not target or not games or len(set(ids))!=len(ids):raise ValueError("INVALID_SLATE")
    def index(obj):
        rows=obj.get("games") or []
        out={str(x.get("game_id")):x for x in rows}
        if len(out)!=len(rows):raise ValueError("DUPLICATE_ARTIFACT_ID")
        return out
    moves,reviews,forecasts=map(index,(movement,dynamic,five))
    if set(ids)!=set(forecasts) or not set(ids)<=set(moves) or not set(ids)<=set(reviews):
        raise ValueError("DELIVERY_COHORT_MISMATCH")
    for g in games:
        gid=str(g["game_id"]);f=forecasts[gid]
        if not g.get("home_team") or not g.get("away_team") or g["home_team"]==g["away_team"]:
            raise ValueError("INVALID_TEAM_"+gid)
        if any(g[k]!=f.get(k) for k in ("home_team","away_team")):
            raise ValueError("TEAM_MISMATCH_"+gid)
        try:
            a=datetime.fromisoformat(str(g["start_time_beijing"]).replace("Z","+00:00"))
            z=datetime.fromisoformat(str(f["tipoff_beijing"]).replace("Z","+00:00"))
            if a.tzinfo is None or z.tzinfo is None or a!=z or a.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()!=target:
                raise ValueError("TIME_MISMATCH")
        except (KeyError,ValueError,TypeError) as e:
            raise ValueError("TIPOFF_MISMATCH_"+gid) from e
        if set(f.get("markets") or {})!=MARKETS:raise ValueError("FIVE_MARKETS_MISSING_"+gid)
    return len(games)
def selftest():
    g={"game_id":"1","home_team":"A","away_team":"B","start_time_beijing":"2026-11-01T03:00+08:00"}
    j={"requested_display_date":"2026-11-01","nba_cba_games":[g]}
    m={"games":[{"game_id":"1"}]};d={"games":[{"game_id":"1"}]}
    f={"games":[{"game_id":"1","home_team":"A","away_team":"B","tipoff_beijing":"2026-11-01T03:00+08:00","markets":{k:{} for k in MARKETS}}]}
    assert check(j,m,d,f)==1
    f["games"][0]["tipoff_beijing"]="2026-11-01T04:00+08:00"
    try:check(j,m,d,f)
    except ValueError:pass
    else:raise AssertionError("ACCEPTED_WRONG_TIP")
    print("DELIVERY_CONTRACT_SELFTEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("joined","movement","dynamic","five"):p.add_argument("--"+k)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:selftest()
    else:
        vals=[json.loads(Path(getattr(a,k)).read_text()) for k in ("joined","movement","dynamic","five")]
        print("DELIVERY_IDENTITY_CONTRACT_PASS",check(*vals))
        quality=content_quality(vals[-1])
        print("DELIVERY_CONTENT_QUALITY",json.dumps(quality,ensure_ascii=False))
        if quality["status"]!="COMPLETE":
            print("::warning::NBA_CONTENT_PARTIAL "+json.dumps(quality,ensure_ascii=False))
