#!/usr/bin/env python3
"""Cross-check 007 BF bulk market prices against independent Crow*-labeled mobile pages.

Uses a tiny selected sample, public pages only. Stops if access rules are
unavailable, refuses silent field changes, no login or restricted endpoints.
"""
from __future__ import annotations
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
import argparse, json, re, time, urllib.request, urllib.error, urllib.robotparser
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import titan007_bf_snapshot as odds

HOST="https://m.titan007.com"
UA="Titan007BasketballResearch/1.0"
SPAN_RE=re.compile(r'<span\b[^>]*\bclass=["\']odds(?:\s+[^"\']*)?["\'][^>]*>\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*</span>', re.I)
TR_RE=re.compile(r'<tr\b[^>]*>.*?</tr>', re.I|re.S)

def mobile_allowed(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(HOST+"/robots.txt",headers={"User-Agent":UA}),timeout=10) as r:
            raw=r.read(40000).decode("utf-8","replace")
        rp=urllib.robotparser.RobotFileParser()
        rp.parse(raw.splitlines())
        return rp.can_fetch(UA,url)
    except urllib.error.HTTPError as e:
        return e.code in (404,410)
    except Exception:
        return False

def get_crown_row(url,gid):
    if not mobile_allowed(url):
        raise RuntimeError(f"Could not verify access policy for {url}")
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=12) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        blob=r.read(100001)
    if len(blob)>100000:
        raise RuntimeError("Unexpected page size")
    html=blob.decode("utf-8","replace")
    rows=[]
    for row in TR_RE.findall(html):
        if not re.search(r"Crow\*|Crown|皇冠",row,re.I):
            continue
        if not re.search(r"showDetail\(\s*['\"]?"+re.escape(str(gid))+r"['\"]?\s*,\s*['\"]?3",row):
            continue
        nums=[float(x) for x in SPAN_RE.findall(row)]
        if len(nums)==6:
            rows.append(nums)
    if len(rows)!=1:
        raise ValueError(f"expected exactly 1 Crown data row, found {len(rows)}")
    return rows[0]

def compare(raw,market):
    series=raw[:3]+raw[3:]
    expected=[]
    for label in ("opening","current"):
        row=market.get(label,{})
        expected.extend([row.get("first_side_water"),row.get("line"),row.get("second_side_water")])
    diff=[]
    for i,(a,b) in enumerate(zip(series,expected)):
        if b is None or abs(a-b)>0.000001:
            diff.append({"index":i,"mobile":a,"bulk":b})
    return diff

def test():
    markup="""<tr onclick="showDetail( '751320' ,'3')"><td>Crow*</td><td><span class="odds">0.90</span><span class="odds red">1.5</span><span class="odds">0.90</span></td><td><span class="odds">0.90</span><span class="odds red">6.5</span><span class="odds">0.90</span></td></tr>"""
    assert [float(x) for x in SPAN_RE.findall(markup)]==[0.9,1.5,0.9,0.9,6.5,0.9]
    assert not compare([0.9,1.5,0.9,0.9,6.5,0.9],{"opening":{"first_side_water":0.9,"line":1.5,"second_side_water":0.9},"current":{"first_side_water":0.9,"line":6.5,"second_side_water":0.9}})
    assert len(compare([0.9,1.5,0.9,0.9,6.5,0.9],{"opening":{"first_side_water":0.9,"line":2.5,"second_side_water":0.9},"current":{"first_side_water":0.9,"line":6.5,"second_side_water":0.9}}))==1
    print("CROWN_ROW_PARSER_TEST_PASS")

def run():
    text=odds.download_once()
    result=odds.parse(text)
    games={r["game_id"]:r for r in result["records"]}
    joined_path=Path("titan007_joined_nba_cba.json")
    if not joined_path.exists():
        raise RuntimeError("Joined target-date game file required")
    joined=json.loads(joined_path.read_text(encoding="utf-8"))
    eligible=[g for g in joined.get("nba_cba_games",[]) if g.get("markets",{}).get("full_spread") and g.get("markets",{}).get("full_total")]
    ids=[g["game_id"] for g in eligible[:3]]
    if not ids:
        if joined.get("nba_cba_joined_for_date",0)>0:
            raise RuntimeError("Games exist but none suitable for checking both full markets")
        output={"checked_at_utc":datetime.now(timezone.utc).isoformat(),"status":"NO_ELIGIBLE_GAMES","matching_markets":0,"mismatching_markets":0,"unverified_markets":0,"details":[]}
        Path("titan007_crown_quality_check.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(output,ensure_ascii=False))
        return
    records=[]
    for gid in ids:
        entry=games.get(gid)
        if entry is None:
            records.append({"game_id":gid,"status":"ID_NOT_IN_CURRENT_BULK"})
            continue
        for name,kind in (("full_spread","handicap"),("full_total","overunder")):
            url=f"{HOST}/lq/{kind}/{gid}.htm"
            item={"game_id":gid,"market":name,"mobile_url":url}
            try:
                numbers=get_crown_row(url,gid)
                errors=compare(numbers,entry["markets"].get(name,{}))
                item.update(status="MATCH" if not errors else "MISMATCH",mobile_six_numbers=numbers,differences=errors)
            except Exception as e:
                item.update(status="UNVERIFIED",error=f"{type(e).__name__}: {str(e)[:150]}")
            records.append(item)
            time.sleep(0.6)
    data={
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "mobile_company_label":"Crow*",
        "mobile_company_id":"3",
        "source_bulk":odds.SOURCE,
        "matching_markets":sum(x["status"]=="MATCH" for x in records),
        "mismatching_markets":sum(x["status"]=="MISMATCH" for x in records),
        "unverified_markets":sum(x["status"] not in ("MATCH","MISMATCH") for x in records),
        "details":records
    }
    Path("titan007_crown_quality_check.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(data,ensure_ascii=False,indent=2))
    if data["matching_markets"] < min(2,len(ids)*2):
        raise RuntimeError("Insufficient verified mobile Crown rows")
    if data["mismatching_markets"] or data["unverified_markets"]:
        print("QUOTE_DRIFT_OR_UNVERIFIED: not a clean Crown snapshot; sampled markets will be blocked from verification status")


if __name__=="__main__":
    if "--self-test" in sys.argv:test()
    else:run()
