#!/usr/bin/env python3
import argparse,json,os,urllib.parse,urllib.request
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--date",required=True); p.add_argument("--out",required=True); a=p.parse_args()
key=os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or os.getenv("ODD")
if not key: raise SystemExit("NO_ODDS_API_KEY_CONFIGURED")
q=urllib.parse.urlencode({"apiKey":key,"regions":"us","markets":"h2h,spreads,totals","oddsFormat":"decimal","date":a.date})
url="https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds/?"+q
req=urllib.request.Request(url,headers={"User-Agent":"mcp-sports-hub-historical-probe/1.0"})
with urllib.request.urlopen(req,timeout=30) as r:
    body=r.read().decode(); headers={k.lower():v for k,v in r.headers.items()}
    obj=json.loads(body)
Path(a.out).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
print(json.dumps({"out":a.out,"events":len(obj.get("data",[])),"timestamp":obj.get("timestamp"),"previous_timestamp":obj.get("previous_timestamp"),"quota":{"requests_remaining":headers.get("x-requests-remaining"),"requests_used":headers.get("x-requests-used")}},ensure_ascii=False))
