#!/usr/bin/env python3
"""Small (<1MiB) verified range inspection of a single ZIP member, no archive download."""
import csv,io,json,re,struct,zlib
from urllib.request import Request,urlopen
URL="https://www.kaggle.com/api/v1/datasets/download/chevronronson/nba-stats-dataset"
# Proven in 2026-10-29 central-directory audit: game_odds member offset 0.
OFFSET=0
COMPRESSED_MEMBER_BYTES=5195677
PROBE=350000
def main():
    req=Request(URL,headers={"Range":f"bytes={OFFSET}-{OFFSET+PROBE-1}",
                               "Accept-Encoding":"identity","User-Agent":"NBAArchiveRangeAudit/1.0"})
    with urlopen(req,timeout=35) as r:
        if r.status!=206 or not re.match(r"bytes 0-349999/",r.headers.get("Content-Range","")):
            raise RuntimeError("RANGE_NOT_SUPPORTED")
        raw=r.read(PROBE+1)
    if len(raw)!=PROBE or raw[:4]!=b"PK\x03\x04":raise RuntimeError("LOCAL_ZIP_HEADER_INVALID")
    header=struct.unpack_from("<4sHHHHHIIIHH",raw,0)
    method,filename_len,extra_len=header[3],header[9],header[10]
    name=raw[30:30+filename_len].decode("utf-8")
    if name!="csv/game_odds.csv" or method!=8:raise RuntimeError("UNEXPECTED_MEMBER")
    start=30+filename_len+extra_len
    decompressor=zlib.decompressobj(-15)
    sample=decompressor.decompress(raw[start:],2500000)
    text=sample.decode("utf-8-sig","replace")
    lines=text.splitlines()
    if not lines:raise RuntimeError("EMPTY_CSV")
    header_line=next(csv.reader([lines[0]]))
    # Only safe metadata: observed column names and date-like fields; no odds/raw rows persisted.
    print("KAGGLE_GAME_ODDS_PARTIAL_SCHEMA "+json.dumps({
      "member":name,"compressed_member_bytes":COMPRESSED_MEMBER_BYTES,
      "downloaded_range_bytes":len(raw),"expanded_sample_bytes":len(sample),
      "header":header_line,
      "preview_full_rows":max(0,len(lines)-2),
      "timestamp_candidates":[c for c in header_line if any(t in c.lower() for t in ("time","date","updated","created","stamp","asof"))],
      "valid_full_csv_not_yet_proven":True,
      "training_admitted":0,"raw_files_saved":False
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
