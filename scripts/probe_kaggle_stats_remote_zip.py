#!/usr/bin/env python3
"""Inspect Kaggle 10.9-GB NBA archive ZIP file listing by HTTP ranges only.

Fail closed: never stream a whole archive, never write raw bytes to disk or
GitHub. Uses HEAD and only HTTP 206 byte ranges. ZIP64 central directory
listing is parsed without extracting entries. Total network budget <= 5 MiB.
"""
from __future__ import annotations
import io,json,re,struct
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlparse

URL="https://www.kaggle.com/api/v1/datasets/download/chevronronson/nba-stats-dataset"
MAX_TRANSFER=5*1024*1024
spent=0

def headers(method="HEAD",range_header=None):
    h={"User-Agent":"NBAHistoricalSourceAudit/1.0","Accept-Encoding":"identity"}
    if range_header:h["Range"]=range_header
    req=Request(URL,headers=h,method=method)
    res=urlopen(req,timeout=35)
    return res

def read_range(start,end,total):
    global spent
    if end<start or start<0 or end>=total:raise ValueError("RANGE_INVALID")
    n=end-start+1
    if spent+n>MAX_TRANSFER:raise ValueError("NETWORK_BUDGET_EXCEEDED")
    with headers("GET",f"bytes={start}-{end}") as res:
        if res.status!=206:raise ValueError(f"RANGE_NOT_HONORED_STATUS_{res.status}")
        cr=res.headers.get("Content-Range","")
        m=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",cr)
        if not m or (int(m[1]),int(m[2]),int(m[3]))!=(start,end,total):
            raise ValueError("CONTENT_RANGE_MISMATCH")
        data=res.read(n+1)
        if len(data)!=n:raise ValueError("RANGE_LENGTH_MISMATCH")
    spent+=n
    return data

def central_directory_locator(tail,tail_start,total):
    e=tail.rfind(b"PK\x05\x06")
    if e<0 or e+22>len(tail):raise ValueError("ZIP_EOCD_NOT_FOUND")
    vals=struct.unpack_from("<4sHHHHIIH",tail,e)
    count,size,offset=vals[4],vals[5],vals[6]
    if (count,size,offset)!=(65535,4294967295,4294967295) and size!=4294967295 and offset!=4294967295:
        return count,size,offset,"ZIP32"
    loc=tail.rfind(b"PK\x06\x07",0,e)
    if loc<0:raise ValueError("ZIP64_LOCATOR_MISSING")
    z64_off=struct.unpack_from("<4sIQI",tail,loc)[2]
    if z64_off>=tail_start and z64_off+56<=total:
        block=tail[z64_off-tail_start:z64_off-tail_start+56]
    else:block=read_range(z64_off,z64_off+55,total)
    if len(block)!=56 or block[:4]!=b"PK\x06\x06":raise ValueError("ZIP64_EOCD_INVALID")
    sig,record_size,vm,vn,d,ds,cdisk,ctotal,csize,coff=struct.unpack("<4sQHHIIQQQQ",block)
    if csize>MAX_TRANSFER:raise ValueError("ZIP64_CENTRAL_DIR_TOO_LARGE")
    return ctotal,csize,coff,"ZIP64"

def parse_central(raw,expected):
    result=[]
    i=0
    while i+46<=len(raw):
        if raw[i:i+4]!=b"PK\x01\x02":
            raise ValueError("CENTRAL_DIRECTORY_SIGNATURE_MISMATCH")
        head=struct.unpack_from("<4sHHHHHHIIIHHHHHII",raw,i)
        comp_size,uncomp_size,fn_len,extra_len,comment_len=head[8],head[9],head[10],head[11],head[12]
        name=raw[i+46:i+46+fn_len].decode("utf-8","replace")
        if fn_len<1 or fn_len>1000:raise ValueError("BAD_ZIP_ENTRY_NAME")
        if len(result)>=100000:raise ValueError("UNBOUNDED_ZIP_ENTRIES")
        result.append({"path":name[:210],"compressed_bytes":comp_size,"uncompressed_bytes":uncomp_size,
                       "method":head[4],"is_directory":name.endswith("/")})
        i+=46+fn_len+extra_len+comment_len
    if i!=len(raw) or len(result)!=expected:
        raise ValueError(f"CENTRAL_DIR_TRUNCATED_{len(result)}_EXPECTED_{expected}")
    return result

def main():
    global spent
    probe={"status":"NOT_YET_VERIFIED","dataset":"chevronronson/nba-stats-dataset",
           "api_endpoint":URL,"raw_archive_downloaded":False,
           "training_approved":False,"no_disk_writes":True}
    try:
        with headers("HEAD") as r:
            head={"http":r.status,"content_length":r.headers.get("Content-Length"),
                  "accept_ranges":r.headers.get("Accept-Ranges"),
                  "content_type":r.headers.get("Content-Type"),
                  "final_host":urlparse(r.url).hostname}
        probe["head"]=head
        size=int(head["content_length"] or 0)
        if size<1000 or size>30*1024**3:raise ValueError("BAD_ARCHIVE_SIZE_OR_MISSING_HEAD")
        tail_n=min(131072,size)
        tail=read_range(size-tail_n,size-1,size)
        count,cdsize,cdoff,kind=central_directory_locator(tail,size-tail_n,size)
        if not 0<=cdoff<size or cdsize>MAX_TRANSFER:raise ValueError("BAD_DIRECTORY_BOUNDS")
        central=read_range(cdoff,cdoff+cdsize-1,size)
        files=parse_central(central,count)
        prioritized=[x for x in files if any(k in x["path"].lower() for k in (
          "odds","line","money","bet","injur","inactive","boxscore","team","player","game","advanced","pbp"))]
        probe.update({"status":"ZIP_CENTRAL_DIRECTORY_VERIFIED",
          "format":kind,"remote_zip_size":size,"entries_total":len(files),
          "prioritized_matches":len(prioritized),"priority_entries":prioritized[:160],
          "other_entries_sample":[x["path"] for x in files if x not in prioritized][:15],
          "total_uncompressed_declared":sum(x["uncompressed_bytes"] for x in files if x["uncompressed_bytes"]!=4294967295)})
    except Exception as ex:
        probe.update({"status":"RANGE_PROBE_FAILED_CLOSED",
            "failure":type(ex).__name__+":"+str(ex)[:170]})
    probe["bytes_transferred"]=spent
    print("KAGGLE_LARGE_DATASET_RANGE_AUDIT "+json.dumps(probe,ensure_ascii=False,sort_keys=True),flush=True)
    assert spent<=MAX_TRANSFER
if __name__=="__main__":main()
