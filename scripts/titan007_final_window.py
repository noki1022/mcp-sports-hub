#!/usr/bin/env python3
"""Select only games 45–75 minutes before the 007 displayed tip time."""
import argparse,json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Shanghai")
def select(source,now=None,low=45,high=75):
    now=now or datetime.now(TZ)
    out=[]; rejected=[]
    for game in source.get("nba_cba_games",[]):
        try:
            tip=datetime.fromisoformat(game["display_date"]+"T"+game["display_clock"]+":00").replace(tzinfo=TZ)
            minutes=(tip-now).total_seconds()/60
            if low<=minutes<=high: out.append({**game,"final_window_minutes_to_tip":round(minutes,2)})
        except (KeyError,TypeError,ValueError):
            rejected.append(game.get("game_id"))
    return {**source,"captured_at_utc":datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "final_window":True,"final_window_rule":{"min_minutes":low,"max_minutes":high,"timezone":"Asia/Shanghai","display_time_unverified":True},
            "nba_cba_games":out,"nba_cba_joined_for_date":len(out),"window_rejected_games":rejected}

def main():
    p=argparse.ArgumentParser();p.add_argument("--infile",required=True);p.add_argument("--outfile",required=True);p.add_argument("--now");a=p.parse_args()
    now=datetime.fromisoformat(a.now).replace(tzinfo=TZ) if a.now else None
    result=select(json.loads(Path(a.infile).read_text(encoding="utf-8")),now)
    Path(a.outfile).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"selected_games":len(result["nba_cba_games"]),"rejected_time_rows":len(result["window_rejected_games"]),"timezone":"Asia/Shanghai"},ensure_ascii=False))
if __name__=="__main__": main()
