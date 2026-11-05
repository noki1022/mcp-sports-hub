#!/usr/bin/env python3
"""Inspect visible 007 CP total-goal row structure with one read-only GET."""
import json,re
from html import unescape
from html.parser import HTMLParser
from urllib.request import Request,urlopen

URL="https://cp.titan007.com/buy/jingcai.aspx?typeID=103&oddstype=2"
class RowReader(HTMLParser):
 def __init__(self):
  super().__init__();self.row=None;self.rows=[];self.depth=0;self.cells=[];self.cell=None
 def handle_starttag(self,tag,attrs):
  if tag=="tr":
   self.row={"attrs":dict(attrs),"cells":[]};self.cells=[];self.depth+=1
  if tag in ("td","th") and self.row is not None:
   self.cell={"attrs":dict(attrs),"text":[]}
  if tag=="input" and self.cell is not None:
   self.cell.setdefault("inputs",[]).append(dict(attrs))
  if tag=="a" and self.cell is not None:
   self.cell.setdefault("anchors",[]).append(dict(attrs))
 def handle_data(self,value):
  if self.cell is not None:self.cell["text"].append(value)
 def handle_endtag(self,tag):
  if tag in ("td","th") and self.cell is not None:
   self.cell["text"]=" ".join(" ".join(self.cell["text"]).split())
   self.row["cells"].append(self.cell);self.cell=None
  if tag=="tr" and self.row is not None:
   self.rows.append(self.row);self.row=None;self.depth-=1

req=Request(URL,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
 "Accept-Language":"zh-CN,zh;q=0.9","Referer":"https://cp.titan007.com/"})
with urlopen(req,timeout=18) as r:
 raw=r.read(850001)
 if len(raw)>850000:raise RuntimeError("CP_HTML_TOO_LARGE")
page=raw.decode("utf-8-sig","replace")
print("CP_TTG_LAYOUT_META",json.dumps({"len":len(page),"anchor_007_match_id":page.count("3075305"),
 "spid_count":page.lower().count("spid"),"seven_plus_count":page.count("7+球"),
 "tr_count":page.lower().count("<tr"),"td_count":page.lower().count("<td")},ensure_ascii=False))
for keyword in ("3075305","3069064","7+球","6球","JcSp.aspx","MatchID","spid","matchid","周四","001","TypeID=103"):
 for n,m in enumerate(re.finditer(re.escape(keyword),page,re.I)):
  if n>=2:break
  i=m.start();s=page[max(0,i-450):i+1050]
  print("CP_TTG_LAYOUT_CONTEXT",keyword,n,json.dumps(s,ensure_ascii=False))
parser=RowReader();parser.feed(page)
print("CP_TTG_ROW_COUNT",len(parser.rows))
for i,row in enumerate(parser.rows):
 cells=row["cells"]
 if not cells:continue
 texts=[x["text"] for x in cells]
 joined=" ".join(texts)
 if any(k in joined for k in ("水晶宫","布斯巴达","町田泽维","0球","7+球","8球")):
  print("CP_TTG_ROW",i,json.dumps({"attrs":row["attrs"],"count":len(cells),
    "cells":[{"text":c["text"][:75],"attrs":c["attrs"],"inputs":c.get("inputs",[])[:2],
       "anchors":c.get("anchors",[])[:2]} for c in cells[:27]]},ensure_ascii=False))
