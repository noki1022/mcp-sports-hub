#!/usr/bin/env python3
"""Compare the current report with the latest prior snapshot for the same target date."""
from __future__ import annotations
import argparse,json
from pathlib import Path
def num(x):
    try:return float(x)
    except:return None
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--current",required=True); ap.add_argument("--history-root",required=True); ap.add_argument("--out",required=True)
    a=ap.parse_args()
    cur=json.loads(Path(a.current).read_text(encoding="utf-8"))
    dirs=sorted([p for p in Path(a.history_root).glob("*") if p.is_dir() and (p/"titan007_three_joined.json").exists()])
    prev=json.loads((dirs[-1]/"titan007_three_joined.json").read_text(encoding="utf-8")) if dirs else {}
    pm={str(g.get("game_id")):g for g in prev.get("nba_cba_games",[])}
    rows=[]
    for g in cur.get("nba_cba_games",[]):
        old=pm.get(str(g.get("game_id")),{})
        def line(x,m,s): return x.get("markets",{}).get(m,{}).get(s,{}).get("line")
        changes={}
        for m,label in (("full_spread","spread"),("full_total","total")):
            before=num(line(old,m,"current")); after=num(line(g,m,"current"))
            changes[label]={"previous":before,"current":after,"delta":(after-before if before is not None and after is not None else None)}
        status="BASELINE" if not old else "STABLE"
        deltas=[v["delta"] for v in changes.values() if v["delta"] is not None]
        if any(abs(x)>=1 for x in deltas): status="SIGNIFICANT_MARKET_MOVE"
        if any(abs(x)>=2 for x in deltas): status="ABRUPT_MOVE"
        rows.append({"game_id":g.get("game_id"),"home_team":g.get("home_team"),"away_team":g.get("away_team"),"status":status,"changes":changes})
    out={"target_date":cur.get("requested_display_date"),"previous_snapshot":str(dirs[-1]) if dirs else None,"games":rows}
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print("MARKET_DELTA",len(rows),"previous",bool(prev))
if __name__=="__main__":main()
