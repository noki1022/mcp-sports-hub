#!/usr/bin/env python3
"""One-shot license-aware candidate inventory. Never merge into 007 live data.

The upstream NBA line-sheet repository says MIT and pairs game scores with
odds, but does NOT prove original quotes' availability timestamps or individual
bookmaker provenance. Inventory is benchmarking only until strict point-in-time
evidence exists. CSV is kept in the runner temp area, not committed.
"""
from __future__ import annotations
import csv, hashlib, io, json, collections
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime,timezone

SOURCE="https://raw.githubusercontent.com/aaryanshah607/nba-line-sheet/main/nba_odds_clean.csv"
REF="https://github.com/aaryanshah607/nba-line-sheet"
MAX_BYTES=8_000_000

def fetch():
    req=Request(SOURCE,headers={"User-Agent":"NBA-Licensed-Research-Inventory/1.0"})
    with urlopen(req,timeout=35) as res:
        content=res.read(MAX_BYTES+1)
    if not content or len(content)>MAX_BYTES:
        raise RuntimeError("CANDIDATE_CSV_INVALID_OR_TOO_LARGE")
    return content

def inventory(raw):
    src=raw.decode("utf-8-sig")
    cr=csv.DictReader(io.StringIO(src))
    columns=cr.fieldnames
    if not columns or len(set(columns))!=len(columns):
        raise ValueError("DUPLICATED_OR_MISSING_SOURCE_COLUMNS")
    cells=collections.Counter()
    vals=collections.defaultdict(collections.Counter)
    dates=[]
    count=0
    examples=[]
    for record in cr:
        count+=1
        if len(examples)<2:examples.append(record)
        for k,v in record.items():
            if v is None or str(v).strip()=="":
                cells[k]+=1
            elif k in ("Date","Home","Away","Spread","Total","ML_Home","ML_Away",
                       "Score_Home","Score_Away","Pts_Home","Pts_Away"):
                vals[k][str(v).strip()]+=1
        if record.get("Date"):dates.append(record["Date"])
    return {
        "source":SOURCE,"upstream_repository":REF,
        "licence_claimed_by_upstream":"MIT_REPO_SOURCE_LICENSE_UPSTREAM_DATA_PROVENANCE_NOT_INDEPENDENTLY_VERIFIED",
        "timestamp_semantics":"GAME_DAY_QUOTE_OPEN_CLOSE_UNVERIFIED",
        "not_007_jingcai_or_crown":True,
        "eligible_for_007_point_in_time_training":False,
        "independent_quote_time_verified":False,
        "rows":count,"columns":columns,"missing_by_column":dict(cells),
        "date_lexical_min":min(dates) if dates else None,
        "date_lexical_max":max(dates) if dates else None,
        "sample_rows":examples,
        "unique_home":len(vals["Home"]),"unique_away":len(vals["Away"]),
        "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
        "source_scan_at_utc":datetime.now(timezone.utc).isoformat(),
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="/tmp/nba-line-sheet-inventory.json")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        o=inventory(b"Date,Home,Away,ML_Home,ML_Away\n2025-01-01,LAL,BOS,-110,+100\n")
        assert o["rows"]==1 and o["not_007_jingcai_or_crown"] and not o["eligible_for_007_point_in_time_training"]
        print("NBA_HISTORICAL_LINE_SHEET_LICENSE_SAFE_INVENTORY_SELF_TEST_PASS")
        return
    o=inventory(fetch())
    Path(args.out).write_text(json.dumps(o,indent=2,ensure_ascii=False)+"\n")
    print("NBA_HISTORICAL_LINE_SHEET_INVENTORY",json.dumps(o,ensure_ascii=False)[:9500])
if __name__=="__main__":main()
