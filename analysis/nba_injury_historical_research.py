#!/usr/bin/env python3
"""NBA injury research evidence, three sequential gates. NO production promotion.

Stage 1: audit local records (team boxes are NOT player-game logs).
Stage 2: inspect timestamped *candidate* official-report archive rows.
Stage 3a: chronological player participation study, not five-market odds test.
Stage 3b: strict paired market test, only if fully qualified forecast files exist.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,re
from collections import Counter,defaultdict
from datetime import datetime,date,timezone,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE=Path(__file__).resolve().parents[1]
ET=ZoneInfo("America/New_York")
STATUSES={"Out","Doubtful","Questionable","Probable","Available"}
MARKETS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")
PINNED_INJURY_SOURCE="Professor-Pete/2024-2025-injury_analysis@6fcf87e34c6c0bd791a1f4c0f100c0a6500ac949"
SPLIT={"fit_end_exclusive":"2025-02-01","embargo_end_exclusive":"2025-03-01","holdout_start":"2025-03-01"}

def write(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return obj

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def finite(value):
    if value is None or isinstance(value,bool): return None
    try:
        x=float(value)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError): return None

def iso(value):
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except (ValueError,TypeError):return None

def csvrows(path):
    with open(path,encoding="utf-8-sig",newline="") as h:
        yield from csv.DictReader(h)

def audit_local(out):
    stats={"files_checked":[],"team_box_rows":0,"player_rows":0,
           "valid_player_game_rows":0,"missing_player_identity":0,"duplicate_player_game":0,
           "player_availability_label_ready":False,"scope":"CHECKED_IN_REPOSITORY_ONLY"}
    keys=set()
    for p in sorted((BASE/"analysis"/"data").glob("boxscore_batch_*.json")):
        rows=json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(rows,list):raise ValueError("INVALID_BOX_BATCH")
        stats["files_checked"].append({"path":str(p.relative_to(BASE)),"sha256":sha(p),"rows":len(rows)})
        for r in rows:
            if not isinstance(r,dict):raise ValueError("INVALID_ROW")
            if not any("player_id" in v for v in (r.get("home") or {},r.get("away") or {})):
                stats["team_box_rows"]+=1;continue
            stats["player_rows"]+=1
            for v in (r.get("home") or {},r.get("away") or {}):
                pid=v.get("player_id");g=r.get("game_id")
                if not (pid and g and v.get("team")) or finite(v.get("min")) is None:
                    stats["missing_player_identity"]+=1;continue
                key=(str(g),str(pid))
                if key in keys:stats["duplicate_player_game"]+=1;continue
                keys.add(key);stats["valid_player_game_rows"]+=1
    stats["quality"]="PLAYER_LEVEL_DATA_NOT_IN_CHECKED_IN_BOX_BATCHES" if not stats["valid_player_game_rows"] else "CANDIDATE_PLAYER_ROWS_ONLY"
    stats["missing_pit_injury_labels"]=True
    return write(out,stats)

def report_clock(day,slot):
    """Filename HHAM/HHPM is hour precision; upper bound is end of that hour.

    This is an estimate of nominal issue time, NOT independently verified HTTP publication.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",str(day)):return None
    m=re.fullmatch(r"(0[1-9]|1[0-2])(AM|PM)",str(slot).strip())
    if not m:return None
    hr=int(m.group(1))%12+(12 if m.group(2)=="PM" else 0)
    try:return datetime.fromisoformat(day).replace(hour=hr,minute=59,second=59,tzinfo=ET).astimezone(timezone.utc)
    except ValueError:return None

def audit_archive(path,out):
    counts=Counter();dates=set();snapshots=set();invalid=Counter();unique=set()
    for row in csvrows(path):
        counts["rows"]+=1
        captured=report_clock(row.get("snapshot_date"),row.get("snapshot_time"))
        if captured is None:
            invalid["unknown_snapshot_clock"]+=1;continue
        game_date=row.get("game_date","").strip()
        try:
            gd=datetime.strptime(game_date,"%m/%d/%Y").date()
        except (ValueError,TypeError):
            invalid["invalid_game_date"]+=1;continue
        if captured.date()>gd+timedelta(days=2) or captured.date()<gd-timedelta(days=4):
            invalid["snapshot_far_from_game"]+=1;continue
        matchup=str(row.get("matchup","")).strip()
        if not re.fullmatch(r"[A-Z]{2,4}@[A-Z]{2,4}",matchup):
            invalid["bad_matchup"]+=1;continue
        dates.add(gd.isoformat());snapshots.add((row["snapshot_date"],row["snapshot_time"]))
        if not row.get("player") or row.get("status") not in STATUSES:
            counts["unsubmitted_or_nonplayer"]+=1;continue
        counts["candidate_player_status_rows"]+=1
        key=(row["snapshot_date"],row["snapshot_time"],game_date,matchup,row.get("team"),row["player"])
        if key in unique:invalid["duplicated_player_snapshot"]+=1
        unique.add(key)
    result={"stage":"2","source":PINNED_INJURY_SOURCE,"archive_sha256":sha(path),
            "row_counts":dict(counts),"invalid_counts":dict(invalid),
            "distinct_game_dates":len(dates),"distinct_nominal_snapshot_slots":len(snapshots),
            "publication_timestamp_verified":False,
            "nominal_report_time_is_not_HTTP_release_time":True,
            "tipoff_time_matched_from_authoritative_schedule":False,
            "fit_eligible_player_injury_rows":0,
            "status":"SOURCE_CANDIDATE_PIT_NOT_VERIFIED",
            "rule":"Historical archive slot + PDF URL + independently verified pre-tip release/fixture required before FIT"}
    return write(out,result)

def labels_audit(path,out):
    rows=list(csvrows(path)); invalid=Counter();seen=set();safe=[]
    for r in rows:
        key=(r.get("player"),r.get("team"),r.get("date"))
        if not all(key) or key in seen:invalid["missing_or_duplicate_identity"]+=1;continue
        seen.add(key)
        try:date.fromisoformat(r["date"])
        except ValueError:invalid["invalid_date"]+=1;continue
        if r.get("lead_status") not in ("Probable","Questionable","Doubtful") or r.get("played") not in ("0","1"):
            invalid["invalid_label"]+=1;continue
        safe.append(r)
    fit=[r for r in safe if r["date"]<SPLIT["fit_end_exclusive"]]
    embargo=[r for r in safe if SPLIT["fit_end_exclusive"]<=r["date"]<SPLIT["embargo_end_exclusive"]]
    test=[r for r in safe if r["date"]>=SPLIT["holdout_start"]]
    if not fit or not test or len(fit)+len(test)+len(embargo)!=len(safe):
        raise ValueError("SPLIT_NOT_VALID")
    if max(r["date"] for r in fit)>=min(r["date"] for r in test):
        raise ValueError("TEMPORAL_LEAK")
    overall=sum(int(r["played"]) for r in fit)/len(fit)
    groups=defaultdict(list)
    for r in fit:groups[r["lead_status"]].append(int(r["played"]))
    # Frozen shrink strength 20; fit is the sole estimation population.
    rates={k:(sum(v)+20*overall)/(len(v)+20) for k,v in groups.items()}
    def score(pred):
        brier=logloss=0.0
        for r in test:
            y=int(r["played"]);p=min(.999999,max(.000001,pred(r)))
            brier+=(y-p)**2
            logloss+=-y*math.log(p)-(1-y)*math.log(1-p)
        return {"n":len(test),"brier":round(brier/len(test),6),
                "logloss":round(logloss/len(test),6)}
    baseline=score(lambda r:overall)
    status=score(lambda r:rates.get(r["lead_status"],overall))
    return write(out,{"stage":"3a","source":PINNED_INJURY_SOURCE,"source_sha256":sha(path),
       "dataset_rows":len(rows),"usable_rows":len(safe),"invalid":dict(invalid),
       "partitions":{"fit":len(fit),"embargo_never_fitted":len(embargo),"test":len(test)},
       "partition_dates":SPLIT,
       "training_base_rate":round(overall,6),
       "training_only_status_rates":{k:round(v,6) for k,v in rates.items()},
       "heldout_baseline":baseline,"heldout_status_model":status,
       "delta_brier":round(status["brier"]-baseline["brier"],6),
       "qualifications":["1PM report source slot is not independently verified PDF publication time",
                         "Tipoff time was not matched; early games may violate pre-tip status",
                         "Player attendance only; not team margin / total / five betting markets",
                         "Test season overlaps earlier base-model tuning/validation; not production-eligible"],
       "eligible_for_live_player_impact_catalog":False,
       "status":"RESEARCH_ONLY_PLAYER_PARTICIPATION_OUT_OF_TIME"})

def paired_market_eval(base_path,injury_path,manifest_path,out):
    if not all(Path(p).is_file() for p in (base_path,injury_path,manifest_path)):
        return write(out,{"stage":"3b","status":"BLOCKED_MISSING_REAL_PAIRED_PRETIP_ARTIFACTS",
          "missing":[str(p) for p in (base_path,injury_path,manifest_path) if not Path(p).is_file()],
          "no_synthetic_holdout":True})
    manifest=json.loads(Path(manifest_path).read_text())
    b=list(csvrows(base_path));a=list(csvrows(injury_path))
    def unique(rows):
        keys=[(r.get("game_id"),r.get("market")) for r in rows]
        if not all(k[0] and k[1] in MARKETS for k in keys) or len(keys)!=len(set(keys)):
            raise ValueError("BAD_OR_DUPLICATED_MARKET_ID")
        return dict(zip(keys,rows))
    left,right=unique(b),unique(a)
    if left.keys()!=right.keys():raise ValueError("NOT_SAME_GAME_MARKET_PAIRS")
    if not left:raise ValueError("EMPTY_PAIRS")
    first=min(str(r["game_date"]) for r in b)
    if (str(manifest.get("fit_through",""))>=first or str(manifest.get("calibrated_through",""))>=first
        or manifest.get("historical_injury_release_verified") is not True
        or manifest.get("player_impact_independent_holdout_pass") is not True
        or not manifest.get("source_sha256")):
        raise ValueError("MISSING_INDEPENDENT_HISTORICAL_MODEL_ATTESTATION")
    scores={x:Counter() for x in ("baseline","injury")}
    paired_games=set()
    for key in sorted(left):
        x,y=left[key],right[key]
        if any(x.get(f)!=y.get(f) for f in ("game_id","market","game_date","outcome")):
            raise ValueError("PAIRED_OUTCOME_MISMATCH")
        tip=iso(x.get("tipoff_utc"))
        snap=iso(y.get("injury_release_utc"))
        generated=iso(y.get("forecast_generated_utc"))
        if any(t is None or t.tzinfo is None for t in (tip,snap,generated)):
            raise ValueError("MISSING_TIMEZONE_AWARE_SOURCE_TIMES")
        if not (snap < generated < tip):raise ValueError("POST_TIP_OR_POST_PREDICTION_LEAK")
        if x.get("game_date")<first:raise ValueError("OUT_OF_ORDER_DATE")
        truth=finite(x.get("outcome"))
        p0,p1=finite(x.get("probability")),finite(y.get("probability"))
        if truth not in (0.,1.) or any(p is None or not 0<=p<=1 for p in (p0,p1)):
            raise ValueError("INVALID_PROBABILITY_OR_RESULT")
        paired_games.add(x["game_id"])
        for label,p in (("baseline",p0),("injury",p1)):
            p=min(1-1e-10,max(1e-10,p));z=scores[label]
            z["brier_sum"]+=(truth-p)**2
            z["logloss_sum"]+=-(truth*math.log(p)+(1-truth)*math.log(1-p))
            z["n"]+=1
    if len(paired_games)<200:raise ValueError("INSUFFICIENT_INDEPENDENT_HOLDOUT_GAMES")
    result={label:{"n":s["n"],"brier":s["brier_sum"]/s["n"],
                   "logloss":s["logloss_sum"]/s["n"]} for label,s in scores.items()}
    # No automatic production promotion on a research-only test.
    return write(out,{"stage":"3b","status":"PAIRED_HOLDOUT_COMPUTED_REQUIRES_INDEPENDENT_REVIEW",
                      "unique_games":len(paired_games),"comparisons":result,
                      "manifest_sha256":sha(manifest_path),"promote_to_production":False})

def self_test():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        a=Path(td)
        rows=a/"played.csv"
        with rows.open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["player","team","date","lead_status","played"])
            w.writeheader()
            for i in range(50):
                day="2024-11-01" if i<20 else "2025-02-10" if i<30 else "2025-03-10"
                w.writerow({"player":"P"+str(i),"team":"ATL","date":day,
                            "lead_status":"Questionable" if i%2 else "Probable","played":str(i%2)})
        obj=labels_audit(rows,a/"summary.json")
        assert obj["partitions"]=={"fit":20,"embargo_never_fitted":10,"test":20}
        assert obj["eligible_for_live_player_impact_catalog"] is False
        assert report_clock("2025-01-01","01PM")<report_clock("2025-01-01","05PM")
        assert report_clock("2025-01-01","13PM") is None
        assert paired_market_eval(a/"a",a/"b",a/"c",a/"blocked.json")["status"].startswith("BLOCKED")
        fixture=a/"archive.csv"
        with fixture.open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["snapshot_date","snapshot_time","game_date","matchup","team","player","status"])
            w.writeheader();w.writerow({"snapshot_date":"2025-01-01","snapshot_time":"01PM",
                  "game_date":"01/01/2025","matchup":"MIA@ATL","team":"Atlanta Hawks",
                  "player":"Test, Player","status":"Out"})
        z=audit_archive(fixture,a/"arc.json")
        assert z["row_counts"]["candidate_player_status_rows"]==1
        assert z["fit_eligible_player_injury_rows"]==0
    print("NBA_INJURY_RESEARCH_THREE_STAGE_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--stage",choices=["local","archive","attendance","market","self-test"],required=True)
    p.add_argument("--source");p.add_argument("--baseline");p.add_argument("--enhanced");p.add_argument("--manifest")
    p.add_argument("--out",default="nba_injury_evidence_result.json")
    args=p.parse_args()
    if args.stage=="self-test":self_test();return
    if args.stage=="local":obj=audit_local(args.out)
    elif args.stage=="archive":
        if not args.source:raise SystemExit("HISTORICAL_ARCHIVE_REQUIRED")
        obj=audit_archive(args.source,args.out)
    elif args.stage=="attendance":
        if not args.source:raise SystemExit("HISTORICAL_ATTENDANCE_LABELS_REQUIRED")
        obj=labels_audit(args.source,args.out)
    else:obj=paired_market_eval(args.baseline or "",args.enhanced or "",args.manifest or "",args.out)
    print(json.dumps({k:obj.get(k) for k in ("stage","status","quality","partitions","row_counts") if k in obj},ensure_ascii=False))
if __name__=="__main__":main()
