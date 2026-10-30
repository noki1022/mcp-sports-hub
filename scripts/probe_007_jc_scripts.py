#!/usr/bin/env python3
"""Bounded read-only public JS structure check for Titan007's *JC* scoreboard domain.

Only the two script paths observed in the previous real HTML probe are requested.
Never requests discovered endpoints, calls private APIs, uses cookies/credentials,
changes user agent to impersonate a browser, or follows robots-disallowed paths.
This is source discovery, not proof of lottery prices.
"""
from __future__ import annotations
import hashlib
import json
import re
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime,timezone
from urllib.parse import urlsplit

ORIGIN="https://jc.titan007.com"
SCRIPTS=("/js/basket.js","/js/common.js")
UA="NBA-007-Authorized-Source-Audit/1.0"
MAX_JS=240000

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def get_bytes(url, max_bytes, fetch=None):
    if urlsplit(url).scheme!="https" or urlsplit(url).netloc!="jc.titan007.com":
        raise ValueError("HOST_RESTRICTED")
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/javascript,application/javascript,text/plain,*/*;q=0.1"})
    if fetch is None:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=12) as response:
            if response.status!=200:raise RuntimeError("HTTP_NOT_OK")
            data=response.read(max_bytes+1)
    else:
        with fetch(req,timeout=12) as response:
            if response.status!=200:raise RuntimeError("HTTP_NOT_OK")
            data=response.read(max_bytes+1)
    if len(data)>max_bytes:raise ValueError("BODY_TOO_LARGE")
    return data

def robots_policy(fetch=None):
    try:
        raw=get_bytes(ORIGIN+"/robots.txt",60000,fetch)
    except urllib.error.HTTPError as exc:
        if exc.code in (404,410):
            return None,"ROBOTS_UNAVAILABLE_"+str(exc.code)
        return False,"ROBOTS_HTTP_"+str(exc.code)
    except (OSError,ValueError,RuntimeError):
        return False,"ROBOTS_CHECK_FAILED"
    rp=urllib.robotparser.RobotFileParser()
    rp.parse(raw.decode("utf-8","replace").splitlines())
    return rp,"ROBOTS_PRESENT"

def examine_js(raw):
    text=raw.decode("utf-8","replace")
    flags={label: bool(re.search(pattern,text,re.I))
        for label,pattern in {
          "xhr":r"XMLHttpRequest",
          "ajax":r"(?:\$\.(?:ajax|getJSON|get|post)|fetch\s*\()",
          "basketball":r"basket|篮球|nba",
          "lottery":r"jingcai|竞彩|lottery|csl",
          "form_post":r"\bpostback\b|__doPostBack",
          "html_table":r"<tr|insertRow|innerHTML|appendChild"
        }.items()}
    # Only disclose source-defined static path names; discard all query strings
    # or credentials and do not dereference discovered links.
    candidates=set()
    for match in re.finditer(r"""["']((?:https?://[^"' ]+|[./][^"' ]+)\.(?:aspx|ashx|xml|json|php|js)(?:\?[^"']*)?)["']""",text,re.I):
        val=match.group(1).split("?",1)[0]
        if len(val)>150:continue
        parts=urlsplit(val)
        if parts.scheme:
            value=parts.netloc+parts.path
        else:
            value=parts.path
        candidates.add(value)
    # Extract bounded redacted context from each occurrence. Does not fetch discovered URLs.
    targets=("JcResult.aspx","oddsChange.aspx","oddsData.aspx","AsianOdds_n.aspx","OverDown_n.aspx")
    contexts={}
    for target in targets:
        snippets=[]
        for m in list(re.finditer(re.escape(target),text,re.I))[:4]:
            excerpt=text[max(0,m.start()-120):min(len(text),m.end()+120)]
            excerpt=re.sub(r"[\r\n\t]+"," ",excerpt)
            excerpt=re.sub(r"(?i)(token|secret|key|password)\\s*[:=]\\s*['\\\"][^'\\\"]+['\\\"]",r"\1=[REDACTED]",excerpt)
            snippets.append(excerpt[:270])
        if snippets:contexts[target]=snippets
    return {"bytes":len(raw),"sha256_prefix":hashlib.sha256(raw).hexdigest()[:16],
      "flags":flags,"static_endpoint_path_candidates":sorted(candidates)[:25],
      "candidate_count":len(candidates),
      "raw_lottery_word_occurrences":sum(text.lower().count(w) for w in ("jingcai","竞彩","lottery","csl")),"target_callsite_context":contexts}

def inspect(fetch=None):
    policy, status=robots_policy(fetch)
    out={"checked_at_utc":datetime.now(timezone.utc).isoformat(),
         "host":ORIGIN,"robots_status":status,
         "source":"PUBLIC_JC_DOMAIN_SCRIPTS_NOT_CP_LOTTERY",
         "verified_lottery_odds":0,"scripts":{}}
    for path in SCRIPTS:
        record={"status":"UNAVAILABLE","lottery_prices_verified":False}
        url=ORIGIN+path
        if policy is False:
            record["status"]="ROBOTS_CHECK_BLOCKED"
        elif policy is not None and not policy.can_fetch(UA,url):
            record["status"]="ACCESS_DISALLOWED"
        else:
            try:
                raw=get_bytes(url,MAX_JS,fetch)
                record.update({"status":"SCRIPT_RETURNED",**examine_js(raw)})
            except urllib.error.HTTPError as exc:
                record["status"]="HTTP_"+str(exc.code)
            except (OSError,ValueError,RuntimeError) as exc:
                record["status"]="FETCH_FAILED_"+type(exc).__name__
        out["scripts"][path]=record
    return out

def self_test():
    class Reply:
        def __init__(self,text,status=200): self.raw=text;self.status=status
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,*a):return self.raw
    calls=[]
    def fake(req,timeout=12):
        calls.append(req.full_url)
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url,404,"Not Found",{},None)
        return Reply(b"var x='/api/public/score.json'; XMLHttpRequest;")
    result=inspect(fake)
    assert result["scripts"]["/js/basket.js"]["status"]=="SCRIPT_RETURNED"
    assert "/api/public/score.json" in result["scripts"]["/js/basket.js"]["static_endpoint_path_candidates"]
    assert len(calls)==3 and all(url.startswith(ORIGIN+"/") for url in calls)
    blocked_calls=[]
    def denied(req,timeout=12):
        blocked_calls.append(req.full_url)
        return Reply(b"User-agent: *\nDisallow: /js/\n")
    result=inspect(denied)
    assert all(row["status"]=="ACCESS_DISALLOWED" for row in result["scripts"].values())
    assert len(blocked_calls)==1
    print("JC_SCRIPT_NO_ENDPOINT_FETCH_SELF_TEST_PASS")

if __name__=="__main__":
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser()
    p.add_argument("--out")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        x=inspect()
        if a.out:Path(a.out).write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n")
        print("JC_JS_SOURCE_METADATA",json.dumps(x,ensure_ascii=False))
