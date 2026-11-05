#!/usr/bin/env python3
"""Audit only the actual 007 soccer JC public page/scripts. No guessed APIs."""
import hashlib
from html.parser import HTMLParser
import json
import re
import urllib.parse
import urllib.request

URLS=["https://jc.titan007.com/schedule.aspx","https://jc.titan007.com/index.aspx",
      "https://live.titan007.com/index2in1.aspx",
      "https://zq.titan007.com/analysis/3075305cn.htm"]
KEYS=("ajax","xml","json","live","schedule","jc","odds","spf","ttg","goal","score","data","match")
class P(HTMLParser):
 def __init__(self): super().__init__();self.scripts=[];self.links=[];self.inline=[];self.in_script=False;self.buffer=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=="script":
   self.in_script=True;self.buffer=[]
   if d.get("src"):self.scripts.append(d["src"])
  if tag=="a" and d.get("href"):self.links.append(d["href"])
 def handle_data(self,v):
  if self.in_script:self.buffer.append(v)
 def handle_endtag(self,tag):
  if tag=="script":
   if self.buffer:self.inline.append("".join(self.buffer))
   self.in_script=False

def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; ResearchSourceAudit/1.0)",
                                          "Accept":"text/html,application/javascript,*/*"})
 with urllib.request.urlopen(req,timeout=12) as res:
  if res.status!=200:raise ValueError(f"STATUS_{res.status}")
  final=res.url
  u=urllib.parse.urlparse(final)
  if not u.hostname or not (u.hostname=="titan007.com" or u.hostname.endswith(".titan007.com")):
   raise ValueError("NON_007_REDIRECT")
  raw=res.read(850001)
  if len(raw)>850000:raise ValueError("TOO_LARGE")
  encoding=res.headers.get_content_charset() or "gb18030"
 try: s=raw.decode(encoding)
 except (UnicodeError,LookupError):s=raw.decode("gb18030","replace")
 return s,hashlib.sha256(raw).hexdigest(),final

def inspect(url):
 out={"url":url}
 try:
  page,sha,final=fetch(url)
  parsed=P();parsed.feed(page)
  out.update(http="OK",sha256=sha,url_final=final,chars=len(page),
             script_urls=[urllib.parse.urljoin(final,s) for s in parsed.scripts][:30],
             live_words={x:page.lower().count(x) for x in ["竞彩足球","让球","进球数","暂无赛事","script"]})
  candidates=re.findall(r"""(?:(?:https?:)?//[^"'<>\s]{4,100}|[\w/.-]{4,100}\.(?:ashx|aspx|json|xml|js)(?:\?[^"'<>\s]{0,80})?)""",page,flags=re.I)
  out["page_url_candidates"]=list(dict.fromkeys(x for x in candidates if any(k in x.lower() for k in KEYS)))[:50]
  scripts=[]
  for link in out["script_urls"][:12]:
   host=urllib.parse.urlparse(link).hostname or ""
   if not (host=="titan007.com" or host.endswith(".titan007.com")):continue
   try:
    js,digest,actual=fetch(link)
    matches=re.findall(r"""(?:(?:https?:)?//[^"'<>\s]{4,100}|[\w/.-]{4,100}\.(?:ashx|aspx|json|xml)(?:\?[^"'<>\s]{0,80})?)""",js,flags=re.I)
    contexts=[]
    for keyword in ("oddsData.aspx","JcResult.aspx","oddsChange.aspx","LoadData","loadData","MatchData","matchData","var game","getData","getMatch"):
     i=js.find(keyword)
     if i>=0:contexts.append({"key":keyword,"snippet":js[max(0,i-300):i+500]})
    scripts.append({"url":actual,"sha256":digest,"length":len(js),"contexts":contexts[:9],"endpoint_hints":
                     list(dict.fromkeys(m for m in matches if any(k in m.lower() for k in KEYS)))[:30]})
   except Exception as e:scripts.append({"url":link,"error":type(e).__name__+":"+str(e)[:120]})
  out["scripts"]=scripts
  for js_url in out["script_urls"]:
   if "/js/football.js" in js_url or "/js/common.js" in js_url:
    try:
     body,_,_=fetch(js_url)
     keys=("function loadData()", "function OddsListInit(", "function ScheduleListInit(", "scheduleDay:", "scheduleDay =", "function getOddsData(", "function getData(")
     for key in keys:
      i=body.find(key)
      if i>=0:print("SOURCE_JS_DETAIL",js_url,key,repr(body[max(0,i-180):i+3000]))
    except Exception as e:print("SOURCE_JS_DETAIL_ERROR",type(e).__name__)
  for url in ("https://jc.titan007.com/xml/bf_jc.txt", "https://jc.titan007.com/xml/odds_jc.txt"):
   try:
    raw,digest,final=fetch(url)
    print("SOURCE_RAW_SAMPLE",json.dumps({"url":final,"sha256":digest,"length":len(raw),"sample":raw[:2400]},ensure_ascii=False))
   except Exception as e:print("SOURCE_RAW_ERROR",url,type(e).__name__,str(e)[:130])
  out["inline_context"]=[v[:1500] for v in parsed.inline[:5]]
  out["html_context"]=page[:1900]
  if "/analysis/" in url:
   out["analysis_keywords"]={}
   for word in ("近期战绩","历史交锋","对赛往绩","伤停","伤病","缺阵","球员","近期","往绩","recent","h2h","injury"):
    idx=page.lower().find(word.lower())
    if idx>=0:out["analysis_keywords"][word]=page[max(0,idx-300):idx+1000]
   out["table_count"]=page.lower().count("<table")
 except Exception as e:out.update(http="ERROR",error=type(e).__name__+":"+str(e)[:200])
 return out

if __name__=="__main__":
 print("FOOTBALL_007_PUBLIC_SOURCE_AUDIT")
 for url in URLS: print(json.dumps(inspect(url),ensure_ascii=False))
