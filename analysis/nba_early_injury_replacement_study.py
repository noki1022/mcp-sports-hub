#!/usr/bin/env python3
"""P0 2022-24 historical injury + prior-only rotation replacement paired study.

Research only: versioned official archives + actual player-game minutes with
stable NBA game/player ID; never current-game minutes in a prediction feature.
Missing reports/rosters are UNKNOWN. No production coefficients produced.
"""
import argparse,hashlib,io,json,math,urllib.request
from collections import defaultdict,Counter
import numpy as np
import pandas as pd

STATUS={"Out":0,"Doubtful":.05,"Questionable":.48,"Probable":.89,"Available":1.}
TEAM_NAME={"Atlanta Hawks":"ATL","Boston Celtics":"BOS","Brooklyn Nets":"BKN",
"Charlotte Hornets":"CHA","Chicago Bulls":"CHI","Cleveland Cavaliers":"CLE",
"Dallas Mavericks":"DAL","Denver Nuggets":"DEN","Detroit Pistons":"DET",
"Golden State Warriors":"GSW","Houston Rockets":"HOU","Indiana Pacers":"IND",
"Los Angeles Clippers":"LAC","LA Clippers":"LAC","Los Angeles Lakers":"LAL",
"Memphis Grizzlies":"MEM","Miami Heat":"MIA","Milwaukee Bucks":"MIL",
"Minnesota Timberwolves":"MIN","New Orleans Pelicans":"NOP","New York Knicks":"NYK",
"Oklahoma City Thunder":"OKC","Orlando Magic":"ORL","Philadelphia 76ers":"PHI",
"Phoenix Suns":"PHX","Portland Trail Blazers":"POR","Sacramento Kings":"SAC",
"San Antonio Spurs":"SAS","Toronto Raptors":"TOR","Utah Jazz":"UTA","Washington Wizards":"WAS"}
BASE_INJ="https://github.com/sportsdataverse/sportsdataverse-data/releases/download/nba_stats_injury_report/"
BASE_LOG="https://huggingface.co/datasets/Sangameshsb/nba-game-logs/resolve/main/game_logs/"
def gid(x):
    try:return str(int(x)).zfill(10)
    except (ValueError,TypeError,OverflowError):return str(x).strip()
def load(url):
    req=urllib.request.Request(url,headers={"User-Agent":"NBA-P0-replacement-study/1.0"})
    with urllib.request.urlopen(req,timeout=55) as r:d=r.read(5_000_001)
    if not 1000<len(d)<=5_000_000:raise ValueError("DATA_SIZE_OUT_OF_BOUNDS")
    return pd.read_parquet(io.BytesIO(d)),hashlib.sha256(d).hexdigest()
def ridge(x,y,lam=150):
    means=x.mean(0);sd=x.std(0);sd[sd<1e-8]=1
    a=np.column_stack((np.ones(len(x)),(x-means)/sd))
    reg=np.eye(a.shape[1])*lam;reg[0,0]=0
    return means,sd,np.linalg.solve(a.T@a+reg,a.T@y)
def pred(x,fit):
    m,sd,b=fit;return np.column_stack((np.ones(len(x)),(x-m)/sd))@b
def score(y,mu,sig):
    p=np.array([.5*(1+math.erf(float(x)/(sig*math.sqrt(2)))) for x in mu])
    p=np.clip(p,1e-7,1-1e-7);actual=np.array(y>0,float)
    return {"MAE":round(float(np.mean(abs(y-mu))),5),
            "Brier":round(float(np.mean((p-actual)**2)),6),
            "LogLoss":round(float(np.mean(-(actual*np.log(p)+(1-actual)*np.log(1-p)))),6)}
def main(out):
    sources={}
    frames=[];reports=[]
    for s,year in (("2022-23",2023),("2023-24",2024)):
        player_url=BASE_LOG+"game_logs_"+s+".parquet"
        injury_url=BASE_INJ+"injury_report_"+str(year)+".parquet"
        f,h=load(player_url);j,g=load(injury_url)
        sources[s]={"players_sha256":h,"injuries_sha256":g,
                    "players_url":player_url,"injuries_url":injury_url}
        f["season_tag"]=s
        frames.append(f);reports.append(j)
    logs=pd.concat(frames,ignore_index=True)
    logs["game_date"]=pd.to_datetime(logs["game_date"]).dt.strftime("%Y-%m-%d")
    logs["game_id"]=logs["game_id"].map(gid)
    logs["player_id"]=logs["player_id"].astype("int64")
    logs["minutes"]=pd.to_numeric(logs["minutes"],errors="coerce")
    logs["pts"]=pd.to_numeric(logs["pts"],errors="coerce")
    logs=logs.dropna(subset=["minutes","pts"]).sort_values(["game_date","game_id","player_id"])
    if logs.duplicated(["game_id","player_id"]).any():raise RuntimeError("DUPLICATE_BOX_PLAYER")
    # Infer official actual score only from reciprocal basketball box rows.
    summed=logs.groupby(["game_date","game_id","team","home"],sort=False).agg(
        score=("pts","sum")).reset_index()
    fixtures={}
    for (day,g),f in summed.groupby(["game_date","game_id"]):
        if len(f)!=2 or set(f["home"].astype(str)) not in ({"True","False"},{"1","0"}):continue
        h=f[f["home"].astype(str).isin(["True","1"])]
        a=f[f["home"].astype(str).isin(["False","0"])]
        if len(h)!=1 or len(a)!=1:continue
        fixtures[(day,g)]=(str(h.iloc[0]["team"]),str(a.iloc[0]["team"]),
                              float(h.iloc[0]["score"]-a.iloc[0]["score"]))
    hist=defaultdict(list)
    for r in logs.itertuples(index=False):
        hist[(str(r.team),int(r.player_id))].append((r.game_date,float(r.minutes),float(r.pts)))
    for h in hist.values():h.sort()
    # Select most recent official report strictly BEFORE nominal calendar-day
    # boundary. Never consider reports missing from the archived snapshot.
    report=defaultdict(dict)
    audit=Counter()
    for frame in reports:
        frame=frame.copy()
        frame["game_date"]=pd.to_datetime(frame["game_date"],errors="coerce")
        frame["report_datetime"]=pd.to_datetime(frame["report_datetime"],errors="coerce")
        frame=frame.dropna(subset=["game_date","report_datetime","game_id"])
        frame=frame[(frame["report_datetime"]<frame["game_date"]) &
                    (frame["report_datetime"]>=frame["game_date"]-pd.Timedelta(days=3))]
        if frame.empty:continue
        latest=frame.groupby(["game_id","game_date"])["report_datetime"].transform("max")
        frame=frame[frame["report_datetime"]==latest]
        for (raw_id,dt),subset in frame.groupby(["game_id","game_date"],sort=False):
            key=(dt.strftime("%Y-%m-%d"),gid(raw_id))
            if key not in fixtures:continue
            home,away,_=fixtures[key]
            teams={home:[],away:[]};invalid=set()
            for r in subset.itertuples(index=False):
                team=TEAM_NAME.get(str(r.team).strip())
                if team not in teams:continue
                reason=str(r.reason or "")
                status=str(r.current_status or "")
                if "NOT YET SUBMITTED" in reason.upper() or status not in STATUS:
                    invalid.add(team);continue
                try:person=int(r.person_id)
                except (ValueError,TypeError,OverflowError):invalid.add(team);continue
                teams[team].append((person,status))
            if invalid or not teams[home] or not teams[away]:
                audit["incomplete_report"]+=1;continue
            if key in report:raise ValueError("DUPLICATE_GAME_REPORT")
            report[key]=teams
    team_history=defaultdict(list);samples=[];no_report=0
    days=defaultdict(list)
    for (day,g),(h,a,m) in fixtures.items():days[day].append((g,h,a,m))
    for day in sorted(days):
        for g,h,a,margin in days[day]:
            teams=report.get((day,g))
            if teams is None:no_report+=1;continue
            if len(team_history[h])<3 or len(team_history[a])<3:continue
            base=[float(np.mean(team_history[h][-7:])),
                  float(np.mean(team_history[a][-7:]))]
            injury=[]
            for t in (h,a):
                injured_minutes=injured_points=0.
                for pid,status in teams[t]:
                    history=hist.get((t,pid),[])
                    older=[(m,p) for d,m,p in history if d<day][-8:]
                    if len(older)<3:continue
                    injury_weight=0.90-STATUS[status]
                    injured_minutes+=injury_weight*sum(m for m,p in older)/len(older)
                    injured_points+=injury_weight*sum(p for m,p in older)/len(older)
                # Replacement depth depends on previous games only and is based
                # on players with usual bench minutes, never a box from target game.
                bench=[]
                for (club,pid),history in hist.items():
                    if club!=t:continue
                    older=[m for d,m,p in history if d<day][-6:]
                    if len(older)<3:continue
                    avg=sum(older)/len(older)
                    if 5<=avg<22:bench.append(avg)
                bench_depth=sum(sorted(bench,reverse=True)[:5])/80 if bench else 0.
                injury.append((injured_minutes/40,injured_points/15,
                    min(bench_depth,2.0),injured_minutes/40/(1+min(bench_depth,2.0))))
            x=base+[injury[0][0]-injury[1][0],
                    injury[0][1]-injury[1][1],
                    injury[0][3]-injury[1][3]]
            samples.append((day,margin,base,x))
        for g,h,a,margin in days[day]:
            team_history[h].append(margin)
            team_history[a].append(-margin)
    fit=[r for r in samples if r[0]<"2023-02-01"]
    cal=[r for r in samples if "2023-02-08"<=r[0]<="2023-04-09"]
    test=[r for r in samples if "2023-10-24"<=r[0]<="2024-04-15"]
    report_obj={"source_hashes":sources,"count":{"fixtures":len(fixtures),"published_both_team_reports":len(report),
            "feature_eligible":len(samples),"fit_2022_23":len(fit),"cal_2022_23":len(cal),"test_2023_24":len(test)},
        "rejected":{**audit,"missing_report":no_report},
        "historical_release_time_http_verified":False,
        "official_pre_tip_reconciliation_verified":False,
        "replacement_features_are_causal_player_effects":False,
        "model_production_approved":False,
        "model_target":"home_minus_away_final_margin",
        "features":"prior-only team margin, status-weighted past minutes/points, team-specific bench depth and replacement-adjusted absence",
        "status":"BLOCKED_INSUFFICIENT_GAME_PAIRS"}
    if len(fit)>=150 and len(cal)>=90 and len(test)>=400:
        metrics={};array={}
        for label,idx in (("team_form_only",2),("plus_injury_replacement",3)):
            x=np.array([r[idx] for r in fit]);y=np.array([r[1] for r in fit])
            m=ridge(x,y)
            cx=np.array([r[idx] for r in cal]);cy=np.array([r[1] for r in cal])
            residual=cy-pred(cx,m)
            bias=float(residual.mean());sigma=max(float(residual.std(ddof=1)),1.)
            ty=np.array([r[1] for r in test])
            prediction=pred(np.array([r[idx] for r in test]),m)+bias
            metrics[label]=score(ty,prediction,sigma)
            array[label]=prediction
        report_obj["test_metrics"]=metrics
        report_obj["injury_minus_baseline_mae"]=round(metrics["plus_injury_replacement"]["MAE"]-metrics["team_form_only"]["MAE"],5)
        report_obj["injury_minus_baseline_brier"]=round(metrics["plus_injury_replacement"]["Brier"]-metrics["team_form_only"]["Brier"],6)
        report_obj["status"]="EARLY_CROSS_SEASON_RESEARCH_COMPLETED_NOT_PRODUCTION_CERTIFIED"
    from pathlib import Path
    Path(out).write_text(json.dumps(report_obj,indent=2,ensure_ascii=False)+"\n")
    print("P0_EARLY_REPLACEMENT_STUDY",json.dumps({k:v for k,v in report_obj.items() if k not in ("source_hashes","rejected")}))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True);a=p.parse_args();main(a.out)
