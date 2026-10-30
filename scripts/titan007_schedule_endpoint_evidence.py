#!/usr/bin/env python3
"""Pinpoint schedule data URL references in Titan007 public HTML/JS."""
from pathlib import Path
import re,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from titan007_nextday_page_probe import fetch
BASE="https://bf.titan007.com"
SITES=[BASE+"/NBA_SC.aspx?type=sc",BASE+"/funcNba.js","https://lq3.titan007.com/nba.htm","https://lq3.titan007.com/funcNba.js?ver=1"]
PATTERNS=[r"(?i).{0,120}(?:\.xml|\.aspx|\.ashx|\.json|\.js)(?:\?[^\"'<> ]*)?.{0,120}",
          r"(?i).{0,120}(?:getScheduleList|GetScheduleList|selectDate|calendar|nextDay|tomorrow|loadSchedule|sclassid|matchdata).{0,160}",
          r"(?i).{0,150}(?:dataFile|oddsFile|scoreFile|scheduleFile|xmlFile|dataUrl).{0,170}"]
for url in SITES:
 data,error=fetch(url,1_000_000)
 print("SOURCE",url,"ERROR",error,"BYTES",len(data or ""))
 if not data:continue
 for pattern in PATTERNS:
  hits=list(re.finditer(pattern,data,re.I))
  print("PATTERN_MATCH_COUNT",len(hits))
  for m in hits[:24]:
   sample=re.sub(r"\s+"," ",m.group(0))
   print("EVIDENCE",sample[:390])
