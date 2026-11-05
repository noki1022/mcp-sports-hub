#!/usr/bin/env python3
"""Inspect actual public 007 mobile pre-match analysis HTML without JS execution."""
from __future__ import annotations
import hashlib
import json
import re
import urllib.request
URL="https://m.titan007.com/analy/Analysis/3075305.htm"
req=urllib.request.Request(URL,headers={"User-Agent":"Mozilla/5.0 (compatible; PublicFootballAnalysisAudit/1.0)"})
with urllib.request.urlopen(req,timeout=20) as res:
    if res.status!=200 or res.url!=URL:raise RuntimeError("BAD_ANALYSIS_RESPONSE")
    raw=res.read(750001)
    if len(raw)>750000:raise RuntimeError("TOO_LARGE")
    page=raw.decode("utf-8-sig","replace")
print("FOOTBALL_007_MOBILE_ANALYSIS_META",json.dumps({
    "url":URL,"sha256":hashlib.sha256(raw).hexdigest(),
    "bytes":len(raw),"tables":page.lower().count("<table"),
    "rows":page.lower().count("<tr"),"injury_tokens":page.count("伤停"),
    "h2h_tokens":page.count("对赛往绩"),"recent_tokens":page.count("近期战绩")},ensure_ascii=False))
candidates=re.findall(r"""(?:[A-Za-z0-9_./-]{3,90}\.(?:ashx|aspx|json|js|htm)(?:\?[^"'<>\s]{0,80})?)""",page,flags=re.I)
print("FOOTBALL_007_MOBILE_ENDPOINTS",json.dumps(list(dict.fromkeys(x for x in candidates if any(k in x.lower() for k in ("analysis","analy","injur","history","near","stat","data","team","detail"))))[:100],ensure_ascii=False))
for token in ("AnalysisObj", "GetAgainst", "getAgainst", "GetNear", "getNear", "getInjury", "GetInjury", "MatchChange(", "nearMatchDiv", "Injury", "againstDiv", "BomHelper.ajax", "ajaxGet(", "getData(", "loadAnalysis"):
    i=page.find(token)
    if i>=0:
        print("FOOTBALL_007_MOBILE_SCRIPT_CONTEXT",token,json.dumps(re.sub(r"\s+"," ",page[max(0,i-200):i+1000]),ensure_ascii=False))
for term in ("对赛往绩","近期战绩","伤停情况","伤病","停赛","数据对比","历史交锋","主队近期","客队近期"):
    i=page.rfind(term)
    if i>=0:
        snippet=re.sub(r"\s+"," ",page[max(0,i-650):i+2600])
        print("FOOTBALL_007_MOBILE_ANALYSIS_CONTEXT",term,json.dumps(snippet,ensure_ascii=False))

for script_url in ("https://m.titan007.com/script/DetailLive.js?ver=9",
                   "https://m.titan007.com/script/live.js?ver=4"):
    try:
        request=urllib.request.Request(script_url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(request,timeout=15) as response:
            js=response.read(450001).decode("utf-8","replace")
        for token in ("against", "Injury", "injury", "hn", "nearMatch", "AnalysisObj", ".ashx", ".aspx", "getMatchData", "getNear"):
            i=js.find(token)
            if i>=0:
                print("FOOTBALL_007_MOBILE_LINKED_JS",script_url,token,json.dumps(re.sub(r"\s+"," ",js[max(0,i-180):i+700]),ensure_ascii=False))
    except Exception as e:print("FOOTBALL_007_MOBILE_LINKED_JS_ERROR",script_url,type(e).__name__)
