#!/usr/bin/env python3
"""One-off bounded 007 JC basketball lottery-odds feed verification.

Uses exact /xml/odds_jc_lq.txt path found in the accessible /js/common.js.
Fetches robots first, never requests cp.titan007.com restricted pages, never
creates production prices from ambiguous fields.
"""
import hashlib,json,re,urllib.error
from datetime import datetime,timezone
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy
TARGET="/xml/odds_jc_lq.txt"
MAX_BYTES=300000

def audit(fetch=None):
    out={"source":ORIGIN+TARGET,"checked_at_utc":datetime.now(timezone.utc).isoformat(),
         "status":"UNVERIFIED","fixed_bonus_verified":False,"verified_price_rows":0,
         "can_use_for_production":False}
    robots,state=robots_policy(fetch)
    out["robots_status"]=state
    if robots is False:out["status"]="ROBOTS_NOT_VERIFIED";return out
    if robots is not None and not robots.can_fetch(UA,ORIGIN+TARGET):
        out["status"]="ROBOTS_DISALLOWED";return out
    try:
        raw=get_bytes(ORIGIN+TARGET,MAX_BYTES,fetch)
    except urllib.error.HTTPError as e:
        out["status"]="HTTP_"+str(e.code);return out
    except (OSError,ValueError,RuntimeError) as e:
        out["status"]="FETCH_"+type(e).__name__;return out
    out["status"]="FEED_RETURNED"
    out["bytes"]=len(raw);out["sha256_16"]=hashlib.sha256(raw).hexdigest()[:16]
    content=raw.decode("utf-8-sig","replace")
    out["delimiter_counts"]={k:content.count(k) for k in ("$","!","^",",","~")}
    out["nba_fixture_ids_present"]={n:bool(re.search(r"(?<!\d)"+n+r"(?!\d)",content)) for n in ("728165","728166","728167","728169","728173")}
    out["first_240_chars_sanitized"]=re.sub(r"[^\x20-\x7e\u3400-\u9fff]","?",content[:240])
    out["contents_appear_html"]=bool(re.search(r"<html|<!doctype",content[:500],re.I))
    out["schema_validated"]=False
    return out

def self_test():
    class Res:
        status=200
        def __init__(self,raw):self.raw=raw
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,*a):return self.raw
    calls=[]
    def ok(req,timeout=12):
        calls.append(req.full_url)
        if req.full_url.endswith("robots.txt"):
            raise urllib.error.HTTPError(req.full_url,404,"not found",{},None)
        return Res(b"728165!2.15!1.60$728166!1.8!1.7")
    r=audit(ok)
    assert r["status"]=="FEED_RETURNED" and r["verified_price_rows"]==0
    assert calls==[ORIGIN+"/robots.txt",ORIGIN+TARGET]
    def denied(req,timeout=12):
        if req.full_url.endswith("robots.txt"):
            return Res(b"User-agent: *\nDisallow: /xml/\n")
        raise AssertionError("disallowed XML fetch")
    assert audit(denied)["status"]=="ROBOTS_DISALLOWED"
    print("JC_BASKET_LOTTERY_FEED_SELFTEST_PASS")

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:print("JC_BASKET_LOTTERY_FEED_AUDIT",json.dumps(audit(),ensure_ascii=False))
