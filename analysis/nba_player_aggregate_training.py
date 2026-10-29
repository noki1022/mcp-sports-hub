#!/usr/bin/env python3
"""Private-research, lagged player team aggregates joined to tri-route labels.

No current-game lineup or postgame boxscore fields enter current target game.
Streaming player ZIP, team total reconcile, 2-calendar-day lag on all inputs,
train/validation exported separately; 2021-22 sealed test not exported.
"""
import argparse,csv,hashlib,io,json,math,sys
from collections import defaultdict,Counter
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import kaggle_nba_foundation_batches as base
import kaggle_player_signed_shard_audit as signed
from kaggle_player_full_audit import get_rows
from nba_chronological_feature_gate import assemble,produce,add_day
from export_nba_train_ready import MODEL_COLUMNS
OUT=Path("/tmp/nba-player-aggregate-research")
FIELDS=["home_player_points5","away_player_points5","home_player_top3_share5","away_player_top3_share5",
        "home_player_active_count5","away_player_active_count5"]
def consume(games):
    expected={(r["date"],r["home"],r["away"]):(r["home_points"],r["away_points"]) for r in games}
    size,entries=base.archive_entries()
    buf=base.fetch_member(size,entries["csv/games_index.csv"])
    indices={}
    for row in csv.DictReader(io.StringIO(buf.decode("utf-8-sig"))):
        key=(row["game_date"][:10],row["home"],row["away"])
        if key in expected:
            try:
                if (int(float(row["pts_home"])),int(float(row["pts_away"])))==expected[key]:
                    indices[row["game_id"]]=(key,row)
            except (ValueError,KeyError):pass
    url,sz=signed.official_signed_url()
    if sz!=size:raise ValueError("ZIP_VERSION_CHANGED")
    def read(start,end,total):
        if total!=size:raise ValueError("ZIP_SIZE_CHANGED")
        return signed.read_direct(url,size,start,end)
    reader=get_rows(size,entries["csv/player_boxscores.csv"],read)
    hdr=next(reader)
    if not {"game_id","team_id","player_id","pts","fgm","fg3m","ftm","fga","fta"}.issubset(hdr):raise ValueError("PLAYER_SCHEMA")
    part=defaultdict(list);seen=set();rej=Counter()
    for vals in reader:
        if len(vals)!=len(hdr):rej["BAD_ROW_WIDTH"]+=1;continue
        r=dict(zip(hdr,vals))
        match=indices.get(r["game_id"])
        if not match:continue
        key,idx=match;tid=r["team_id"]
        if tid not in (idx["team_id_home"],idx["team_id_away"]):rej["TEAM_MISMATCH"]+=1;continue
        dup=(r["game_id"],tid,r["player_id"])
        if dup in seen:rej["DUPLICATE_PLAYER"]+=1;continue
        seen.add(dup)
        try:
            pts,fgm,fg3,ftm,fga,fta=[float(r[k]) for k in ("pts","fgm","fg3m","ftm","fga","fta")]
            if not all(map(math.isfinite,(pts,fgm,fg3,ftm,fga,fta))) or min(pts,fgm,fg3,ftm,fga,fta)<0:
                raise ValueError("BAD_NUMERIC")
            if abs(pts-(2*fgm+fg3+ftm))>.01 or fgm>fga or ftm>fta:raise ValueError("SCORE_ARITHMETIC")
            part[(r["game_id"],tid)].append(pts)
        except (ValueError,TypeError,KeyError) as ex:rej[str(ex)[:55]]+=1
    verified={}
    for gid,(key,idx) in indices.items():
        x=[]
        for tid,points in ((idx["team_id_home"],expected[key][0]),(idx["team_id_away"],expected[key][1])):
            scores=part.get((gid,tid),[])
            if not 5<=len(scores)<=25 or abs(sum(scores)-points)>.01:break
            total_score=sum(scores)
            x.append({"points":total_score,
                      "top3_share":sum(sorted(scores,reverse=True)[:3])/total_score,
                      "active_count":sum(p>0 for p in scores)})
        if len(x)==2:
            if key in verified:raise ValueError("DUPLICATE_MATCH_ID")
            verified[key]={"home":x[0],"away":x[1]}
    print("PLAYER_JOIN_SCORES "+json.dumps({"tri_route_games":len(games),
        "individually_consistent_team_aggregates":len(verified),
        "rejections":dict(rej),"raw_records_exported":False},sort_keys=True),flush=True)
    return verified
def make_features(baseline,verified):
    bydate=defaultdict(list)
    for key,parts in verified.items():bydate[key[0]].append((key,parts))
    ordered=sorted(bydate)
    hist=defaultdict(list)
    p=0;output=[];reject=Counter()
    for row in sorted(baseline,key=lambda r:(r["date"],r["home"],r["away"])):
        day=row["date"];cut=add_day(day,-1)
        while p<len(ordered) and ordered[p]<cut:
            for (src,h,a),parts in bydate[ordered[p]]:
                hist[h].append((src,parts["home"]))
                hist[a].append((src,parts["away"]))
            p+=1
        ha=hist[row["home"]];aa=hist[row["away"]]
        if len(ha)<5 or len(aa)<5:
            reject["LESS_THAN_5_PRIOR_COMPLETE_PLAYER_GAMES"]+=1;continue
        out=dict(row)
        for side,history in (("home",ha),("away",aa)):
            assert history[-1][0]<cut
            for f in ("points","top3_share","active_count"):
                out[f"{side}_player_{f}5"]=round(sum(x[1][f] for x in history[-5:])/5,6)
        output.append(out)
    return output,reject
def test():
    hist={}
    for i in range(5):
        d=add_day("2018-01-01",i*2)
        hist[(d,"BOS","NYK")]={"home":{"points":110+i,"top3_share":.7,"active_count":10},
                                "away":{"points":100+i,"top3_share":.65,"active_count":9}}
    target={"date":"2018-01-15","home":"BOS","away":"NYK","split":"train"}
    a,_=make_features([target],hist)
    assert len(a)==1
    hist[(add_day("2018-01-15",-1),"BOS","NYK")]={"home":{"points":200,"top3_share":.9,"active_count":8},
                                                      "away":{"points":200,"top3_share":.9,"active_count":8}}
    b,_=make_features([target],hist)
    assert a==b
    print("PLAYER_LAGGED_AGGREGATE_SELF_TEST_PASS")
def main():
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:return test()
    games,_,_=assemble()
    baseline,_=produce(games)
    verified=consume(games)
    joined,reasons=make_features(baseline,verified)
    groups={s:[r for r in joined if r["split"]==s] for s in ("train","validation","sealed_holdout")}
    if len(joined)<14000 or len(groups["train"])<11000:raise ValueError("PLAYER_COVERAGE_TOO_LOW")
    OUT.mkdir(exist_ok=True)
    final_columns=MODEL_COLUMNS+FIELDS
    artifacts={}
    for group in ("train","validation"):
        dest=OUT/(group+"_player_agg.csv")
        with dest.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=final_columns,extrasaction="ignore")
            w.writeheader();w.writerows(groups[group])
        artifacts[group]={"n":len(groups[group]),"sha256":hashlib.sha256(dest.read_bytes()).hexdigest()}
    meta={"status":"PLAYER_LAGGED_INTERNAL_RESEARCH_ONLY",
          "source_game_player_score_pairs":len(verified),"samples":{x:len(g) for x,g in groups.items()},
          "artifacts":artifacts,"lagged_player_features":FIELDS,"history_rejections":dict(reasons),
          "training_source_rights_unverified":True,"historical_publication_timestamp_unverified":True,
          "holdout_exported":False,"production_modified":False}
    (OUT/"manifest.json").write_text(json.dumps(meta,indent=2))
    print("NBA_PLAYER_AGG_TRAIN_READY "+json.dumps(meta,sort_keys=True),flush=True)
if __name__=="__main__":main()
