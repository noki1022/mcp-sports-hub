#!/usr/bin/env python3
"""Read-only 007 JC soccer fulltime source field audit.

Examines the actual same public XML-style text feed already used by football
capture. It reports RAW status codes and score columns, without assuming that
a numerical status by itself proves 90-minute FT, or modifying any models.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime,timezone

from football_007_live_capture import FEEDS,fetch,timestamp,text_decode

MAX_BYTES=2_000_000

def inspect(raw,observed_at):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise ValueError("INVALID_007_RAW_BYTES")
    decoded=text_decode(raw)
    sections=decoded.split("$")
    if len(sections)<2:
        raise ValueError("NO_007_FIXTURE_SECTION")
    statuses=Counter()
    nonzero=[]
    invalid=[]
    seen=set()
    for record in sections[1].split("!"):
        if not record.strip():continue
        cols=record.split("^")
        if len(cols)<15 or not re.fullmatch(r"\d{4,10}",cols[0]):
            invalid.append({"example":record[:90]})
            continue
        mid=cols[0]
        if mid in seen:
            raise ValueError("DUPLICATE_007_FIXTURE_ID")
        seen.add(mid)
        st=cols[3].strip()
        statuses[st]+=1
        if st!="0":
            sample={
                "match_id":mid,"jc_number":cols[4],
                "time_utc":timestamp(cols[1]).astimezone(timezone.utc).isoformat(),
                "status_raw":st,"home_team_id":cols[7],"away_team_id":cols[9],
                "home_name":cols[8].split(",")[0],
                "away_name":cols[10].split(",")[0],
                "candidate_score_fields":{"c11":cols[11],"c12":cols[12],
                    "c13":cols[13],"c14":cols[14]},
                "field_count":len(cols)}
            nonzero.append(sample)
    return {
        "audit":"OBSERVED_007_JC_RAW_STATUS_CODES_NO_ASSUMED_FT_MAPPING",
        "source_url":FEEDS["fixtures"],
        "captured_at_utc":observed_at,
        "raw_sha256":hashlib.sha256(raw).hexdigest(),
        "bytes":len(raw),"fixtures":len(seen),
        "statuses":dict(sorted(statuses.items())),
        "nonzero_status_samples":nonzero[:25],
        "nonzero_status_total":len(nonzero),
        "invalid_row_count":len(invalid)
    }

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--out",default="football-ft-source-audit/source_status.json")
    a.add_argument("--raw-dir",default="football-ft-source-audit/raw")
    args=a.parse_args()
    raw=fetch(FEEDS["fixtures"])
    asof=datetime.now(timezone.utc).isoformat()
    report=inspect(raw,asof)
    directory=Path(args.raw_dir);directory.mkdir(parents=True,exist_ok=True)
    (directory/"bf_jc.txt.gz").write_bytes(gzip.compress(raw,mtime=0))
    output=Path(args.out);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print("FOOTBALL_007_FT_SOURCE_STATUS",json.dumps(
        {"fixtures":report["fixtures"],"statuses":report["statuses"],
         "nonzero_samples":report["nonzero_status_samples"][:6]},ensure_ascii=False))
if __name__=="__main__":main()
