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
for term in ("对赛往绩","近期战绩","伤停情况","伤病","停赛","数据对比","历史交锋","主队近期","客队近期"):
    i=page.find(term)
    if i>=0:
        snippet=re.sub(r"\s+"," ",page[max(0,i-350):i+1600])
        print("FOOTBALL_007_MOBILE_ANALYSIS_CONTEXT",term,json.dumps(snippet,ensure_ascii=False))
