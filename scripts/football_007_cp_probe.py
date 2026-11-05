#!/usr/bin/env python3
"""Bounded CP Titan007 Jingcai market source diagnostic; read-only and auditable.

Observe actual site behavior before selecting a parser. Does NOT infer an
undocumented API or claim successful parsing from screenshots or page titles.
"""
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError, URLError
import hashlib, json, re, time, urllib.request, gzip, argparse

SITE="https://cp.titan007.com"
MARKETS={"HAD":101,"SCORE":102,"TTG":103,"HALF_FULL":104}
PARAM="oddstype=2"
MAX_HTML=850_000
MAX_SCRIPT=220_000
class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts=[];self.forms=[];self.inline=[];self._on=False;self._buffer=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="script":
            if a.get("src"):self.scripts.append(a["src"])
            self._on=True;self._buffer=[]
        if tag=="form":self.forms.append({k:v for k,v in a.items() if k in ("action","method","id")})
    def handle_data(self,data):
        if self._on:self._buffer.append(data)
    def handle_endtag(self,tag):
        if tag=="script":
            if self._buffer:self.inline.append("".join(self._buffer))
            self._on=False

def request(url,limit=MAX_HTML):
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept":"text/html,application/xhtml+xml,application/javascript,text/plain;q=0.9,*/*;q=0.7",
        "Accept-Language":"zh-CN,zh;q=0.9,en;q=0.5",
        "Referer":SITE+"/buy/jingcai.aspx?typeID=101&oddstype=2"})
    try:
        with urllib.request.urlopen(req,timeout=18) as r:
            final=r.url
            host=(urlparse(final).hostname or "").lower()
            if not (host=="titan007.com" or host.endswith(".titan007.com")):raise ValueError("NON_007_REDIRECT")
            raw=r.read(limit+1)
            if len(raw)>limit:raise ValueError("RESPONSE_TOO_LARGE")
            return {"http_status":r.status,"final_url":final,"content_type":r.headers.get("Content-Type",""),
                "data":raw,"sha256":hashlib.sha256(raw).hexdigest()}
    except HTTPError as exc:
        return {"http_status":exc.code,"error":"HTTP_ERROR_"+str(exc.code)}
    except (URLError,TimeoutError,OSError,ValueError) as exc:
        return {"http_status":None,"error":type(exc).__name__+":"+str(exc)[:140]}

def decode(raw):
    for encoding in ("utf-8-sig","gb18030"):
        try:return raw.decode(encoding)
        except UnicodeError:pass
    return raw.decode("utf-8","replace")

def audit(markets,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    results=[]
    for name,kind in markets.items():
        url=f"{SITE}/buy/jingcai.aspx?typeID={kind}&{PARAM}"
        response=request(url)
        row={"market":name,"typeID":kind,"requested_url":url,
             "http_status":response.get("http_status"),"error":response.get("error"),
             "final_url":response.get("final_url"),"sha256":response.get("sha256"),
             "content_type":response.get("content_type")}
        if "data" in response:
            raw=response["data"]
            (output/f"cp_{name.lower()}.html.gz").write_bytes(gzip.compress(raw,mtime=0))
            page=decode(raw)
            p=Parser();p.feed(page)
            row.update(bytes=len(raw),script_count=len(p.scripts),forms=p.forms[:12],
                page_title=(re.search(r"<title[^>]*>(.*?)</title>",page,re.I|re.S).group(1).strip()[:150]
                    if re.search(r"<title[^>]*>(.*?)</title>",page,re.I|re.S) else ""),
                text_signals={k:page.lower().count(k.lower()) for k in
                    ("进球数","总进球","7+球","胜平负","周四001","让球","jincai","postback")},
                scripts=[urljoin(url,s) for s in p.scripts][:40])
            script_hints=[]
            patterns=(r'''[/"'][\w/-]{1,100}\.(?:ashx|aspx|json|txt|js)(?:\?[^"'<> ]{0,80})?''',
                      r'''(?:url|src|href)\s*[:=]\s*["'][^"']{3,130}''')
            for body in [page]+p.inline:
                for pattern in patterns:
                    for m in re.findall(pattern,body,flags=re.I):
                        if any(x in m.lower() for x in ("ajax","odd","data","jing","goals","goal","jincai","get","buy","market")):
                            script_hints.append(m[:150])
            row["page_endpoint_hints"]=list(dict.fromkeys(script_hints))[:60]
            row["inline_script_count"]=len(p.inline)
            row["inline_script_lengths"]=[len(x) for x in p.inline[:40]]
            for link in row["scripts"][:16]:
                host=(urlparse(link).hostname or "").lower()
                if not host.endswith(".titan007.com"):continue
                if not link.lower().split("?")[0].endswith(".js"):continue
                sub=request(link,MAX_SCRIPT)
                if "data" not in sub:
                    script_hints.append({"url":link,"status":sub.get("http_status"),"error":sub.get("error")})
                    continue
                js=decode(sub["data"])
                endpoints=re.findall(r'''[/\w.-]{1,100}\.(?:aspx|ashx|json|txt)(?:\?[^"'<> ]{0,100})?''',js,re.I)
                triggers=("typeID","jingcai","goal","totgoal","进球","odds","jincai","loadData","dataType")
                contexts=[]
                for word in triggers:
                    m=re.search(re.escape(word),js,re.I)
                    if m:
                        i=m.start();contexts.append({"key":word,"sample":re.sub(r"\s+"," ",js[max(0,i-140):i+330])})
                script_hints.append({"url":link,"sha256":sub["sha256"],"bytes":len(sub["data"]),
                    "endpoint_candidates":list(dict.fromkeys(endpoints))[:36],"contexts":contexts[:8]})
            row["linked_script_hints"]=script_hints[-16:]
        results.append(row)
        print("CP_MARKET_AUDIT",json.dumps(row,ensure_ascii=False))
        time.sleep(0.4)
    (output/"cp_market_audit.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return results

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="football-output/cp-audit")
    args=ap.parse_args()
    audit(MARKETS,args.out)
