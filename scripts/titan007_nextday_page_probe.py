#!/usr/bin/env python3
"""Inspect official Titan007 'next day schedule' entrypoint and script data calls.

Only prints selected endpoint/script names and small relevant JS code fragments.
Never writes scraped data, never assumes a source is approved unless robots allows it.
"""
import html.parser,re,urllib.parse,urllib.request,urllib.robotparser
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import titan007_join_daily as src
import titan007_bf_snapshot as odds

URLS=[
"https://bf.titan007.com/NBA_SC.aspx?type=sc",
"https://lq3.titan007.com/nba.htm",
"https://bf.titan007.com/NBA_SC.aspx",
]
class Tags(html.parser.HTMLParser):
 def __init__(self):
  super().__init__();self.scripts=[];self.links=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=="script" and "src" in a:self.scripts.append(a["src"])
  if tag=="a" and "href" in a:self.links.append((a.get("href"),a.get("title","")))
def fetch(url,limit=800_000):
 req=urllib.request.Request(url,headers={"User-Agent":odds.UA})
 robot_url=urllib.parse.urlsplit(url)
 robots=f"{robot_url.scheme}://{robot_url.netloc}/robots.txt"
 try:
  raw=urllib.request.urlopen(urllib.request.Request(robots,headers={"User-Agent":odds.UA}),timeout=12).read(150000)
  p=urllib.robotparser.RobotFileParser();p.parse(raw.decode("utf-8","replace").splitlines())
  if not p.can_fetch(odds.UA,url):return None,"ROBOTS_DISALLOWED"
 except Exception as e:return None,"ROBOTS_UNAVAILABLE_"+type(e).__name__
 try:
  with urllib.request.urlopen(req,timeout=15) as r:
   body=r.read(limit+1)
  if len(body)>limit:return None,"OVER_LIMIT"
  return body.decode("gb18030","replace"),None
 except Exception as e:return None,type(e).__name__+":"+str(e)[:120]
def run():
 for url in URLS:
  data,err=fetch(url)
  print("PAGE",url,"ERROR",err,"SIZE",len(data or ""))
  if not data:continue
  p=Tags();p.feed(data)
  print("SCRIPTS",p.scripts[:90])
  print("LINKS",p.links[:40])
  for needle in ("tomorrow","next","GetMatch","MatchData","ScoreData","date","DataBsk","NBA_SC","sbOdds","ascx","ajax"):
   poslist=[m.start() for m in list(re.finditer(re.escape(needle),data,re.I))[:6]]
   for pos in poslist:
    print("MATCH",needle,re.sub(r"\\s+"," ",data[max(0,pos-95):pos+175])[:280])
  scripts=[urllib.parse.urljoin(url,x) for x in p.scripts]
  for script in scripts:
   if not any(z in script.lower() for z in ("nba","live","score","schedule","default","sc.","common","basket")):continue
   if not urllib.parse.urlsplit(script).hostname.endswith("titan007.com"):continue
   d,e=fetch(script,limit=700_000)
   print("SCRIPT",script,"ERROR",e,"SIZE",len(d or ""))
   if not d:continue
   for needle in ("tomorrow","nex","today.xml","NBA_SC","oddsData","Date","ajax","XML","bsk","schedule"):
    occ=list(re.finditer(re.escape(needle),d,re.I))[:4]
    for m in occ:
     print("SNIPPET",needle,re.sub(r"\\s+"," ",d[max(0,m.start()-105):m.start()+170])[:280])
if __name__=="__main__":run()
