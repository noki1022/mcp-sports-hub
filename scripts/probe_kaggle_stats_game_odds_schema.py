#!/usr/bin/env python3
"""Small (<1MiB) verified range inspection of a single ZIP member, no archive download."""
import csv,io,json,re,struct,zlib
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse
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
    # Inspect only bounded partial rows; do not persist source prices.
    sampled=list(csv.DictReader(io.StringIO("\n".join(lines[:-1]))))
    hosts=Counter(urlparse(x.get("source_url","")).hostname or "none" for x in sampled)
    date_stats={k:{"filled":sum(bool(x.get(k)) for x in sampled),
                   "first":next((x.get(k) for x in sampled if x.get(k)),""),
                   "last":next((x.get(k) for x in reversed(sampled) if x.get(k)),"")}
                for k in ("game_date","odds_date","last_fetched")}
    temporal=Counter()
    for rec in sampled:
        label=(rec.get("odds_date") or "").strip()
        if label.lower()=="open":
            temporal["OPEN_LABEL"]+=1
            continue
        try:
            game=datetime.fromisoformat(rec["game_date"].replace("Z","+00:00"))
            odds=datetime.fromisoformat(label.replace("Z","+00:00"))
            difference=(game-odds).total_seconds()
            if difference>0:temporal["BEFORE_SCHEDULED_TIP"]+=1
            elif difference==0:temporal["AT_SCHEDULED_TIP"]+=1
            else:temporal["AFTER_SCHEDULED_TIP_REJECT"]+=1
        except (ValueError,TypeError,KeyError):
            temporal["UNPARSEABLE_OR_MISSING_ODDS_DATE"]+=1
    # Only safe metadata: observed column names and date-like fields; no odds/raw rows persisted.
    print("KAGGLE_GAME_ODDS_PARTIAL_SCHEMA "+json.dumps({
      "member":name,"compressed_member_bytes":COMPRESSED_MEMBER_BYTES,
      "downloaded_range_bytes":len(raw),"expanded_sample_bytes":len(sample),
      "header":header_line,"source_hosts":dict(hosts.most_common(8)),
      "distinct_game_ids_in_sample":len({x.get("game_id") for x in sampled}),"date_stats":date_stats,"odds_time_classification":dict(temporal),
      "preview_full_rows":max(0,len(lines)-2),
      "timestamp_candidates":[c for c in header_line if any(t in c.lower() for t in ("time","date","updated","created","stamp","asof"))],
      "valid_full_csv_not_yet_proven":True,
      "training_admitted":0,"raw_files_saved":False
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
