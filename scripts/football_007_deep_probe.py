#!/usr/bin/env python3
"""Bounded forensic exploration of public 007 football analysis data routing."""
from html.parser import HTMLParser
from urllib.parse import urljoin,urlparse
import urllib.request,re,json,hashlib

URL="https://m.titan007.com/analy/Analysis/3075305.htm"
KEYS=("against","injury","near","analysis","h2h","vs","state","lastmatch","matchhistory","history","getdata","dataurl","async","ajax","lineup","headhome","last5","score")
class Html(HTMLParser):
 def __init__(self):super().__init__();self.scripts=[];self.inscript=False;self.buf=[];self.inline=[]
 def handle_starttag(self,tag,attrs):
  if tag=="script":
   d=dict(attrs)
   if d.get("src"):self.scripts.append(d["src"])
   self.inscript=True;self.buf=[]
 def handle_data(self,v):
  if self.inscript:self.buf.append(v)
 def handle_endtag(self,tag):
  if tag=="script":
   if self.buf:self.inline.append("".join(self.buf))
   self.inscript=False
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,application/javascript,*/*","Referer":URL})
 with urllib.request.urlopen(req,timeout=15) as r:
  raw=r.read(900001)
  if len(raw)>900000:raise ValueError("TOO_LARGE")
  if (urlparse(r.url).hostname or "").endswith("titan007.com") is False:raise ValueError("EXTERNAL_REDIRECT")
  return raw.decode("utf-8","replace")
html=fetch(URL)
parser=Html();parser.feed(html)
print("DEEPMETA",json.dumps({"html_chars":len(html),"scripts":len(parser.scripts),
 "inline":len(parser.inline),"inline_lengths":[len(x) for x in parser.inline],
 "js_urls":parser.scripts},ensure_ascii=False))
for i,x in enumerate(parser.inline):
 if len(x)<50:continue
 endpoints=re.findall(r"""[A-Za-z0-9_./-]{2,120}\.(?:ashx|aspx|json|js|htm)(?:\?[^"'<>\s]{0,100})?""",x,flags=re.I)
 if endpoints:print("INLINE_ENDPOINTS",i,json.dumps(list(dict.fromkeys(endpoints))[:70],ensure_ascii=False))
 for k in ("GetAnalysis","getAnalysis","analysisObj","AnalysisObj","against","nearMatch","Injury","injuryData","injury","Ajax","ajax","/analy/","/ajax/","loadData"):
  st=0
  for n in range(2):
   at=x.lower().find(k.lower(),st)
   if at<0:break
   snippet=re.sub(r"\s+"," ",x[max(0,at-180):at+1100])
   print("INLINE_CTX",i,k,n,json.dumps(snippet,ensure_ascii=False))
   st=at+len(k)
for u in parser.scripts:
 if "titan007.com" not in urljoin(URL,u):continue
 if not any(z in u.lower() for z in ("analysis","analy","detail","live","data","common")):continue
 full=urljoin(URL,u)
 try:
  j=fetch(full)
  endpoints=re.findall(r"""[A-Za-z0-9_./-]{2,120}\.(?:ashx|aspx|json|js|htm)(?:\?[^"'<>\s]{0,100})?""",j,flags=re.I)
  targets=[e for e in dict.fromkeys(endpoints) if any(t in e.lower() for t in ("near","anal","stat","injur","team","history","match","data","all"))]
  print("LINKED_META",full,len(j),hashlib.sha256(j.encode()).hexdigest(),json.dumps(targets[:80],ensure_ascii=False))
  for k in ("against","nearMatch","injury","AnalysisObj","matchData","getNear","getVs","getInjury","ajaxGet"):
   at=j.lower().find(k.lower())
   if at>=0:print("LINKED_CTX",full,k,json.dumps(re.sub(r"\s+"," ",j[max(0,at-200):at+1000]),ensure_ascii=False))
 except Exception as ex:print("LINKED_ERR",full,type(ex).__name__,str(ex)[:100])
