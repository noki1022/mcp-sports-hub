#!/usr/bin/env python3
"""Verify Titan007 date-source schema, target game IDs and market coverage."""
import sys,re,urllib.parse,collections
sys.path.insert(0,__import__("os").path.dirname(__file__))
from titan007_nextday_page_probe import fetch
from titan007_join_daily import identify
from xml.etree import ElementTree as ET
B="https://bf.titan007.com/"
for dt in ("2026-10-30","2026-10-31"):
 query=urllib.parse.urlencode({"date":dt,"h":"12","m":"00","s":"1"})
 scores,err=fetch(B+"nba_date.aspx?"+query,500_000)
 odds,err2=fetch(B+"nba_Oddsdata.aspx?"+urllib.parse.urlencode({"date":dt,"id":"3","h":"12","m":"00"}),500_000)
 print("REQUEST",dt,"score_error",err,"odds_error",err2)
 if not scores or not odds:continue
 # feed may state gb2312 but include valid UTF8 or other, see parsing check
 try:identity,rejected=identify(scores.encode("gb18030"))
 except Exception as e:print("PARSE_SCORE_ERR",str(e));continue
 try:
  root=ET.fromstring(odds)
  markets={}
  for node in root.findall(".//match/m"):
   a=(node.text or "").split(",")
   if len(a)>=7 and a[0].isdigit():markets[a[0]]=a
 except Exception as e:print("PARSE_ODDS_ERR",str(e));continue
 ids={k for k,x in identity.items() if x["display_date"]==dt and x["league"] in ("NBA","CBA")}
 shared=ids&markets.keys()
 print("SCHEMA",dt,"TOTAL_SCORES",len(identity),"REJECT",len(rejected),
       "SCORE_DATES",dict(collections.Counter(x["display_date"] for x in identity.values())),
       "TARGET_NBA_CBA",len(ids),"ODDS",len(markets),"MATCHED",len(shared))
 print("TARGET_NAMES",[(k,identity[k]["league"],identity[k]["home_team"],identity[k]["away_team"],markets.get(k)) for k in sorted(ids)[:12]])
 print("MATCHED_COUNTS",dict(collections.Counter(identity[k]["league"] for k in shared)))
