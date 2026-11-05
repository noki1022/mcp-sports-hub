#!/usr/bin/env python3
"""Read-only 007 football form/H2H/injury source audit.

All candidate URLs below were observed as actual links in Titan007 pages,
not invented private APIs. This inspects public HTTP/HTML/JS and archives
raw evidence; NEVER infers injury lists from headings or empty containers.
"""
import gzip,hashlib,json,re,urllib.request,urllib.error,sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse,urljoin

MATCH="3075305"
URLS={
 "desktop_analysis":f"https://zq.titan007.com/analysis/{MATCH}cn.htm",
 "mobile_analysis":f"https://m.titan007.com/analy/Analysis/{MATCH}.htm",
 "mobile_news":f"https://m.titan007.com/analy/qingbao/{MATCH}.htm",
 "mobile_lineup":f"https://m.titan007.com/analy/Lineup/{MATCH}.htm",
 "mobile_member":f"https://m.titan007.com/analy/menber/{MATCH}.htm",
 "cp_match_detail_script":"https://cp.titan007.com/info/match/data/detail.js",
}
class Html(HTMLParser):
 def __init__(self):
  super().__init__();self.scripts=[];self.inline=[];self._inline=False;self.buf=[];self.embedded=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=="script":
   self._inline=True;self.buf=[]
   if a.get("src"):self.scripts.append(a["src"])
  if tag in ("iframe","link") and a.get("src"):self.embedded.append(a["src"])
 def handle_data(self,v):
  if self._inline:self.buf.append(v)
 def handle_endtag(self,tag):
  if tag=="script":
   if self.buf:self.inline.append("".join(self.buf))
   self._inline=False
def request(url):
 req=urllib.request.Request(url,headers={
   "User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
   "Accept":"text/html,application/javascript,*/*;q=0.7","Accept-Language":"zh-CN,zh;q=0.9",
   "Referer":"https://m.titan007.com/"})
 try:
  with urllib.request.urlopen(req,timeout=11) as r:
   host=(urlparse(r.url).hostname or "").lower()
   if host!="titan007.com" and not host.endswith(".titan007.com"):raise ValueError("NOT_007")
   raw=r.read(850001)
   if len(raw)>850000:raise ValueError("TOO_LARGE")
   return {"status":r.status,"url":r.url,"raw":raw}
 except urllib.error.HTTPError as e:return {"status":e.code,"error":f"HTTP_{e.code}"}
 except (urllib.error.URLError,OSError,ValueError) as e:
  return {"status":None,"error":type(e).__name__+":"+str(e)[:110]}
def audit(out):
 d=Path(out);d.mkdir(parents=True,exist_ok=True)
 report={}
 tokens=("对赛往绩","近期战绩","伤停","伤病","缺阵","停赛","阵容","首发","球员","近5","against","injury","near","historic","h2h")
 for name,url in URLS.items():
  got=request(url);info={"url":url,"http":got["status"],"error":got.get("error")}
  if "raw" in got:
   raw=got["raw"];(d/f"{name}.html.gz").write_bytes(gzip.compress(raw,mtime=0))
   page=raw.decode("utf-8-sig","replace")
   html=Html()
   try:html.feed(page)
   except Exception as e:info["html_parser_warning"]=str(e)[:100]
   info.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
      script_urls=[urljoin(url,x) for x in html.scripts][:60],
      inline_count=len(html.inline),inline_lengths=[len(x) for x in html.inline[:80]],
      mention_count={k:page.lower().count(k.lower()) for k in tokens},
      empty_placeholders={k:page.count(k) for k in
       ('id="against"','id="hn"','id="an"','id="Injury"')})
   hints=[]
   sources=[page]+html.inline
   for body in sources:
    candidates=re.findall(r'''[A-Za-z0-9_/.\-]{2,140}\.(?:ashx|aspx|json|txt|xml|js)(?:\?[^"'<> \t\r\n]{0,80})?''',body,flags=re.I)
    for u in candidates:
     if any(k in u.lower() for k in ("analy","analysis","match","team","near","injur","hist","detail","data","lineup","member")):
      hints.append(u[:180])
   info["endpoint_hints"]=list(dict.fromkeys(hints))[:80]
   largest=max(html.inline,key=len,default="")
   if len(largest)>50000:
    m=re.search(r"var\s+jsonData\s*=\s*",largest)
    if m:
     try:
      structured,offset=json.JSONDecoder().raw_decode(largest[m.end():].lstrip())
      info["embedded_json_parsed"]=True
      info["embedded_json_id"]=structured.get("scheduleId")
      info["embedded_top_keys"]=list(structured.keys())[:60]
      for side in ("homeMatches","awayMatches"):
       data=(structured.get("nearMatches") or {}).get(side) or {}
       info.setdefault("recent_schema",{})[side]={
        "keys":list(data.keys()),
        "team_id":data.get("teamId"),
        "count":len(data.get("matches") or []),
        "sample_matches":(data.get("matches") or [])[:1]}
      for side in ("homeInjury","awayInjury"):
       group=(structured.get("injury") or {}).get(side) or []
       info.setdefault("injury_schema",{})[side]={"count":len(group),"sample":group[:1]}
      vs=structured.get("vsMatches")
      info["h2h_schema"]={"state":"NULL" if vs is None else "PRESENT",
                           "keys":list(vs.keys()) if isinstance(vs,dict) else [],
                           "sample":str(vs)[:1200]}
     except (ValueError,TypeError) as exc:
      info["embedded_json_parsed"]=False
      info["embedded_json_error"]=str(exc)[:100]
    info["largest_inline_prefix"]=largest[:1900]
    info["largest_inline_suffix"]=largest[-1100:]
    info["largest_inline_length"]=len(largest)
    for token in ('"nearMatches"','"vsMatches"','"injury"','"homeInjury"','"homeMatches"','"awayMatches"'):
     pos=largest.find(token)
     if pos>=0:
      info.setdefault("largest_inline_data_keys",{})[token]={"offset":pos,
          "before":largest[max(0,pos-700):pos+150]}
   for target in ("AnalysisObj","analysisData","nearMatchDiv","againstDiv","injuryData","Injury","NearMatch","getNear","getAgainst","getInjury","XMLHttpRequest","ajax","dataList","api/"):
    entries=[]
    for segment in html.inline:
     at=segment.lower().find(target.lower())
     if at>=0:
      entries.append(re.sub(r"\s+"," ",segment[max(0,at-120):at+450]))
    if entries:info.setdefault("inline_contexts",{})[target]=entries[:3]
  report[name]=info
  print("FOOTBALL_ANALYSIS_SOURCE",json.dumps({"source":name,**info},ensure_ascii=False))
 (d/"source_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 return report
if __name__=="__main__":
 audit(sys.argv[1] if len(sys.argv)>1 else "football-output/analysis-source-audit")
