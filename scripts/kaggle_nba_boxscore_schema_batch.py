#!/usr/bin/env python3
"""Kaggle NBA batch 3: inspect team/player schemas with bounded HTTP 206 ranges.

No permanent raw data. This is a schema probe, not training admission.
"""
import csv,io,json,struct,zlib,re
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import kaggle_nba_foundation_batches as foundation
import probe_kaggle_stats_remote_zip as remote
remote.MAX_TRANSFER=5*1024*1024
TARGETS=("csv/team_boxscores.csv","csv/player_boxscores.csv")
def sample(size,member):
    offset=member["local_header_offset"]
    h=remote.read_range(offset,offset+29,size)
    head=struct.unpack("<4sHHHHHIIIHH",h)
    assert head[0]==b"PK\x03\x04" and head[3]==8
    nlen,elen=head[9:11]
    nm=remote.read_range(offset+30,offset+29+nlen+elen,size)[:nlen].decode()
    assert nm==member["path"]
    first=offset+30+nlen+elen
    n=min(220000,member["compressed_bytes"])
    packed=remote.read_range(first,first+n-1,size)
    output=zlib.decompressobj(-15).decompress(packed,1750000)
    lines=output.decode("utf-8-sig","replace").splitlines()
    r=csv.DictReader(io.StringIO("\n".join(lines[:-1])))
    rows=list(r)
    fields=r.fieldnames or []
    ids=Counter(row.get("game_id","") for row in rows)
    blanks=Counter(k for row in rows for k in fields if (row.get(k) or "").strip()=="")
    return {"file":nm,"declared_raw_bytes":member["uncompressed_bytes"],"declared_compressed_bytes":member["compressed_bytes"],
      "sample_rows":len(rows),"distinct_game_ids":len(ids),"fields":fields,"top_missing_fields":dict(blanks.most_common(12)),
      "game_id_examples":list(ids.keys())[:3],"source_raw_saved":False,"training_admitted":0}
def main():
    size,files=foundation.archive_entries()
    for target in TARGETS:
        print("KAGGLE_BATCH3_SCHEMA "+json.dumps(sample(size,files[target]),ensure_ascii=False,sort_keys=True),flush=True)
    print("KAGGLE_BATCH3_VERDICT "+json.dumps({"bytes_transferred":remote.spent,"no_raw_archive_download":True,"accepted_to_training":0}))
if __name__=="__main__":main()
