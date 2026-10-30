#!/usr/bin/env python3
"""Probe official date-parameter schedule and odds routes from Titan007 JS.
Robots respected; output aggregate hints only; no raw record persisted.
"""
import re,sys,json,urllib.parse
sys.path.insert(0,__import__("os").path.dirname(__file__))
from titan007_nextday_page_probe import fetch
B="https://bf.titan007.com/"
js,e=fetch(B+"funcNba.js",200000)
if not js:raise RuntimeError("OFFICIAL_JS_UNAVAILABLE:"+str(e))
for term in ("_oddsUitl.getOnlyDate","nba_date.aspx?date=","nba_Oddsdata.aspx?date=","var companyid","companyID","function selectDate","function GetDate","function ChangeDate"):
 matches=list(re.finditer(re.escape(term),js,re.I))
 print("JS_TERM",term,"COUNT",len(matches))
 for m in matches[:3]:
  print("JS_CONTEXT",re.sub(r"\s+"," ",js[max(0,m.start()-250):m.start()+370])[:610])
params=[
 ("2026-10-31","2026-10-31"),("2026/10/31","2026/10/31"),("2026,10,31","2026,10,31"),
 ("2026-10-30","2026-10-30"),
]
for target,dt in params:
 for endpoint,more in (("nba_date.aspx",{"date":dt,"h":"12","m":"00","s":"0"}),
                       ("nba_Oddsdata.aspx",{"date":dt,"id":"3","h":"12","m":"00"})):
  url=B+endpoint+"?"+urllib.parse.urlencode(more)
  body,error=fetch(url,1000000)
  print("DATE_ENDPOINT",endpoint,"TARGET",target,"ERROR",error,"CHARS",len(body or ""),"PREFIX",re.sub(r"\s+"," ",(body or "")[:180]))
  if body:
   print("DATE_MATCHES",target,{"2026":body.count("2026"),"10月31日":body.count("10月31日"),"10/31":body.count("10/31"),"nba":len(re.findall(r"NBA",body,re.I)),"xml_c":bool(re.search(r"<c|<m|<h",body,re.I))})
