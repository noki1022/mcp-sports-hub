#!/usr/bin/env python3
"""Read-only forensic audit of Titan007 public multi-company Asian odds.

The current verified endpoints come from Titan007 public pages and the
repository's 007 match links. This audit DOES NOT assume a guessed AsianOdds
address is valid: candidate routes are marked unverified until HTTP+payload+
match ID/price schema are confirmed. No model predictions or basketball code.

Access is bounded and ordinary. No login, bypass, proxy or anti-bot evasion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
import argparse
import gzip
import hashlib
import json
import re
import time
import urllib.request

FIXTURE="3075305"   # real 007 fixture ID previously verified against JC snapshot
PAGES={
 "asian_history_index":"https://vip.titan007.com/history/odds.aspx",
 "asian_company_detail_public":"https://vip.titan007.com/changeDetail/handicap.aspx?companyid=8&id=2995798&l=1",
 "mobile_fixture_analysis":f"https://m.titan007.com/analy/Analysis/{FIXTURE}.htm",
 "mobile_match_asian_index":f"https://m.titan007.com/asian/{FIXTURE}.htm",
 "mobile_match_odds_comparison":f"https://m.titan007.com/Analy/OddsComp.aspx?scheid={FIXTURE}",
 "mobile_match_odds_detail":f"https://m.titan007.com/Analy/OddsDetail.aspx?scheid={FIXTURE}",
 "desktop_fixture_analysis":f"https://zq.titan007.com/analysis/{FIXTURE}cn.htm",
 "asian_match_candidate":f"https://vip.titan007.com/AsianOdds_n.aspx?id={FIXTURE}",
 "euro_match_public":"https://1x2.titan007.com/Oddslist/3102540_2.htm",
}
# Crawl only known public same-Titan007 document/script URLs and discovered
# href targets, up to strict limits. Distinguish observed from candidates.
KEYS=("asian","handicap","companyid","company","changeDetail","odds","yc",
      "盘","亚让","亚盘","水位","初盘","即","公司","早盘")
MAX_PAGE=900_000
MAX_SCRIPT=320_000

class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href=[];self.scripts=[];self.inline=[]
        self._on=False;self._buf=[]
        self._title=False;self._title_text=[]
        self.rows=[];self._row=None;self._cell=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="a" and a.get("href"):
            self.href.append({"href":a["href"],"onclick":a.get("onclick",""),"title":a.get("title","")})
        if tag=="script":
            self._on=True;self._buf=[]
            if a.get("src"):self.scripts.append(a["src"])
        if tag=="title":self._title=True
        if tag=="tr":self._row={"id":a.get("id"),"class":a.get("class"),"cells":[]}
        if tag in ("td","th") and self._row is not None:
            self._cell={"text":[],"attrs":{k:v for k,v in a.items()
                if k in ("id","class","data-id","title","name")}}
    def handle_data(self,v):
        if self._on:self._buf.append(v)
        if self._title:self._title_text.append(v)
        if self._cell is not None:self._cell["text"].append(v)
    def handle_endtag(self,tag):
        if tag=="script":
            if self._buf:self.inline.append("".join(self._buf))
            self._on=False
        if tag=="title":self._title=False
        if tag in ("td","th") and self._cell is not None:
            self._cell["text"]=" ".join(" ".join(self._cell["text"]).split())[:100]
            self._row["cells"].append(self._cell)
            self._cell=None
        if tag=="tr" and self._row is not None:
            self.rows.append(self._row);self._row=None
    @property
    def title(self):
        return " ".join(" ".join(self._title_text).split())[:140]

def domain_ok(url):
    u=urlparse(url)
    host=(u.hostname or "").lower()
    return u.scheme=="https" and (host=="titan007.com" or host.endswith(".titan007.com"))

def fetch(url,limit):
    if not domain_ok(url):raise ValueError("OUTSIDE_007_DOMAIN")
    headers={
      "User-Agent":"Mozilla/5.0 (compatible; ReadOnlyFootballResearch/1.0)",
      "Accept":"text/html,application/javascript,text/plain,*/*;q=0.8",
      "Accept-Language":"zh-CN,zh;q=0.8",
    }
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=12) as res:
            if not domain_ok(res.url):raise ValueError("EXTERNAL_REDIRECT_BLOCKED")
            data=res.read(limit+1)
            if len(data)>limit:raise ValueError("RESPONSE_EXCEEDS_BOUND")
            return {"status":res.status,"url":res.url,
                    "content_type":res.headers.get("Content-Type",""),
                    "raw":data,"sha256":hashlib.sha256(data).hexdigest()}
    except HTTPError as exc:
        return {"status":exc.code,"error":"HTTP_"+str(exc.code)}
    except (URLError, OSError, ValueError, TimeoutError) as exc:
        return {"status":None,"error":type(exc).__name__+":"+str(exc)[:140]}

def decode(data):
    for enc in ("utf-8-sig","gb18030"):
        try:return data.decode(enc)
        except UnicodeError:pass
    return data.decode("utf-8","replace")

def hints(text,limit=45):
    candidates=re.findall(r'''(?:(?:https?:)?//[\w./?=&%-]{8,160}|[/\w.-]{3,120}\.(?:aspx|ashx|js|txt|json|xml)(?:\?[^"'<>\s]{0,100})?)''',text,re.I)
    return list(dict.fromkeys(x for x in candidates if any(k in x.lower() for k in
             ("asian","odd","company","change","handicap","data","match"))))[:limit]

def inspect(name,url,directory):
    result={"name":name,"requested_url":url,"source_status":"PAGE_AUDIT_ONLY_NOT_ACCEPTED_AS_ODDS"}
    a=fetch(url,MAX_PAGE)
    result.update(http=a["status"],error=a.get("error"))
    if "raw" not in a:return result
    raw=a["raw"]
    final=a["url"]
    destination=directory/(name+".html.gz")
    destination.write_bytes(gzip.compress(raw,mtime=0))
    body=decode(raw)
    parsed=Parser()
    parsed.feed(body)
    links=[]
    for d in parsed.href:
        l=urljoin(final,d["href"])
        if not domain_ok(l):continue
        if any(k in (l+" "+d.get("onclick","")).lower() for k in KEYS):
            links.append({"url":l,"onclick":d.get("onclick","")[:160],
                          "title":d.get("title","")[:70]})
    script_urls=list(dict.fromkeys(urljoin(final,x) for x in parsed.scripts
                      if domain_ok(urljoin(final,x))))[:35]
    rows=[]
    for i,row in enumerate(parsed.rows):
        vals=[c["text"] for c in row["cells"]]
        joined=" ".join(vals).lower()
        if (any(k in joined for k in ("皇冠","澳门","365","立博","盘","水","半球","平手"))
            or len(vals) in (5,6,7,8,9,10,11)):
            rows.append({"row_index":i,"row_id":row["id"],"cell_count":len(vals),
                         "cells":vals[:12]})
        if len(rows)>=14:break
    result.update(http_status=a["status"],final_url=final,sha256=a["sha256"],
                  bytes=len(raw),title=parsed.title,
                  keys={k:body.lower().count(k.lower()) for k in
                        ("亚盘","亚洲","亚让","初盘","即盘","公司","盘口","水位","Crown","365","changeDetail","AsianOdds")},
                  script_urls=script_urls,site_links=links[:50],
                  endpoint_hints=hints(body),script_inline_hints=[
                    {"n":i,"len":len(s),"refs":hints(s,15)} for i,s in enumerate(parsed.inline)
                    if len(s)>100 and hints(s,15)][:15],
                  row_shapes=rows)
    # Dig into up to 5 actual linked site scripts, preserving host allowlist
    # and checking only endpoints and relevant text snippets; no blind crawl.
    follow=[]
    for link in script_urls:
        if not link.lower().split("?")[0].endswith(".js"):continue
        if not any(k in link.lower() for k in ("odds","asian","data","match","detail","common","ajax")):
            continue
        if len(follow)>=5:break
        resp=fetch(link,MAX_SCRIPT)
        record={"url":link,"status":resp["status"],"error":resp.get("error")}
        if "raw" in resp:
            js=decode(resp["raw"])
            record["sha256"]=resp["sha256"]
            record["bytes"]=len(resp["raw"])
            record["endpoint_hints"]=hints(js,40)
            context=[]
            for key in ("companyID","companyid","AsianOdds","changeDetail","handicap",
                        "var company","oddsData","getData","parseOdds","亚盘","初盘"):
                ix=js.lower().find(key.lower())
                if ix>=0:
                    context.append({"term":key,"sample":re.sub(r"\s+"," ",
                               js[max(0,ix-140):ix+400])})
            record["contexts"]=context[:12]
        follow.append(record)
    result["same_site_linked_script_audit"]=follow
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="football-output/multi-company-source-audit")
    args=p.parse_args()
    directory=Path(args.out);directory.mkdir(parents=True,exist_ok=True)
    report={"audited_at_utc":datetime.now(timezone.utc).isoformat(),
            "user_goal":"actual Asian multi-company open/current/history from Titan007",
            "verified_market_data_collected":False,
            "pages":[]}
    for name,url in PAGES.items():
        row=inspect(name,url,directory)
        report["pages"].append(row)
        print("FOOTBALL_007_ASIAN_SOURCE",json.dumps(row,ensure_ascii=False))
        time.sleep(.3)
    (directory/"source_audit.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":main()
