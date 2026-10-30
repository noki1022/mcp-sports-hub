#!/usr/bin/env python3
"""Locate NBA season fixture endpoint on 007 league schedule (no storage)."""
import re,sys,html.parser,urllib.parse
sys.path.insert(0,__import__("os").path.dirname(__file__))
from titan007_nextday_page_probe import fetch,Tags
urls=["https://nba.titan007.com/cn/Normal.aspx?SclassID=1",
"https://nba.titan007.com/cn/Normal.aspx?SclassID=1&Season=2026-2027"]
for u in urls:
 s,e=fetch(u,1000000)
 print("PAGE",u,"ERROR",e,"SIZE",len(s or ""))
 if not s:continue
 t=Tags();t.feed(s)
 print("SCRIPTS",t.scripts[:45])
 for term in ("2026-2027","2026/10/31","2026-10-31","Schedule","matchInfo","matchdata","Ajax","getSchedule","GetCalendar","赛程","日程","/json","nba.js","normal.aspx"):
  m=list(re.finditer(re.escape(term),s,re.I));print("TERM",term,"COUNT",len(m))
  for v in m[:5]:print("FRAGMENT",re.sub(r"\s+"," ",s[max(0,v.start()-130):v.start()+210])[:340])
 for p in t.scripts:
  v=urllib.parse.urljoin(u,p)
  if not (urllib.parse.urlsplit(v).hostname or "").endswith("titan007.com"):continue
  if not any(z in v.lower() for z in ("normal","nba","season","common","calendar","league","schedule")):continue
  x,er=fetch(v,900000)
  print("SCRIPT",v,"ERROR",er,"SIZE",len(x or ""))
  if not x:continue
  for term in ("Schedule","ajax","Data","aspx","season","league","match"):
   matches=list(re.finditer(re.escape(term),x,re.I))[:8]
   for m in matches:
    sample=re.sub(r"\s+"," ",x[max(0,m.start()-125):m.start()+185])
    print("JS",term,sample[:310])
