#!/usr/bin/env python3
"""NBA player injury cross-season feature ablation on actual reported pregame snapshots.

Requires 2024-25 and 2025-26 sportsdataverse injury parquet, player NBA
boxscore-derived game logs. No historical bookmaker odds are ever assumed.
Archives' report_datetime is presumed Eastern publication/version time, not
independently HTTP verified; study findings NOT production-certifying.
"""
from __future__ import annotations
import argparse, json, math, hashlib
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
import pandas as pd

TEAMS={
"ATL":"Atlanta Hawks","BOS":"Boston Celtics","BKN":"Brooklyn Nets",
"CHA":"Charlotte Hornets","CHI":"Chicago Bulls","CLE":"Cleveland Cavaliers",
"DAL":"Dallas Mavericks","DEN":"Denver Nuggets","DET":"Detroit Pistons","GSW":"Golden State Warriors",
"HOU":"Houston Rockets","IND":"Indiana Pacers","LAC":"LA Clippers","LAL":"Los Angeles Lakers",
"MEM":"Memphis Grizzlies","MIA":"Miami Heat","MIL":"Milwaukee Bucks","MIN":"Minnesota Timberwolves",
"NOP":"New Orleans Pelicans","NYK":"New York Knicks","OKC":"Oklahoma City Thunder","ORL":"Orlando Magic",
"PHI":"Philadelphia 76ers","PHX":"Phoenix Suns","POR":"Portland Trail Blazers","SAC":"Sacramento Kings",
"SAS":"San Antonio Spurs","TOR":"Toronto Raptors","UTA":"Utah Jazz","WAS":"Washington Wizards",
}
T_NAME={v.lower():k for k,v in TEAMS.items()}
STATUS={"Out":0.0,"Doubtful":.05,"Questionable":.48,"Probable":.89,"Available":1.0}
def clean_team(t):
    if not isinstance(t,str):return None
    t=t.upper().strip()
    if t=="BRK":return "BKN"
    if t=="PHO":return "PHX"
    if t=="CHO":return "CHA"
    return t
def ridge(x,y,alpha):
    avg=x.mean(0);sd=x.std(0);sd[sd<1e-10]=1.
    z=(x-avg)/sd
    xx=np.column_stack((np.ones(len(x)),z))
    reg=np.eye(xx.shape[1])*alpha;reg[0,0]=0
    beta=np.linalg.solve(xx.T@xx+reg,xx.T@y)
    return avg,sd,beta
def forecast(x,m):
    avg,sd,beta=m
    return np.column_stack((np.ones(len(x)),(x-avg)/sd))@beta
def stats(y,p):
    return {"MAE":round(float(np.mean(abs(y-p))),5),"RMSE":round(float(np.sqrt(np.mean((y-p)**2))),5)}
def probscore(y,mu,sigma,threshold):
    from math import erf,sqrt
    p=np.array([max(1e-8,min(1-1e-8,(1+erf((x-threshold)/(sigma*sqrt(2))))/2)) for x in mu])
    t=np.asarray(y>threshold,float)
    return {"Brier":round(float(np.mean((p-t)**2)),6),
            "LogLoss":round(float(np.mean(-t*np.log(p)-(1-t)*np.log(1-p))),6)}
def main(args):
    hist=defaultdict(list);points=defaultdict(float);state={}
    for path in (args.players_2025,args.players_2026):
        df=pd.read_csv(path,low_memory=False)
        for r in df.itertuples(index=False):
            try:
                d=str(getattr(r,"Date"));team=clean_team(str(getattr(r,"Team")));opp=clean_team(str(getattr(r,"Opp")))
                pid=str(int(getattr(r,"ID")));mins=float(getattr(r,"Minutes"));pts=float(getattr(r,"Points"))
                if not (team in TEAMS and opp in TEAMS and team!=opp and 0<=mins<=65 and 0<=pts<=100):continue
                if not ("2024-10-22"<=d<="2025-04-13" or "2025-10-21"<=d<="2026-04-12"):continue
                if (d,team,opp,pid) in state:continue
                state[(d,team,opp,pid)]=True
                points[(d,team,opp)]+=pts
                hist[pid].append((d,mins,pts,team))
            except (ValueError,TypeError,AttributeError,OverflowError):continue
    for p in hist:hist[p].sort()
    rows=[];report_counts={}
    for tag,path in (("2025",args.injury_2025),("2026",args.injury_2026)):
        frame=pd.read_parquet(path)
        frame["game_date"]=pd.to_datetime(frame["game_date"],errors="coerce")
        frame["report_datetime"]=pd.to_datetime(frame["report_datetime"],errors="coerce")
        frame=frame.dropna(subset=["game_date","report_datetime","report_matchup"])
        frame=frame[frame["game_date"].dt.strftime("%Y-%m-%d").between("2024-10-22" if tag=="2025" else "2025-10-21","2025-04-13" if tag=="2025" else "2026-04-12")]
        # Previous-day 23:59 ET is safely earlier than the following day's
        # NBA tipoff. This is an archived VERSION TIME, not proven HTTP availability.
        cutoff=frame["game_date"]-pd.Timedelta(minutes=1)
        frame=frame[(frame["report_datetime"]<=cutoff)&(frame["report_datetime"]>=frame["game_date"]-pd.Timedelta(days=3))]
        recent=frame.groupby(["game_date","report_matchup"])["report_datetime"].transform("max")
        frame=frame[frame["report_datetime"]==recent]
        report_counts[tag]={"rows_asof":len(frame),"matchups":int(frame.groupby(["game_date","report_matchup"]).ngroups)}
        for (date_,matchup),group in frame.groupby(["game_date","report_matchup"],sort=False):
            d=date_.strftime("%Y-%m-%d")
            try:
                away,home=str(matchup).split("@")
                home=clean_team(home);away=clean_team(away)
                if home not in TEAMS or away not in TEAMS:continue
                if (d,home,away) not in points or (d,away,home) not in points:continue
                side_rows={home:[],away:[]};not_submitted=set()
                for r in group.itertuples(index=False):
                    t=T_NAME.get(str(getattr(r,"team","")).lower().strip())
                    if t not in side_rows:continue
                    reason=str(getattr(r,"reason","") or "")
                    if "NOT YET SUBMITTED" in reason.upper():
                        not_submitted.add(t)
                    side_rows[t].append(r)
                if not_submitted or not all(side_rows[t] for t in (home,away)):continue
                items={home:[],away:[]}
                for t in (home,away):
                    for r in side_rows[t]:
                        st=str(getattr(r,"current_status",""))
                        if st not in STATUS:continue
                        raw=getattr(r,"person_id",None)
                        if pd.isna(raw):continue
                        try:pid=str(int(raw))
                        except (ValueError,TypeError,OverflowError):continue
                        items[t].append((pid,st))
                rows.append((d,home,away,points[(d,home,away)]-points[(d,away,home)],
                             points[(d,home,away)]+points[(d,away,home)],items))
            except (ValueError,TypeError):continue
    data=sorted(rows,key=lambda x:(x[0],x[1],x[2]))
    # Update team history at end of each date; avoid scores from same-day matches.
    team_history=defaultdict(list);eligible=[];excluded=Counter()
    byday=defaultdict(list)
    for r in data:byday[r[0]].append(r)
    for day in sorted(byday):
        onday=[]
        for d,h,a,margin,total,items in byday[day]:
            if len(team_history[h])<3 or len(team_history[a])<3:
                excluded["team_history_lt3"]+=1;continue
            base=[float(np.mean([v[0] for v in team_history[h][-7:]])),float(np.mean([v[0] for v in team_history[a][-7:]])),
                  float(np.mean([v[1] for v in team_history[h][-7:]])),
                  float(np.mean([v[1] for v in team_history[a][-7:]]))]
            # Minutes and past scoring are computed exclusively before target date.
            byside={}
            for t in (h,a):
                available=0.; missing=0;expected_pts=0.;count=0
                for pid,status in items[t]:
                    old=[(dt,m,p) for dt,m,p,club in hist.get(pid,[]) if dt<day and club==t]
                    if len(old)<3:
                        missing+=1;continue
                    old=old[-8:]
                    minutes=sum(x[1] for x in old)/len(old)
                    ppg=sum(x[2] for x in old)/len(old)
                    # Difference relative to ordinary baseline assumption 90% available.
                    available+=(.9-STATUS[status])*minutes
                    expected_pts+=(.9-STATUS[status])*ppg
                    count+=1
                byside[t]=(available,expected_pts,count,missing)
                excluded["unmatched_or_lt3_minutes"]+=missing
            x=[*base,
               byside[h][0],byside[a][0],
               byside[h][1],byside[a][1]]
            eligible.append((day,margin,total,base,x))
        for d,h,a,margin,total,items in byday[day]:
            team_history[h].append((margin,total))
            team_history[a].append((-margin,total))
    # Fix base's first two entries from correctly typed tuples.
    # Separate season training, calibration and test; no holdout outcomes in fit.
    fit=[r for r in eligible if r[0]<"2025-03-01"]
    cal=[r for r in eligible if "2025-03-01"<=r[0]<="2025-04-13"]
    test=[r for r in eligible if r[0]>="2025-10-21"]
    report={"status":"BLOCKED_PENDING_PUBLICATION_AND_TRUE_NEW_HOLDOUT",
            "sources":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in map(Path,(args.injury_2025,args.injury_2026,args.players_2025,args.players_2026))},
            "snapshot_method":"latest archived report time by previous-day 23:59 ET; release not independently verified",
            "snapshot_counts":report_counts,
            "counts":{"unique_report_matched_games":len(data),"feature_eligible":len(eligible),"train_2024_25":len(fit),
                      "calibrate_2024_25":len(cal),"test_2025_26":len(test)},
            "excluded":dict(excluded),
            "trained_player_level_effect_catalog":False,
            "assumptions":"prior minutes and points weighted with frozen status availability; no causal player coefficients, true 007 historical odds, or certified publish timestamps",
            "limitations":["2025-26 outcomes already studied in earlier baseline research; not pristine for every model choice",
                           "Only report-listed players; unmatched names/ids excluded",
                           "No canonical roster missing from report interpreted as injury",
                           "Actual 007 market thresholds not available",
                           "Experimental only; prohibit production catalog from this output"],
            "promotion_allowed":False}
    if len(fit)>=200 and len(cal)>=80 and len(test)>=400:
        report["result"]={}
        resultmeans={}
        for target,index in (("margin",1),("total",2)):
            y=np.array([r[index] for r in fit],float)
            cy=np.array([r[index] for r in cal],float)
            ty=np.array([r[index] for r in test],float)
            report["result"][target]={}
            for key,idx in (("baseline",3),("injury_proxy",4)):
                fx=np.array([r[idx] for r in fit],float)
                cx=np.array([r[idx] for r in cal],float)
                tx=np.array([r[idx] for r in test],float)
                model=ridge(fx,y,alpha=200.)
                error=cy-forecast(cx,model)
                bias=float(np.mean(error));sigma=max(float(np.std(error,ddof=1)),1.)
                pred=forecast(tx,model)+bias
                report["result"][target][key]={**stats(ty,pred),"calibration_sigma":round(sigma,3)}
                resultmeans[target,key]=(ty,pred,sigma)
            report["result"][target]["MAE_delta"]=round(report["result"][target]["injury_proxy"]["MAE"]-
                                                         report["result"][target]["baseline"]["MAE"],5)
        for key,threshold,name in (("margin",0.,"home_win"),("total",225.5,"total_over_225_5_FIXED_NOT_BOOKMAKER")):
            report["result"][name]={}
            for version in ("baseline","injury_proxy"):
                y,pred,sigma=resultmeans[key,version]
                report["result"][name][version]=probscore(y,pred,sigma,threshold)
            report["result"][name]["Brier_delta"]=round(report["result"][name]["injury_proxy"]["Brier"]-report["result"][name]["baseline"]["Brier"],6)
        report["status"]="CROSS_SEASON_RESEARCH_HOLDOUT_COMPUTED_NOT_PRODUCTION_CERTIFIED"
    else:
        report["status"]="BLOCKED_INSUFFICIENT_CROSS_SEASON_MATCHED_GAMES"
    Path(args.out).write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    for name in ("injury_2025","injury_2026","players_2025","players_2026","out"):
        ap.add_argument("--"+name.replace("_","-"),required=True)
    main(ap.parse_args())
