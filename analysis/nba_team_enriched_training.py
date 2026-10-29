#!/usr/bin/env python3
"""Build auditable lagged TEAM boxscore features joined to tri-route verified NBA labels.

Every source game is:
1) matched to the independent-source verified target outcome;
2) checked against Kaggle index for both teams, score, date and numeric ranges;
3) made available only to games at least TWO calendar dates later.
Raw Kaggle ZIP/rows are never kept in the repository. Never export sealed holdout.
This is private research training input; upstream game data rights are not certified.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math,sys
from collections import defaultdict,Counter,deque
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"analysis"))
import kaggle_nba_foundation_batches as base
from kaggle_team_boxscore_strict_audit import csv_records
from nba_chronological_feature_gate import assemble,produce,OUT_FEATURES,TRAIN_END,VALID_END,EMBARGO_DAYS,add_day

FIELDS=("off_rating","def_rating","pace","efg_pct","tm_tov_pct","oreb_pct")
STAT_COLUMNS=[f"{side}_{stat}{window}" for side in ("home","away") for stat in FIELDS for window in (5,10)]
STAT_COLUMNS+=["home_box_last_date","away_box_last_date"]
INDEX_REQUIRED={"game_id","game_date","home","away","team_id_home","team_id_away","pts_home","pts_away"}
OUT_DIR=Path("/tmp/nba-team-stats-train-ready")
GATE_MIN_GAMES=15500

def team_code(x):
    alias={"BRK":"BKN","NJN":"BKN","NOH":"NOP","NOK":"NOP","CHO":"CHA",
           "PHO":"PHX","SA":"SAS","GS":"GSW","WSH":"WAS"}
    code=str(x).strip().upper()
    return alias.get(code,code)

def safe_num(x,low,high):
    n=float(x)
    if not (math.isfinite(n) and low<=n<=high):raise ValueError("STAT_OUT_OF_RANGE")
    return n

def build_boxscores(games):
    expected={(g["date"],g["home"],g["away"]):(int(g["home_points"]),int(g["away_points"])) for g in games}
    total,members=base.archive_entries()
    blob=base.fetch_member(total,members["csv/games_index.csv"])
    index={}
    index_reasons=Counter()
    for i in csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))):
        day=i.get("game_date","")[:10]
        key=(day,team_code(i.get("home","")),team_code(i.get("away","")))
        if not "2007-08-01"<=day<"2022-08-01" or key not in expected:continue
        try:
            hp,ap=int(float(i["pts_home"])),int(float(i["pts_away"]))
            if (hp,ap)!=expected[key]:raise ValueError("INDEX_SCORE_CONFLICT")
            if i["game_id"] in index:raise ValueError("DUPLICATE_INDEX_GAME_ID")
            index[i["game_id"]]=(key,i)
        except (ValueError,KeyError) as ex:
            index_reasons[str(ex)[:70]]+=1
    per_game=defaultdict(list);row_reject=Counter()
    rows=csv_records(total,members["csv/team_boxscores.csv"])
    header=next(rows)
    required={"game_id","game_date","team_id","is_home","pts",*FIELDS}
    if not required.issubset(header):raise ValueError("TEAM_SOURCE_SCHEMA_CHANGED")
    for values in rows:
        if len(values)!=len(header):
            row_reject["BAD_CSV_WIDTH"]+=1;continue
        row=dict(zip(header,values))
        entry=index.get(row["game_id"])
        if entry is None:continue
        key,i=entry
        try:
            side=str(row["is_home"]).strip().lower()
            if side not in ("1","0","true","false","1.0","0.0"):raise ValueError("INVALID_HOME_FLAG")
            home=side in ("1","true","1.0")
            expect_id=i["team_id_home" if home else "team_id_away"]
            expect_pts=expected[key][0 if home else 1]
            if row["team_id"]!=expect_id:raise ValueError("TEAM_ID_MISMATCH")
            if row["game_date"][:10]!=key[0]:raise ValueError("GAME_DATE_MISMATCH")
            pts=safe_num(row["pts"],40,200)
            if pts!=expect_pts:raise ValueError("SCORE_MISMATCH")
            metrics={}
            for field in FIELDS:
                metrics[field]=safe_num(row[field],50 if field in ("off_rating","def_rating") else
                                        60 if field=="pace" else 0,
                                        180 if field in ("off_rating","def_rating") else
                                        160 if field=="pace" else 1.5)
            per_game[row["game_id"]].append((home,row["team_id"],metrics))
        except (ValueError,TypeError,KeyError) as ex:
            row_reject[str(ex)[:65]]+=1
    result={}
    for gid,parts in per_game.items():
        if len(parts)!=2 or {p[0] for p in parts}!={True,False}:
            row_reject["NON_RECIPROCAL_OR_PARTIAL_GAME"]+=1;continue
        (key,i)=index[gid]
        home=next(p[2] for p in parts if p[0])
        away=next(p[2] for p in parts if not p[0])
        if len({parts[0][1],parts[1][1]})!=2:
            row_reject["DUPLICATE_TEAM_ID"]+=1;continue
        if key in result:raise RuntimeError("SAME_GAME_MULTIPLE_KAGGLE_IDS")
        result[key]={"home":home,"away":away}
    print("TEAM_STATS_MATCH_AUDIT "+json.dumps({
      "tri_route_games":len(expected),"indexed_score_matched":len(index),
      "boxscore_score_matched_pairs":len(result),
      "index_reasons":dict(index_reasons),
      "row_reasons":dict(row_reject),
      "index_sha256":hashlib.sha256(blob).hexdigest(),
      "source_side_bytes_loaded_by_ranges":True,
      "training_license_unverified":True
    },sort_keys=True),flush=True)
    return result

def features_for(base_rows,game_stats,history_embargo=EMBARGO_DAYS):
    """Lag boxscores by two calendar days, never from same/opposing games on target day."""
    per_day=defaultdict(list)
    for key,stats in game_stats.items():
        per_day[key[0]].append((key,stats))
    pending=deque()
    history=defaultdict(list)
    results=[]
    reject=Counter()
    for row in sorted(base_rows,key=lambda r:(r["date"],r["home"],r["away"])):
        day=row["date"]
        cut=add_day(day,-history_embargo)
        # stage history by day, append when source game day STRICTLY before cut
        while pending and pending[0][0]<cut:
            _,items=pending.popleft()
            for (gday,h,a),pair in items:
                history[h].append((gday,pair["home"]))
                history[a].append((gday,pair["away"]))
        # pending only receives source dates <= current day, in chronological order
        # Add previously unseen source dates < current date, keeping late ones staged.
        if not pending or pending[-1][0]<day:
            pass
        h,a=row["home"],row["away"]
        hh=[r for r in history[h] if r[0]<cut]
        aa=[r for r in history[a] if r[0]<cut]
        if len(hh)<10 or len(aa)<10:
            reject["INSUFFICIENT_PRIOR_VERIFIED_BOX_GAMES"]+=1
        else:
            values={}
            for side,values_history in (("home",hh),("away",aa)):
                for feature in FIELDS:
                    for period in (5,10):
                        values[f"{side}_{feature}{period}"]=sum(v[feature] for _,v in values_history[-period:])/period
                values[f"{side}_box_last_date"]=values_history[-1][0]
            assert all(values[f"{side}_box_last_date"]<cut for side in ("home","away"))
            results.append({**row,**values})
    return results,reject

def lagged_join(base_rows,game_stats):
    """Correct event-time batched processing: a game becomes eligible strictly after embargo."""
    grouped=defaultdict(list)
    for k,v in game_stats.items():grouped[k[0]].append((k,v))
    history=defaultdict(list)
    entries=sorted(grouped)
    p=0
    result=[];reject=Counter()
    for row in sorted(base_rows,key=lambda r:(r["date"],r["home"],r["away"])):
        day=row["date"];cut=add_day(day,-EMBARGO_DAYS)
        while p<len(entries) and entries[p]<cut:
            d=entries[p]
            for (gday,home,away),box in grouped[d]:
                history[home].append((gday,box["home"]))
                history[away].append((gday,box["away"]))
            p+=1
        h,a=history[row["home"]],history[row["away"]]
        if len(h)<10 or len(a)<10:
            reject["MISSING_10_PRIOR_BOX_GAMES"]+=1;continue
        new=dict(row)
        for side,values in (("home",h),("away",a)):
            for feature in FIELDS:
                for window in (5,10):
                    new[f"{side}_{feature}{window}"]=round(sum(x[1][feature] for x in values[-window:])/window,6)
            new[f"{side}_box_last_date"]=values[-1][0]
            if not new[f"{side}_box_last_date"]<cut:raise AssertionError("BOX_SCORE_LEAKAGE")
        result.append(new)
    return result,reject

def self_test():
    target={"date":"2019-02-01","home":"BOS","away":"NYK","split":"train",
            "feature_latest_source_date":"2019-01-28","home_win":1,"home_margin":5,"final_total":210}
    g={}
    for k in range(12):
        day=add_day("2019-01-01",k*2)
        base={f:float(100+k) if f in ("off_rating","def_rating","pace") else .5 for f in FIELDS}
        g[(day,"BOS","NYK")]={"home":base,"away":base}
    a,b=lagged_join([target],g)
    assert len(a)==1 and not b
    g[(add_day("2019-02-01",-1),"BOS","NYK")]={"home":{f:900 for f in FIELDS},"away":{f:900 for f in FIELDS}}
    c,_=lagged_join([target],g)
    assert a[0]==c[0],"YESTERDAY_INFORMATION_LEAKED"
    assert a[0]["home_box_last_date"]<"2019-01-31"
    print("TEAM_STATS_LAG_JOIN_SELF_TEST_PASS")

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--self-test",action="store_true")
    arg=parser.parse_args()
    if arg.self_test:return self_test()
    games,_,_=assemble()
    baseline,skips=produce(games)
    box=build_boxscores(games)
    rows,reasons=lagged_join(baseline,box)
    split={"train":[r for r in rows if r["split"]=="train"],
           "validation":[r for r in rows if r["split"]=="validation"],
           "sealed_holdout":[r for r in rows if r["split"]=="sealed_holdout"]}
    if len(rows)<14000 or len(split["train"])<11000:raise RuntimeError("INSUFFICIENT_SOURCE_COVERAGE")
    from export_nba_train_ready import MODEL_COLUMNS
    fields=MODEL_COLUMNS+[x for x in STAT_COLUMNS if not x.endswith("_date")]
    OUT_DIR.mkdir(parents=True,exist_ok=True)
    artifacts={}
    for part in ("train","validation"):
        path=OUT_DIR/f"{part}_team_enriched.csv"
        with path.open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
            writer.writeheader();writer.writerows(split[part])
        # no train/test leakage, only allowed columns
        with path.open(newline="",encoding="utf-8") as f:
            rr=csv.DictReader(f)
            assert rr.fieldnames==fields
            reread=list(rr)
        if len(reread)!=len(split[part]):raise RuntimeError("OUTPUT_ROW_COUNT_MISMATCH")
        artifacts[part]={"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"rows":len(reread)}
    manifest={
        "status":"RESEARCH_TRAINING_INPUT_VALIDATED_TECHNICALLY",
        "source_license_and_publication_time_unverified":True,
        "feature_creation_embargo_days":EMBARGO_DAYS,
        "kaggle_team_file":"csv/team_boxscores.csv",
        "tri_route_label_games":len(games),
        "source_score_matched_team_games":len(box),
        "feature_rows":len(rows),"split_counts":{k:len(v) for k,v in split.items()},
        "train_validation_artifacts":artifacts,"field_names":fields,
        "holdout_exported":False,"holdout_used_for_fit":False,
        "target_game_boxscore_never_used":True,
        "boxscore_history_rejects":dict(reasons),
        "score_history_rejects":skips,
        "production_dataset_modified":False
    }
    (OUT_DIR/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print("NBA_TEAM_ENRICHED_READY "+json.dumps(manifest,sort_keys=True),flush=True)
if __name__=="__main__":main()
