#!/usr/bin/env python3
"""Read-only, fail-closed Titan007 BF basketball market snapshot parser.

This is independent research code. The published HTML references the JS file.
No login, automation evasion, guessing of IDs or unrestricted crawling.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import re
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path

SOURCE = "https://bf.titan007.com/NBA/sbOddsDataBsk.js"
ROBOTS = "https://bf.titan007.com/robots.txt"
UA = "Titan007BasketballResearch/1.0"
ROW = re.compile(r"sData\[(\d{4,12})\]\s*=\s*(\[\[.*?\]\])\s*;", re.DOTALL)
GROUP = re.compile(r"\[([^\[\]]*)\]")
MARKETS = ("full_spread", "full_total", "half_spread", "half_total")
EPOCH_LABELS = ("opening", "current", "in_play")

def number(s):
    s = s.strip().strip("'\"")
    if not s:
        return None
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", s):
        raise ValueError(f"non-numeric market element: {s[:30]!r}")
    return float(s)

def parse(text):
    games = {}
    skipped = []
    for m in ROW.finditer(text):
        game_id = m.group(1)
        if game_id in games:
            skipped.append({"game_id":game_id,"reason":"duplicate"})
            continue
        groups = GROUP.findall(m.group(2))
        if len(groups) < 2:
            skipped.append({"game_id":game_id,"reason":"too_few_groups"})
            continue
        markets = {}
        try:
            for j, label in enumerate(MARKETS):
                if j >= len(groups):
                    continue
                values = [number(x) for x in groups[j].split(",")]
                if not values:
                    continue
                if len(values) < 9:
                    values.extend([None] * (9 - len(values)))
                markets[label] = {
                    stage: {"first_side_water":values[k*3], "line":values[k*3+1], "second_side_water":values[k*3+2]}
                    for k, stage in enumerate(EPOCH_LABELS)
                }
        except ValueError as e:
            skipped.append({"game_id":game_id,"reason":str(e)})
            continue
        full = (markets.get("full_spread"),markets.get("full_total"))
        if not any(x and any(v["line"] is not None for v in x.values()) for x in full):
            skipped.append({"game_id":game_id,"reason":"no_full_market"})
            continue
        games[game_id] = {"game_id":game_id,"markets":markets}
    return {"records":list(games.values()),"rejected":skipped}

def download_once():
    with urllib.request.urlopen(
        urllib.request.Request(ROBOTS,headers={"User-Agent":UA}),timeout=12
    ) as f:
        rp=urllib.robotparser.RobotFileParser()
        rp.parse(f.read(50000).decode("utf-8","replace").splitlines())
    if not rp.can_fetch(UA,SOURCE):
        raise RuntimeError("robots rules do not allow requested source")
    with urllib.request.urlopen(
        urllib.request.Request(SOURCE,headers={"User-Agent":UA,"Accept":"application/javascript,*/*;q=0.5"}),timeout=15
    ) as f:
        data=f.read(400001)
        if len(data)>400000:
            raise RuntimeError("response too large")
        if f.status != 200:
            raise RuntimeError(f"HTTP {f.status}")
        return data.decode("gb18030","replace")

def self_test():
    snippet = (
        "sData[751320]=[[0.90,1.5,0.90,0.90,6.5,0.90,0.83,17.5,0.87],"
        "[0.88,193.5,0.88,1.00,192.5,0.76,0.87,172.5,0.73],"
        "[,,,,,,,,],[,,,,,,,,],[,,,,,,,,,1],[,,,,,,,,]];"
    )
    obj=parse(snippet)
    assert len(obj["records"]) == 1
    m=obj["records"][0]["markets"]
    assert m["full_spread"]["opening"]["line"] == 1.5
    assert m["full_spread"]["current"]["line"] == 6.5
    assert m["full_total"]["opening"]["line"] == 193.5
    assert m["full_total"]["current"]["line"] == 192.5
    assert m["full_spread"]["in_play"]["line"] == 17.5
    assert m["half_spread"]["opening"]["line"] is None
    assert parse(snippet+snippet)["rejected"][0]["reason"] == "duplicate"
    assert not parse("const a=123456;")["records"]
    print("PARSER_SELF_TEST_PASS")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="titan007_bf_snapshot.json")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test()
        return
    raw=download_once()
    result=parse(raw)
    records=result["records"]
    if not records:
        raise RuntimeError("no valid match IDs with full-market data; refusing empty success")
    output={
        "source_url":SOURCE,
        "fetched_at_utc":datetime.now(timezone.utc).isoformat(),
        "company_identity":"UNVERIFIED (historical source associates this feed with SB/Crown)",
        "water_side_mapping":"UNVERIFIED (raw first/second side slots)",
        "coverage":"ALL LEAGUES IN SOURCE, NOT NBA/CBA FILTERED",
        "game_count":len(records),
        "sample_game_ids":[r["game_id"] for r in records[:15]],
        "records":records,
        "rejected":result["rejected"]
    }
    Path(args.out).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in output.items() if k not in ("records","rejected")},ensure_ascii=False,indent=2))
    print("rejected_count",len(result["rejected"]))

if __name__ == "__main__":
    main()
