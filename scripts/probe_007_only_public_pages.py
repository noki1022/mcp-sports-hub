#!/usr/bin/env python3
"""007-only public-page discovery, read-only, not a lottery fixed-bonus scraper.

Only checks cp5.titan007.com root and the already-proven JC NBA index.
Never requests cp.titan007.com robots-disallowed JingCaiBasket pages, performs
automated browser impersonation, calls discovered endpoints, or follows redirects.
"""
import json,re,urllib.error,urllib.request,urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
from datetime import datetime,timezone

UA="NBA-007-Authorized-Source-Audit/1.0"
TARGETS={"cp5":"https://cp5.titan007.com/","cp5_basketball":"https://cp5.titan007.com/basketball.shtml","jc":"https://jc.titan007.com/nba/index.aspx"}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None
opener=urllib.request.build_opener(NoRedirect)

def fetch(url,limit=240000):
    q=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,text/plain,*/*;q=0.2"})
    with opener.open(q,timeout=12) as r:
        if r.status!=200:raise RuntimeError("NON_200")
        data=r.read(limit+1)
        if len(data)>limit:raise ValueError("BODY_LIMIT")
        return data

def allowed(url):
    origin=urlsplit(url).scheme+"://"+urlsplit(url).netloc
    try:
        data=fetch(origin+"/robots.txt",60000)
    except urllib.error.HTTPError as ex:
        if ex.code in (404,410):return True,"ROBOTS_UNAVAILABLE_"+str(ex.code)
        return False,"ROBOTS_HTTP_"+str(ex.code)
    except (OSError,RuntimeError,ValueError):
        return False,"ROBOTS_UNREADABLE"
    rp=urllib.robotparser.RobotFileParser()
    rp.parse(data.decode("utf-8","replace").splitlines())
    return rp.can_fetch(UA,url),"ROBOTS_PRESENT"

class Structure(HTMLParser):
    def __init__(self,origin):
        super().__init__()
        self.origin=origin;self.links=set();self.scripts=set();self.tables=0;self.rows=0;self.cells=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="table":self.tables+=1
        if tag=="tr":self.rows+=1
        if tag in ("td","th"):self.cells+=1
        for name,bucket in (("href",self.links),("src",self.scripts)):
            if tag not in (("a","link") if name=="href" else ("script",)):continue
            value=a.get(name,"")
            if not value:continue
            u=urlsplit(urljoin(self.origin,value))
            if u.scheme=="https" and u.netloc==urlsplit(self.origin).netloc:
                bucket.add(u.path)

def scan(name,url,fetcher=fetch,check=allowed):
    record={"url":url,"status":"UNVERIFIED","lottery_fixed_prices_verified":0}
    yes,state=check(url);record["robots_status"]=state
    if not yes:record["status"]="ACCESS_NOT_ELIGIBLE";return record
    try:raw=fetcher(url)
    except urllib.error.HTTPError as e:record["status"]="HTTP_"+str(e.code);return record
    except (OSError,ValueError,RuntimeError) as e:record["status"]="FETCH_"+type(e).__name__;return record
    decoded=None
    for encoding in ("utf-8-sig","gb18030"):
        try:decoded=raw.decode(encoding);break
        except UnicodeDecodeError:pass
    if decoded is None:record["status"]="UNDECODABLE";return record
    struct=Structure(url);struct.feed(decoded)
    # Debug only internal same-site path names. Never fetch them.
    records=[p for p in struct.links|struct.scripts if any(
        t in p.lower() for t in ("jingcai","basket","jclq","lq","odds","jc","buy"))]
    record.update({"status":"PAGE_RETURNED","bytes":len(raw),"tables":struct.tables,
        "rows":struct.rows,"cells":struct.cells,
        "same_site_links":len(struct.links),"same_site_scripts":len(struct.scripts),
        "candidate_paths":sorted(records)[:30],
        "markets_text_flags":{k:(k in decoded) for k in ("竞彩","让分胜负","大小分","胜负","固定奖金")},
        "machine_readable_price_rows":0})
    return record

def main():
    results={k:scan(k,u) for k,u in TARGETS.items()}
    print("TITAN007_EXCLUSIVE_PUBLIC_PAGE_AUDIT",json.dumps(results,ensure_ascii=False))
def selftest():
    fake="<html><a href='/buy/JingCaiBasket.aspx?TypeID=112'>x</a><script src='/js/basket.js'></script><table><tr><td>竞彩</td></tr></table></html>".encode('utf-8')
    result=scan("mock",TARGETS["cp5"],lambda _:fake,lambda _:(True,"MOCK"))
    assert result["status"]=="PAGE_RETURNED" and result["lottery_fixed_prices_verified"]==0
    assert "/buy/JingCaiBasket.aspx" in result["candidate_paths"]
    calls=[]
    def blocked(url):
        calls.append(url);return False,"BLOCKED"
    assert scan("x",TARGETS["cp5"],lambda _:1/0,blocked)["status"]=="ACCESS_NOT_ELIGIBLE"
    assert len(calls)==1
    print("TITAN007_PUBLIC_PATH_ONLY_SELFTEST_PASS")
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:selftest()
    else:main()
