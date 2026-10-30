#!/usr/bin/env python3
"""Classify real JC 007 basketball JS odds data handling from permitted public scripts.

Research only. Makes exactly robots check + two known script fetches. Does not
call discovered endpoints or cp.titan007.com restricted lottery URLs.
"""
from __future__ import annotations
import hashlib,json,re
from datetime import datetime,timezone
from probe_007_jc_scripts import (ORIGIN,UA,SCRIPTS,MAX_JS,get_bytes,robots_policy)

TOKENS={
    "lottery_mode":"Config.isJc",
    "odds_data":"oddsData.aspx",
    "odds_change":"oddsChange.aspx",
    "jc_result":"JcResult.aspx",
    "odds_source":"oddsCID",
    "company_id":"showCompanyID",
    "home_price":"homeOdds",
    "guest_price":"guestOdds",
    "home_win":"homeWin",
    "guest_win":"guestWin",
    "total_line":"totalScore",
    "spread_line":"letBall"
}
def inspect_text(raw):
    s=raw.decode("utf-8","replace")
    results={}
    for label,needle in TOKENS.items():
        found=list(re.finditer(re.escape(needle),s,re.I))
        samples=[]
        for m in found[:3]:
            fragment=s[max(0,m.start()-150):min(len(s),m.end()+170)]
            fragment=fragment.replace("\r"," ").replace("\n"," ").replace("\t"," ")
            fragment=re.sub(r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]",r"\1=[REDACTED]",fragment)
            samples.append(fragment[:330])
        results[label]={"count":len(found),"callsite_snippets":samples}
    return {"size_bytes":len(raw),"sha256_first_16":hashlib.sha256(raw).hexdigest()[:16],
            "token_references":results,"fixed_bonus_records_verified":0}

def audit(fetch=None):
    policy,status=robots_policy(fetch)
    result={"at_utc":datetime.now(timezone.utc).isoformat(),"host":ORIGIN,
        "robots_status":status,"verified_fixed_bonuses":0,"odds_source_identity_verified":False,
        "scripts":{}}
    for path in SCRIPTS:
        if policy is False or (policy is not None and not policy.can_fetch(UA,ORIGIN+path)):
            result["scripts"][path]={"status":"NOT_PERMITTED"};continue
        try:
            result["scripts"][path]={"status":"RETURNED",**inspect_text(get_bytes(ORIGIN+path,MAX_JS,fetch))}
        except Exception as e:
            result["scripts"][path]={"status":"UNAVAILABLE","error":type(e).__name__}
    return result

def self_test():
    from urllib.error import HTTPError
    class Response:
        status=200
        def __init__(self,data):self.data=data
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,*a):return self.data
    requests=[]
    def fake(req,timeout=12):
        requests.append(req.full_url)
        if req.full_url.endswith("/robots.txt"):raise HTTPError(req.full_url,404,"not found",{},None)
        return Response(b"var a=Config.isJc ? oddsItem.guestWin : oddsItem.guestOdds;")
    x=audit(fake)
    assert len(requests)==3
    assert x["scripts"]["/js/basket.js"]["token_references"]["lottery_mode"]["count"]==1
    assert x["verified_fixed_bonuses"]==0
    def deny(req,timeout=12):
        if req.full_url.endswith("/robots.txt"):return Response(b"User-agent: *\nDisallow: /js/\n")
        raise AssertionError("never fetch blocked scripts")
    assert all(v["status"]=="NOT_PERMITTED" for v in audit(deny)["scripts"].values())
    print("JC_BASKET_ODDS_SEMANTICS_SELFTEST_PASS")

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:self_test()
    else:print("JC_BASKET_ODDS_SEMANTICS_AUDIT",json.dumps(audit(),ensure_ascii=False))
