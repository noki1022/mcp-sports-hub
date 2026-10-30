#!/usr/bin/env python3
"""Read-only eligibility probe for 007's *distinct* JC basketball host.

Checks robots before any page request. No anti-bot workaround, cookies,
browser impersonation, credential usage, page payload dumping, or odds claims.
Results are audit metadata only, not verified lottery price rows.
"""
import json
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import urlparse

UA = "NBA-007-Authorized-Source-Audit/1.0"
HOST = "https://jc.titan007.com"
PATH = "/nba/index.aspx"

def inspect(fetch=None):
    fetch = fetch or urllib.request.urlopen
    report = {"host":HOST, "page":HOST+PATH,"checked_at_utc":datetime.now(timezone.utc).isoformat(),
              "status":"UNVERIFIED","odds_rows_verified":0,
              "fixed_bonus_verified":False}
    robots = urllib.request.Request(HOST+"/robots.txt",headers={"User-Agent":UA})
    try:
        with fetch(robots,timeout=12) as response:
            raw = response.read(60001)
            if len(raw)>60000:raise ValueError("ROBOTS_SIZE_LIMIT")
            lines = raw.decode("utf-8","replace").splitlines()
        rp=urllib.robotparser.RobotFileParser()
        rp.parse(lines)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            rp=urllib.robotparser.RobotFileParser()
            rp.parse([])
            report["robots_status"]="UNAVAILABLE_"+str(exc.code)
        else:
            report["status"]="ROBOTS_HTTP_"+str(exc.code)
            return report
    except (OSError, ValueError, RuntimeError) as exc:
        report["status"]="ROBOTS_CHECK_FAILED_"+type(exc).__name__
        return report
    if not rp.can_fetch(UA,HOST+PATH):
        report["status"]="ACCESS_DISALLOWED_BY_ROBOTS"
        return report
    report["robots_allows_page"]=True
    try:
        req=urllib.request.Request(HOST+PATH,headers={"User-Agent":UA,"Accept":"text/html"})
        with fetch(req,timeout=15) as response:
            raw=response.read(250001)
            if len(raw)>250000:raise ValueError("PAGE_SIZE_LIMIT")
            report["status"]="PAGE_RETURNED"
            report["http_status"]=response.status
            report["content_type"]=response.headers.get("Content-Type","")
            report["content_length"]=len(raw)
            report["html_table_tags"]=raw.lower().count(b"<table")
            report["contains_lottery_words"]=any(x in raw for x in
               ("竞彩".encode("utf-8"),"胜负".encode("utf-8"),"竞彩".encode("gb18030")))
    except urllib.error.HTTPError as exc:
        report["status"]="PAGE_HTTP_"+str(exc.code)
    except (OSError, ValueError, RuntimeError) as exc:
        report["status"]="PAGE_FETCH_FAILED_"+type(exc).__name__
    return report

def self_test():
    class Reply:
        def __init__(self,content,status=200):
            self.content,self.status,self.headers=content,status,{"Content-Type":"text/html"}
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,*a):return self.content
    def blocked(req,timeout=12):
        if req.full_url.endswith("/robots.txt"):
            return Reply(b"User-agent: *\nDisallow: /nba/\n")
        raise AssertionError("disallowed page fetched")
    b=inspect(blocked)
    assert b["status"]=="ACCESS_DISALLOWED_BY_ROBOTS"
    def allowed(req,timeout=12):
        if req.full_url.endswith("/robots.txt"):
            return Reply(b"User-agent: *\nAllow: /\n")
        return Reply("<table>竞彩 胜负</table>".encode("utf-8"))
    a=inspect(allowed)
    assert a["status"]=="PAGE_RETURNED" and a["fixed_bonus_verified"] is False
    def missing(req,timeout=12):
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url,404,"Not Found",{},None)
        return Reply("<table>NBA 竞彩</table>".encode("utf-8"))
    m=inspect(missing)
    assert m["status"]=="PAGE_RETURNED" and m["robots_status"]=="UNAVAILABLE_404"
    print("JC_007_READ_ONLY_ACCESS_AUDIT_TEST_PASS")

if __name__=="__main__":
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser()
    p.add_argument("--output")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:self_test()
    else:
        x=inspect()
        if args.output:Path(args.output).write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n")
        print("JC_007_PUBLIC_ACCESS_AUDIT",json.dumps(x,ensure_ascii=False))
