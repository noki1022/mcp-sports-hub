#!/usr/bin/env python3
"""Audit Kaggle odds in sequential streaming chunks, group output by season.

No raw ZIP or CSV persisted, no features admitted. Checks exact ZIP entry
integrity, one-to-one game IDs and per-quote pregame time. 'open'/'close' labels
are NOT presumed timestamped. Sources must be separately licensed and audited.
"""
from __future__ import annotations
import csv,io,json,math,re,struct,zlib
from urllib.parse import urlparse
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import kaggle_nba_foundation_batches as foundation
import probe_kaggle_stats_remote_zip as remote
remote.MAX_TRANSFER=14*1024*1024
TARGET="csv/game_odds.csv"

def iso(x):
    x=(x or "").strip().replace("Z","+00:00")
    try:
        v=datetime.fromisoformat(x)
        return v if v.tzinfo is not None else None
    except ValueError:return None

def verify(row,match):
    if not match:return "NO_GAME_INDEX"
    game=iso(match.get("game_date"))
    if game is None:
        # Index stores date without timezone; lack of timezone forbids
        # inferring precise start-of-game timing.
        return "INDEX_TIP_TIME_UNVERIFIED"
    label=(row.get("odds_date") or "").strip()
    if label.lower() in ("open","close","opening","closing"):return "UNTIMED_"+label.upper()
    stamp=iso(label)
    if not stamp:return "MISSING_OR_INVALID_ODDS_DATE"
    if stamp>=game:return "NON_PREGAME_REJECT"
    raw=[row.get("decimal_home",""),row.get("decimal_away","")]
    try:
        p=list(map(float,raw))
        if any(not math.isfinite(v) or v<=1.01 or v>1000 for v in p):
            return "INVALID_DECIMAL_ODDS"
        implied=sum(1/v for v in p)
        if not 0.80<=implied<=1.40:return "OVERROUND_INVALID"
    except (ValueError,TypeError):return "MISSING_PRICE"
    return "PREGAME_TIME_CANDIDATE"

def stream_odds(total,entry,gameids):
    offset=entry["local_header_offset"]
    head=remote.read_range(offset,offset+29,total)
    sig,version,flags,method,t,d,crc,cs,us,nlen,elen=struct.unpack("<4sHHHHHIIIHH",head)
    if sig!=b"PK\x03\x04" or method!=8:raise ValueError("ZIP_LOCAL_HEADER_WRONG")
    tail=remote.read_range(offset+30,offset+29+nlen+elen,total)
    if tail[:nlen].decode()!="csv/game_odds.csv":raise ValueError("ZIP_FILE_MISMATCH")
    begin=offset+30+nlen+elen
    end=begin+entry["compressed_bytes"]
    decompressor=zlib.decompressobj(-15)
    actual_crc=0
    decoded=0
    carry=""
    header=None
    counts=defaultdict(Counter)
    ids=defaultdict(set)
    num_rows=0
    source_hosts=Counter()
    candidate_ids=set()
    timestamp_candidate_quotes=0
    for i in range(begin,end,131072):
        data=remote.read_range(i,min(i+131072,end)-1,total)
        output=decompressor.decompress(data)
        if len(output)>8_000_000 or decoded+len(output)>110_000_000:raise ValueError("UNEXPECTED_INFLATE_BURST")
        decoded+=len(output)
        actual_crc=zlib.crc32(output,actual_crc)
        carry+=output.decode("utf-8","strict")
        lines=carry.split("\n");carry=lines.pop()
        for line in lines:
            if not line.strip():continue
            rowvals=next(csv.reader([line]))
            if header is None:
                header=rowvals
                required={"game_id","game_date","odds_date","decimal_home","decimal_away","source_url"}
                if not required.issubset(header):raise ValueError("ODDS_SCHEMA_CHANGED")
                continue
            if len(rowvals)!=len(header):raise ValueError("CSV_COLUMN_COUNT_MISMATCH")
            row=dict(zip(header,rowvals))
            num_rows+=1
            game=gameids.get(row["game_id"])
            season=(game or {}).get("season_year","UNKNOWN")
            year=str(season)
            status=verify(row,game)
            counts[year][status]+=1
            source_hosts[urlparse(row.get("source_url","")).hostname or "MISSING"]+=1
            if status=="PREGAME_TIME_CANDIDATE":
                candidate_ids.add(row["game_id"])
                timestamp_candidate_quotes+=1
            if len(ids[year])<5000:ids[year].add(row["game_id"])
    leftover=decompressor.flush()
    actual_crc=zlib.crc32(leftover,actual_crc)
    decoded+=len(leftover)
    if carry.strip() or leftover.strip():
        # Do not silently drop trailing partial records.
        rem=carry+leftover.decode("utf-8","strict")
        if rem.strip():
            rv=next(csv.reader([rem]))
            if len(rv)!=len(header):raise ValueError("TRAILING_CSV_ROW_INVALID")
            row=dict(zip(header,rv));num_rows+=1
            game=gameids.get(row["game_id"])
            counts[str((game or {}).get("season_year","UNKNOWN"))][verify(row,game)]+=1
    if not decompressor.eof or decoded!=entry["uncompressed_bytes"]:
        raise ValueError("ODDS_ZIP_LENGTH_OR_CRC_INCOMPLETE")
    return {"total_quote_rows":num_rows,"expanded_bytes":decoded,
      "by_season":{season:{"quote_statuses":dict(c),"sample_distinct_game_ids":len(ids[season])} for season,c in sorted(counts.items())},
      "source_archive_crc32":f"{actual_crc:08x}",
      "source_domains":dict(source_hosts.most_common(10)),
      "unique_pregame_candidate_games":len(candidate_ids),
      "timestamp_candidate_quotes":timestamp_candidate_quotes,
      "source_provenance_not_verified":True,
      "strict_train_eligible":0}

def main():
    if "--self-test" in sys.argv:
        assert verify({"odds_date":"2025-01-01T20:00:00Z","decimal_home":"1.9","decimal_away":"1.9"},{"game_date":"2025-01-02T00:00:00Z"})=="PREGAME_TIME_CANDIDATE"
        assert verify({"odds_date":"close"},{"game_date":"2025-01-02T00:00:00Z"})=="UNTIMED_CLOSE"
        assert verify({"odds_date":"2025-01-02T01:00:00Z"},{"game_date":"2025-01-02T00:00:00Z"})=="NON_PREGAME_REJECT"
        print("KAGGLE_ODDS_BATCH_SELF_TEST_PASS")
        return
    total,entry=foundation.archive_entries()
    index_bytes=foundation.fetch_member(total,entry["csv/games_index.csv"])
    schedule_bytes=foundation.fetch_member(total,entry["csv/games_schedule.csv"])
    index={r["game_id"]:r for r in csv.DictReader(io.StringIO(index_bytes.decode("utf-8-sig")))}
    schedules={r["game_id"]:r for r in csv.DictReader(io.StringIO(schedule_bytes.decode("utf-8-sig")))}
    # Schedule supplies timezone only for 2025-26; old index dates remain
    # unverified rather than manufacturing precise tip-off time.
    for k,row in index.items():
        if k in schedules:row["game_date"]=schedules[k]["game_date"]
    result=stream_odds(total,entry[TARGET],index)
    result["timestamp_gate"]={
      "status":"PASSED_FOR_EXPLICIT_PRETIP_QUOTES" if result.get("timestamp_candidate_quotes",0)>0 else "NO_EXPLICIT_PRETIP_QUOTES",
      "passed_quote_rows":result.get("timestamp_candidate_quotes",0),
      "passed_game_ids":result.get("unique_pregame_candidate_games",0),
      "tip_time_source":"games_schedule.csv",
      "comparison":"odds_date < game_date",
      "untimed_open_close_excluded":True,
      "old_seasons_without_tip_time":"QUARANTINED"
    }
    print("KAGGLE_ODDS_SEASON_BATCH_AUDIT "+json.dumps(result,sort_keys=True,ensure_ascii=False),flush=True)
    print("KAGGLE_ODDS_BATCH_VERDICT "+json.dumps({
       "train_admitted":0,"timestamp_gate_passed":result.get("timestamp_gate",{}),"zip_downloaded_in_full":False,
       "raw_data_saved":False,"bytes_fetched":remote.spent,
       "unmatched_old_game_times_do_not_enter_training":True
    },sort_keys=True))
if __name__=="__main__":main()
