#!/usr/bin/env python3
"""Diagnostic: compare NBA rows from consecutive 007 displayed date windows."""
import sys,collections
sys.path.insert(0,__import__("os").path.dirname(__file__))
from titan007_join_daily import dated_source
for day in ("2026-10-29","2026-10-30","2026-10-31","2026-11-01","2026-11-02"):
 try:
  ids,rej,markets=dated_source(day)
  marketids={x["game_id"] for x in markets}
  nba=[m for m in ids.values() if m["league"]=="NBA"]
  print("DAY",day,"SCORE",len(ids),"ODDS",len(marketids),"NBA",len(nba),"PAIRED",sum(x["game_id"] in marketids for x in nba))
  for g in nba[:16]:
   print("NBA_MATCH",g["game_id"],g["display_date"],g["display_clock"],g["home_team"],g["away_team"],g["game_id"] in marketids)
 except Exception as e:print("FAILED",day,str(e)[:200])
