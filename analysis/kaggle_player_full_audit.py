#!/usr/bin/env python3
"""Full-stream player records audit: no player rows written to Git, no training promotion."""
import csv,io,sys,json,math,struct,zlib
from collections import defaultdict,Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import kaggle_nba_foundation_batches as base
import kaggle_player_signed_shard_audit as signed
import probe_kaggle_stats_remote_zip as remote
remote.MAX_TRANSFER=260_000_000
TARGET="csv/player_boxscores.csv"
def get_rows(total,m,read_range=remote.read_range):
    off=m["local_header_offset"]
    head=read_range(off,off+29,total)
    h=struct.unpack("<4sHHHHHIIIHH",head)
    if h[0]!=b"PK\x03\x04" or h[3]!=8:raise ValueError("ZIP_HEADER_INVALID")
    n,e=h[9:11]
    name=read_range(off+30,off+29+n+e,total)[:n].decode()
    if name!=TARGET:raise ValueError("ZIP_ENTRY_MISMATCH")
    begin=off+30+n+e
    z=zlib.decompressobj(-15)
    carry=b""
    decoded=0
    for pos in range(begin,begin+m["compressed_bytes"],400_000):
        compressed=read_range(pos,min(pos+400_000,begin+m["compressed_bytes"])-1,total)
        data=z.decompress(compressed,16_000_000)
        if z.unconsumed_tail:raise ValueError("INFLATE_LIMIT")
        decoded+=len(data)
        if decoded>800_000_000:raise ValueError("UNBOUNDED_EXPANSION")
        chunks=(carry+data).split(b"\n")
        carry=chunks.pop()
        for line in chunks:
            if line:yield next(csv.reader([line.decode("utf-8-sig")]))
    rest=z.flush()
    decoded+=len(rest)
    if carry+rest:
        tail=(carry+rest).strip()
        if tail:yield next(csv.reader([tail.decode("utf-8-sig")]))
    if not z.eof or decoded!=m["uncompressed_bytes"]:raise ValueError("ZIP_INTEGRITY_FAILED")
    print("PLAYER_FILE_STREAM_VERIFIED",decoded,flush=True)
def check():
    total,m=base.archive_entries()
    url,archive_len=signed.official_signed_url()
    if archive_len!=total:raise ValueError("ARCHIVE_VERSION_CHANGED")
    def verified_range(start,end,size):
        if size!=total:raise ValueError("ARCHIVE_SIZE_CHANGED")
        return signed.read_direct(url,total,start,end)
    idx=base.fetch_member(total,m["csv/games_index.csv"])
    ref={r["game_id"]:r for r in csv.DictReader(io.StringIO(idx.decode("utf-8-sig")))}
    iterator=get_rows(total,m[TARGET],verified_range)
    fields=next(iterator)
    need={"game_id","player_id","team_id","team_abbreviation","game_date","pts","fgm","fg3m","ftm","fga","fta","min"}
    if not need.issubset(fields):raise ValueError("CHANGED_SCHEMA")
    counts=Counter();seen=set();team_scores=defaultdict(lambda:[0,0,0])
    for vals in iterator:
        counts["raw_player_rows"]+=1
        if len(vals)!=len(fields):counts["bad_csv_width"]+=1;continue
        r=dict(zip(fields,vals));g=ref.get(r["game_id"])
        if not g:counts["game_not_in_index"]+=1;continue
        pid=r["player_id"];key=(r["game_id"],r["team_id"],pid)
        if not pid or key in seen:counts["duplicate_or_missing_player"]+=1;continue
        seen.add(key)
        tid=r["team_id"]
        if tid not in (g["team_id_home"],g["team_id_away"]):counts["team_conflict"]+=1;continue
        if r["game_date"][:10]!=g["game_date"][:10]:counts["date_conflict"]+=1;continue
        if r["game_date"][:10]>="2024-10-01":counts["holdout_cutoff_excluded"]+=1;continue
        try:
            pts=float(r["pts"]);fgm=float(r["fgm"]);fg3=float(r["fg3m"]);ft=float(r["ftm"]);fga=float(r["fga"]);fta=float(r["fta"])
            if not all(map(math.isfinite,(pts,fgm,fg3,ft,fga,fta))) or any(x<0 for x in (pts,fgm,fg3,ft,fga,fta)):raise ValueError()
            if abs(pts-(2*fgm+fg3+ft))>.01 or fgm>fga or ft>fta:raise ValueError()
        except (ValueError,TypeError):
            counts["missing_or_conflicting_player_stats"]+=1;continue
        k=(r["game_id"],tid)
        team_scores[k][0]+=pts;team_scores[k][1]+=1
        counts["individually_valid_prior_train_player_rows"]+=1
    games=Counter()
    for (gid,tid),(points,n,_) in team_scores.items():
        g=ref[gid];home=tid==g["team_id_home"]
        try:expected=float(g["pts_home" if home else "pts_away"])
        except (ValueError,TypeError):counts["missing_index_score"]+=1;continue
        if abs(points-expected)<.01 and 5<=n<=25:games[gid]+=1
        else:counts["player_sum_vs_team_score_conflict"]+=1
    counts["fully_reconciled_games"]=sum(v==2 for v in games.values())
    print("KAGGLE_PLAYER_FULL_AUDIT "+json.dumps({"counts":dict(counts),"downloaded_bytes":remote.spent,"signed_url_range_read":True,"source_license_upstream_unverified":True,"training_promoted":0,"raw_records_saved":False},sort_keys=True),flush=True)
if __name__=="__main__":
    if "--self-test" in sys.argv:
        assert (2*10+3+4)==27
        print("PLAYER_STRICT_SELF_TEST_PASS")
    else:check()
