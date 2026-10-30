#!/usr/bin/env python3
"""One-shot read-only structure audit of a public JC basketball text feed.

The path was found in the already-permitted /js/basket.js call site.
This is NOT a pricing adapter; zero official/verified Jingcai odds are assumed.
Do not invoke other endpoints, follow redirects, bypass robots, or schedule polling.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import urllib.error
from datetime import datetime,timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy

TARGET="/xml/bf_jc_lq.txt"
MAX_BYTES=350000

def inspect(fetch=None):
    report={"url":ORIGIN+TARGET,"checked_at_utc":datetime.now(timezone.utc).isoformat(),
            "status":"UNVERIFIED","source":"JC_PUBLIC_BASKETBALL_FEED",
            "verified_007_jingcai_fixed_prices":0,"official_payout_verified":False,
            "eligible_for_production":False}
    policy,robots_status=robots_policy(fetch)
    report["robots_status"]=robots_status
    if policy is False:
        report["status"]="ROBOTS_CHECK_BLOCKED"
        return report
    if policy is not None and not policy.can_fetch(UA,ORIGIN+TARGET):
        report["status"]="ROBOTS_DISALLOWED"
        return report
    try:
        raw=get_bytes(ORIGIN+TARGET,MAX_BYTES,fetch)
    except urllib.error.HTTPError as exc:
        report["status"]="HTTP_"+str(exc.code)
        return report
    except (OSError,RuntimeError,ValueError) as exc:
        report["status"]="FETCH_FAILED_"+type(exc).__name__
        return report
    report["status"]="FEED_RETURNED"
    report["size_bytes"]=len(raw)
    report["sha256_prefix"]=hashlib.sha256(raw).hexdigest()[:16]
    decoded=None
    for encoding in ("utf-8-sig","gb18030"):
        try:
            decoded=raw.decode(encoding)
            report["decoded_as"]=encoding
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        report["status"]="UNDECODABLE_BODY"
        return report
    stripped=decoded.strip()
    report["body_kind"]="HTML_LIKE" if stripped.lower().startswith(("<!doctype","<html")) else (
        "JSON_LIKE" if stripped.startswith(("{","[")) else "TEXT_OR_XML")
    # Format evidence only; avoid publishing full bodies or arbitrary HTML/script content.
    lines=[x.strip() for x in decoded.splitlines() if x.strip()]
    report["nonempty_line_count"]=len(lines)
    report["longest_line_chars"]=max((len(x) for x in lines),default=0)
    report["nba_mentions"]=len(re.findall(r"\bNBA\b",decoded,re.I))
    report["jctype_mentions"]=sum(decoded.lower().count(t) for t in ("竞彩","jingcai","彩票"))
    report["site_fixture_id_markers"]={v:bool(re.search(r"(?<!\d)"+v+r"(?!\d)",decoded)) for v in ("728165","728166","728167")}
    report["punctuation"]={c:decoded.count(c) for c in ("^","|",",","~")}
    try:
        root=ET.fromstring(decoded.lstrip("\ufeff"))
        report["xml_root"]=root.tag[:80]
        report["xml_first_level_tag_counts"]={tag:len(root.findall(tag)) for tag in ("m","match","h","game","row")}
    except ET.ParseError:
        report["xml_root"]=None
    # Short samples only for delimited data, not markup. These might be scores, not odds!
    if report["body_kind"]=="TEXT_OR_XML" and not stripped.startswith("<"):
        report["sample_first_lines"]=[re.sub(r"[^\x20-\x7E\u3400-\u9FFF]","?",x)[:180] for x in lines[:3]]
    report["schema_verified"]=False
    report["price_side_orientation_verified"]=False
    report["field_meanings_verified"]=False
    return report

def self_test():
    class Response:
        status=200
        def __init__(self,data):self.data=data
        def __enter__(self):return self
        def __exit__(self,*exc):return False
        def read(self,*a):return self.data
    requests=[]
    def allowed(req,timeout=12):
        requests.append(req.full_url)
        if req.full_url.endswith("robots.txt"):
            raise urllib.error.HTTPError(req.full_url,404,"Not Found",{},None)
        return Response("NBA^728165^2026-10-31^0:0\n".encode())
    r=inspect(allowed)
    assert r["status"]=="FEED_RETURNED" and r["site_fixture_id_markers"]["728165"]
    assert not r["eligible_for_production"] and r["verified_007_jingcai_fixed_prices"]==0
    assert requests==[ORIGIN+"/robots.txt",ORIGIN+TARGET]
    def denied(req,timeout=12):
        if req.full_url.endswith("robots.txt"):
            return Response(b"User-agent: *\nDisallow: /xml/\n")
        raise AssertionError("Disallowed feed requested")
    assert inspect(denied)["status"]=="ROBOTS_DISALLOWED"
    print("JC_PUBLIC_BF_FEED_READ_ONLY_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        result=inspect()
        if a.out:Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("JC_PUBLIC_BF_FEED_AUDIT",json.dumps(result,ensure_ascii=False))
