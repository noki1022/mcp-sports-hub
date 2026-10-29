#!/usr/bin/env python3
"""Strict standalone Kaggle team-boxscore source audit.

Loads only the 22.65 MB compressed member with 206 byte-range requests.
Validates each game's reciprocal teams, scoreboard agreement, teams, metrics,
duplicate IDs, chronological availability. Does NOT import into production.
"""
from __future__ import annotations
import csv, io, json, sys, math, zlib, struct, hashlib
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import kaggle_nba_foundation_batches as base
import probe_kaggle_stats_remote_zip as rem
rem.MAX_TRANSFER=30_000_000
FILE="csv/team_boxscores.csv"
NEEDED={"game_id","game_date","team_id","is_home","pts","fga","fta","oreb","tov","poss","off_rating","def_rating","pace"}
TRAIN_END="2024-10-01"  # prevent contamination of existing tune, calibration and test
def flag(x):
    v=str(x).strip().lower()
    if v in ("true","1","1.0","yes"):return True
    if v in ("false","0","0.0","no"):return False
    raise ValueError("UNKNOWN_HOME_FLAG")
def number(x):
    v=float(x)
    if not math.isfinite(v):raise ValueError("NOT_FINITE")
    return v
def csv_records(total,member):
    off=member["local_header_offset"]
    head=rem.read_range(off,off+29,total)
    tup=struct.unpack("<4sHHHHHIIIHH",head)
    if tup[0]!=b"PK\x03\x04" or tup[3]!=8:raise ValueError("BAD_MEMBER_HEADER")
    n,e=tup[9:11]
    name=rem.read_range(off+30,off+29+n+e,total)[:n].decode()
    if name!=FILE:raise ValueError("SOURCE_MEMBER_CHANGED")
    start=off+30+n+e
    end=start+member["compressed_bytes"]
    inflater=zlib.decompressobj(-15)
    carry=b""
    sha=hashlib.sha256()
    expanded=0
    for i in range(start,end,250000):
        data=rem.read_range(i,min(end,i+250000)-1,total)
        raw=inflater.decompress(data,8_000_000)
        if inflater.unconsumed_tail:raise ValueError("UNBOUNDED_INFLATE")
        expanded+=len(raw)
        if expanded>75_000_000:raise ValueError("UNEXPECTED_FILE_SIZE")
        sha.update(raw)
        carry+=raw
        parts=carry.split(b"\n")
        carry=parts.pop()
        for line in parts:
            if line.strip():
                yield next(csv.reader([line.decode("utf-8-sig","strict")]))
    tail=inflater.flush()
    expanded+=len(tail)
    sha.update(tail)
    carry+=tail
    if carry.strip():yield next(csv.reader([carry.decode("utf-8-sig","strict")]))
    if not inflater.eof or expanded!=member["uncompressed_bytes"]:
        raise ValueError("ZIP_DEFLATE_INTEGRITY_FAILURE")
    print("TEAM_BOX_SOURCE_INTEGRITY "+json.dumps({"sha256":sha.hexdigest(),"expanded_bytes":expanded,"compressed_bytes":member["compressed_bytes"]}),flush=True)

def parse_index(contents):
    result={}
    for r in csv.DictReader(io.StringIO(contents.decode("utf-8-sig"))):
        k=r.get("game_id","")
        if not k or k in result:raise ValueError("INDEX_DUPLICATE_OR_EMPTY_ID")
        result[k]=r
    return result

def audit(total,member,index):
    rows=csv_records(total,member)
    header=next(rows)
    if not NEEDED.issubset(header):raise ValueError("SCHEMA_CHANGED")
    grouped=defaultdict(list); reasons=Counter(); seen=Counter()
    for vals in rows:
        seen["input_rows"]+=1
        if len(vals)!=len(header):
            reasons["CSV_FIELD_MISMATCH"]+=1
            continue
        r=dict(zip(header,vals))
        gid=r["game_id"]
        game=index.get(gid)
        if not game:
            reasons["NO_INDEX_MATCH"]+=1
            continue
        try:
            rawdate=r["game_date"].strip().split("T")[0]
            targetdate=game["game_date"].strip().split("T")[0]
            if rawdate!=targetdate:raise ValueError("GAME_DATE_CONFLICT")
            home=flag(r["is_home"])
            team=r["team_id"].strip()
            expected=game["team_id_home" if home else "team_id_away"].strip()
            if team!=expected:raise ValueError("TEAM_ID_CONFLICT")
            if str(game.get("pts_home" if home else "pts_away","")).strip()=="":
                raise ValueError("INDEX_SCORE_MISSING")
            points=number(r["pts"])
            if int(points)!=points or not 40<=points<=200:
                raise ValueError("SCORE_INVALID")
            if abs(points-number(game["pts_home" if home else "pts_away"]))>1e-6:
                raise ValueError("SCORE_DISAGREEMENT")
            d={k:number(r[k]) for k in ("fga","fta","oreb","tov","poss","off_rating","def_rating","pace")}
            if not (50<=d["poss"]<=160 and 60<=d["pace"]<=160
                    and 50<=d["off_rating"]<=180 and 50<=d["def_rating"]<=180
                    and 0<=d["oreb"]<=d["fga"]<=160
                    and 0<=d["fta"]<=100 and 0<=d["tov"]<=60):
                raise ValueError("EFFICIENCY_STAT_RANGE_INVALID")
            if rawdate>=TRAIN_END:
                seen["post_train_cutoff_excluded"]+=1
                continue
            grouped[gid].append({"home":home,"date":rawdate,"team":team,"points":int(points),
                  "poss":d["poss"],"pace":d["pace"],"off_rating":d["off_rating"],"def_rating":d["def_rating"]})
        except (ValueError,KeyError,TypeError,OverflowError) as e:
            reasons[str(e) if len(str(e))<80 else "BAD_ROW"]+=1
    qualified={}
    season=defaultdict(Counter)
    for gid,parts in grouped.items():
        if len(parts)!=2 or {x["home"] for x in parts}!={True,False}:
            reasons["NOT_EXACTLY_TWO_RECIPROCAL_ROWS"]+=len(parts)
            continue
        h=next(x for x in parts if x["home"])
        a=next(x for x in parts if not x["home"])
        if h["team"]==a["team"] or h["date"]!=a["date"]:
            reasons["PAIR_TEAM_DATE_CONFLICT"]+=2
            continue
        if any(abs(h["poss"]-a["poss"])>65 for _ in [0]):
            reasons["POSSESSION_PAIR_IMPLAUSIBLE"]+=2
            continue
        qualified[gid]={"game_id":gid,"date":h["date"],"home":h["team"],"away":a["team"],
          "home_pts":h["points"],"away_pts":a["points"],"home_poss":h["poss"],
          "away_poss":a["poss"],"home_off":h["off_rating"],"away_off":a["off_rating"]}
        season[index[gid]["season_year"]]["eligible_games"]+=1
    print("TEAM_BOXSCORE_BATCH_VERDICT "+json.dumps({
      "input_rows":seen["input_rows"],"post_train_cutoff_excluded":seen["post_train_cutoff_excluded"],
      "candidate_games_strict_score_and_stat":len(qualified),
      "per_season":{s:dict(v) for s,v in sorted(season.items())},
      "rejections":dict(reasons),
      "source_independence_verified":False,
      "source_license_reuse_verified":False,
      "train_promoted":0,
      "feature_policy":"ONLY past game dates, never same-day or later",
      "repo_modified":False,"network_bytes":rem.spent
    },sort_keys=True),flush=True)

def selftest():
    assert flag("1")==True and flag("false")==False
    for v in ("nan","inf","-inf"):
        try:number(v);raise AssertionError("non-finite accepted")
        except ValueError:pass
    print("TEAM_BOXSCORE_STRICT_SELF_TEST_PASS")
def main():
    if "--self-test" in sys.argv:return selftest()
    total,entries=base.archive_entries()
    index=parse_index(base.fetch_member(total,entries["csv/games_index.csv"]))
    audit(total,entries[FILE],index)
if __name__=="__main__":main()
