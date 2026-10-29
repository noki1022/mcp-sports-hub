#!/usr/bin/env python3
"""Bounded per-shard player ZIP range audit. Shards independent, no raw storage.

Avoid hundreds of source download endpoint redirects: resolve official Kaggle
redirect to signed Google Storage URL once per job, then issue Content-Range
checked requests to that exact URL. Stop on 404/expiry, no infinite retries.
Only audit deflate shards; no partial player rows are admitted as complete games.
"""
import argparse,json,re,struct,hashlib,time
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import kaggle_nba_foundation_batches as base
import probe_kaggle_stats_remote_zip as remote

def official_signed_url():
    req=Request(remote.URL,headers={"Range":"bytes=0-0","Accept-Encoding":"identity",
                                    "User-Agent":"NBAHistoricalIntegrity/1.0"})
    with urlopen(req,timeout=35) as res:
        if res.status!=206:raise RuntimeError("NO_HTTP_RANGE")
        url=res.url
        cr=res.headers.get("Content-Range","")
        if not re.fullmatch(r"bytes 0-0/\d+",cr):raise RuntimeError("BAD_INITIAL_CONTENT_RANGE")
    if urlparse(url).hostname!="storage.googleapis.com":
        raise RuntimeError("UNEXPECTED_REDIRECT_HOST")
    return url,int(cr.rsplit("/",1)[1])

def read_direct(url,total,start,end):
    n=end-start+1
    if n>4*1024*1024:raise ValueError("SHARD_REQUEST_TOO_LARGE")
    err=None
    for attempt in range(2):
        try:
            req=Request(url,headers={"Range":f"bytes={start}-{end}","Accept-Encoding":"identity",
                                     "User-Agent":"NBAHistoricalIntegrity/1.0"})
            with urlopen(req,timeout=35) as r:
                if r.status!=206:raise ValueError("RANGE_RESPONSE_NOT_206")
                if r.headers.get("Content-Range")!=f"bytes {start}-{end}/{total}":
                    raise ValueError("RANGE_MISMATCH")
                raw=r.read(n+1)
                if len(raw)!=n:raise ValueError("INCOMPLETE_RANGE")
                return raw
        except (HTTPError,URLError,OSError) as ex:
            err=ex
            # Signed URL may expire or be invalid; never persist partial shards.
            if isinstance(ex,HTTPError) and ex.code in (400,401,403,404):break
            if attempt==0:time.sleep(.6)
    raise RuntimeError(f"SHARD_NETWORK_FAILURE:{type(err).__name__}:{getattr(err,'code','unknown')}")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--shard",type=int,required=True)
    p.add_argument("--shards",type=int,default=16)
    a=p.parse_args()
    if a.shards<2 or a.shards>64 or a.shard<0 or a.shard>=a.shards:
        raise ValueError("BAD_SHARD_NUMBER")
    total,entries=base.archive_entries()
    e=entries["csv/player_boxscores.csv"]
    url,confirmed_total=official_signed_url()
    if confirmed_total!=total:raise ValueError("ARCHIVE_VERSION_CHANGED")
    off=e["local_header_offset"]
    header=read_direct(url,total,off,off+29)
    h=struct.unpack("<4sHHHHHIIIHH",header)
    if h[0]!=b"PK\x03\x04" or h[3]!=8:raise ValueError("ENTRY_MISMATCH")
    n,x=h[9:11]
    name=read_direct(url,total,off+30,off+29+n+x)[:n].decode()
    if name!="csv/player_boxscores.csv":raise ValueError("FILE_NAME_MISMATCH")
    start=off+30+n+x
    zsize=e["compressed_bytes"]
    lo=start+(zsize*a.shard)//a.shards
    hi=start+(zsize*(a.shard+1))//a.shards
    digest=hashlib.sha256()
    amount=0
    for offset in range(lo,hi,2*1024*1024):
        end=min(offset+2*1024*1024,hi)-1
        content=read_direct(url,total,offset,end)
        digest.update(content);amount+=len(content)
    if amount!=hi-lo:raise RuntimeError("INCOMPLETE_SHARD")
    # This is an independently downloaded, verified compressed-byte slice,
    # not an intact independent DEFLATE stream or a complete CSV.
    print("PLAYER_COMPRESSED_SHARD_AUDIT "+json.dumps({
        "shard":a.shard,"shards":a.shards,
        "range_start":lo,"range_end_exclusive":hi,
        "bytes":amount,"sha256":digest.hexdigest(),
        "archive_size":total,"zip_member_crc32":e["crc32"],
        "complete_csv_rows":0,"eligible_games":0,"training_admitted":0,
        "partial_records_deleted":True,"raw_data_committed":False
    },sort_keys=True),flush=True)
if __name__=="__main__":main()
