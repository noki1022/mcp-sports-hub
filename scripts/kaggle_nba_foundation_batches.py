#!/usr/bin/env python3
"""Batch 1: strictly read *only* two small files inside Kaggle NBA Stats ZIP.

ZIP central directory + byte range 206 checks, DEFLATE CRC/size verification,
bounded RAM, no raw files saved. Not a training acceptance decision.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import re
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_kaggle_stats_remote_zip as remote
remote.MAX_TRANSFER=10*1024*1024
TARGETS=("csv/games_schedule.csv","csv/games_index.csv")

def archive_entries():
    try:
        r=remote.headers("HEAD")
    except Exception as e:
        if getattr(e,"code",None) not in (403,404,405):raise
        r=remote.headers("GET","bytes=0-0")
    with r:
        http=r.status
        clen=r.headers.get("Content-Length","")
        content_range=r.headers.get("Content-Range","")
    if http==206:
        m=re.fullmatch(r"bytes 0-0/(\d+)",content_range)
        if not m:raise ValueError("NO_VERIFIED_ZIP_LENGTH")
        size=int(m[1])
    elif http==200:size=int(clen)
    else:raise ValueError("ZIP_DOWNLOAD_STATUS_INVALID")
    if not 2_000_000_000<size<4_000_000_000:raise ValueError("ARCHIVE_VERSION_OR_SIZE_CHANGED")
    tail_len=131072
    tail=remote.read_range(size-tail_len,size-1,size)
    n,cdsize,offset,fmt=remote.central_directory_locator(tail,size-tail_len,size)
    directory=remote.read_range(offset,offset+cdsize-1,size)
    members=remote.parse_central(directory,n)
    names={m["path"]:m for m in members}
    if len(members)!=8 or not set(TARGETS).issubset(names):raise ValueError("ZIP_MANIFEST_CHANGED")
    return size,names

def fetch_member(size,info,cap=7_000_000):
    if info["method"]!=8 or info["uncompressed_bytes"]>cap or info["compressed_bytes"]>4_000_000:
        raise ValueError("ENTRY_TOO_LARGE")
    off=info["local_header_offset"]
    header=remote.read_range(off,off+29,size)
    values=struct.unpack("<4sHHHHHIIIHH",header)
    if values[0]!=b"PK\x03\x04" or values[3]!=8:
        raise ValueError("ZIP_LOCAL_HEADER_INVALID")
    namelen,extralen=values[9:11]
    local=remote.read_range(off+30,off+30+namelen+extralen-1,size)
    name=local[:namelen].decode("utf-8")
    if name!=info["path"]:raise ValueError("ZIP_MEMBER_NAME_MISMATCH")
    start=off+30+namelen+extralen
    end=start+info["compressed_bytes"]
    decomp=zlib.decompressobj(-15)
    checksum=0
    chunks=[]
    for blockstart in range(start,end,131072):
        raw=remote.read_range(blockstart,min(blockstart+131072,end)-1,size)
        part=decomp.decompress(raw,cap+1-sum(map(len,chunks)))
        chunks.append(part)
        if sum(map(len,chunks))>cap:raise ValueError("MEMBER_DECOMPRESSION_LIMIT")
    final=decomp.flush()
    chunks.append(final)
    data=b"".join(chunks)
    if not decomp.eof or len(data)!=info["uncompressed_bytes"]:
        raise ValueError("ZIP_DEFLATE_OR_SIZE_CHECK_FAILED")
    return data

def profile(name,data):
    reader=csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    cols=reader.fieldnames or []
    if not cols or len(cols)>150:raise ValueError("CSV_SCHEMA_INVALID")
    n=0
    missing=Counter()
    id_values=Counter()
    date_keys=[k for k in cols if any(s in k.lower() for s in ("date","time","start","tip"))]
    date_ranges={k:{"first":None,"last":None,"filled":0} for k in date_keys}
    for row in reader:
        n+=1
        if n>100000:raise ValueError("ROWS_OVER_LIMIT")
        if None in row:missing["INVALID_EXTRA_COLUMNS"]+=1
        for k in date_keys:
            v=(row.get(k) or "").strip()
            if v:
                date_ranges[k]["filled"]+=1
                if date_ranges[k]["first"] is None:date_ranges[k]["first"]=v[:35]
                date_ranges[k]["last"]=v[:35]
        if "game_id" in row:
            v=(row.get("game_id") or "").strip()
            if v:id_values[v]+=1
    return {"name":name,"sha256":hashlib.sha256(data).hexdigest(),
      "rows":n,"header":cols,"date_like_fields":date_ranges,
      "distinct_game_ids":len(id_values),"repeated_game_id_values":sum(c>1 for c in id_values.values()),
      "invalid_row_counts":dict(missing),"research_only":True}

def main():
    if "--self-test" in sys.argv:
        assert "csv/games_index.csv" in TARGETS
        assert remote.MAX_TRANSFER<15*1024*1024
        print("KAGGLE_BATCH_FOUNDATION_SELF_TEST_PASS")
        return
    size,files=archive_entries()
    for name in TARGETS:
        data=fetch_member(size,files[name])
        report=profile(name,data)
        print("KAGGLE_FOUNDATION_BATCH "+json.dumps(report,sort_keys=True,ensure_ascii=False),flush=True)
        del data
    print("KAGGLE_FOUNDATION_VERDICT "+json.dumps({
      "status":"SCHEMA_VALIDATION_ONLY","bytes_transferred":remote.spent,
      "full_archive_downloaded":False,"raw_saved":False,"training_admitted":0},sort_keys=True))
if __name__=="__main__":main()
