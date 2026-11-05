#!/usr/bin/env python3
"""Discover 007 JC total-goals endpoints from site scripts, without guessing URLs."""
import re,json,urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin,urlparse
ROOT="https://jc.titan007.com/"
PAGES=[ROOT+"schedule.aspx",ROOT+"index.aspx"]
class Parser(HTMLParser):
 def __init__(self):super().__init__();self.scripts=[]
 def handle_starttag(self,tag,attrs):
  if tag=="script":
   src=dict(attrs).get("src")
   if src:self.scripts.append(src)
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,application/javascript,*/*","Referer":ROOT})
 with urllib.request.urlopen(req,timeout=12) as res:
  if not (urlparse(res.url).hostname or "").endswith("titan007.com"):raise ValueError("CROSS_DOMAIN")
  data=res.read(800001)
  if len(data)>800000:raise ValueError("TOO_LARGE")
  return data.decode("utf-8-sig","replace")
scripts=set()
for url in PAGES:
 try:
  html=fetch(url);p=Parser();p.feed(html)
  scripts.update(urljoin(url,s) for s in p.scripts if "titan007.com" in urljoin(url,s))
  print("JC_PAGE",url,len(html),len(p.scripts))
 except Exception as e:print("JC_PAGE_ERROR",url,type(e).__name__,str(e)[:90])
for url in sorted(scripts)[:24]:
 try:
  js=fetch(url)
  print("JC_SCRIPT",url,len(js))
  for token in ("总进球","进球数","总进球数","ttg","TotalGoals","totalGoal","goals","JcResult","oddsData","odds_jc","ajax","ashx","竞彩"):
   match=re.search(re.escape(token),js,re.I)
   if match:
    i=match.start()
    print("JC_JS_TOKEN",url,token,json.dumps(re.sub(r"\s+"," ",js[max(0,i-180):i+650]),ensure_ascii=False))
  endpoints=re.findall(r"""[A-Za-z0-9_./-]{2,120}\.(?:ashx|aspx|txt|json|xml)(?:\?[^"'<>\s]{0,80})?""",js,re.I)
  print("JC_JS_ENDPOINTS",url,json.dumps(list(dict.fromkeys(endpoints))[:70],ensure_ascii=False))
 except Exception as e:print("JC_SCRIPT_ERROR",url,type(e).__name__,str(e)[:100])
