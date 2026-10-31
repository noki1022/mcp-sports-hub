#!/usr/bin/env python3
"""2024-25 NBA injury-versus-baseline chronological research comparison.

Uses frozen previous-calendar-day 05PM ET *nominal* injury report snapshot.
Nominal time is not a verified first-publication time; results are
RESEARCH ONLY and cannot promote injury impact probabilities.
"""
import argparse,csv,hashlib,json,math,statistics
from collections import defaultdict,Counter
from datetime import datetime,timedelta
from pathlib import Path
import unicodedata,re
import numpy as np

TEAM={
"ATL":"Atlanta Hawks","BOS":"Boston Celtics","BKN":"Brooklyn Nets","BRK":"Brooklyn Nets","CHA":"Charlotte Hornets","CHO":"Charlotte Hornets",
"CHI":"Chicago Bulls","CLE":"Cleveland Cavaliers","DAL":"Dallas Mavericks","DEN":"Denver Nuggets","DET":"Detroit Pistons","GSW":"Golden State Warriors",
"HOU":"Houston Rockets","IND":"Indiana Pacers","LAC":"LA Clippers","LAL":"Los Angeles Lakers","MEM":"Memphis Grizzlies","MIA":"Miami Heat",
"MIL":"Milwaukee Bucks","MIN":"Minnesota Timberwolves","NOP":"New Orleans Pelicans","NYK":"New York Knicks","OKC":"Oklahoma City Thunder",
"ORL":"Orlando Magic","PHI":"Philadelphia 76ers","PHX":"Phoenix Suns","POR":"Portland Trail Blazers","SAC":"Sacramento Kings",
"SAS":"San Antonio Spurs","TOR":"Toronto Raptors","UTA":"Utah Jazz","WAS":"Washington Wizards",
}
NAME_TEAM={re.sub(r"[^a-z]","",v.lower()):k for k,v in TEAM.items()}
NAME_TEAM.update({"brooklynnets":"BKN","charlottehornets":"CHA","laclipppers":"LAC"})
STATUS={"Out":0.0,"Doubtful":0.05,"Questionable":0.48,"Probable":0.89,"Available":1.0}

def norm(s):
    s=unicodedata.normalize("NFKD",str(s or "")).casefold()
    s="".join(x for x in s if not unicodedata.combining(x))
    s=re.sub(r"\b(jr|sr|ii|iii|iv|v)\b","",s)
    return " ".join(re.sub(r"[^a-z ]"," ",s).split())

def pname(s):
    if "," in str(s):
        a,b=s.split(",",1);s=b+" "+a
    return norm(s)

def rows(path):
    with open(path,encoding="utf-8-sig",newline="") as h:
        yield from csv.DictReader(h)

def decode_date(s):
    return datetime.strptime(s,"%m/%d/%Y").date().isoformat()

def fit_ridge(X,y,alpha=100.0):
    m=X.mean(axis=0); sd=X.std(axis=0);sd[sd<1e-9]=1
    z=(X-m)/sd
    A=np.column_stack([np.ones(len(z)),z])
    penalty=np.eye(A.shape[1])*alpha;penalty[0,0]=0
    beta=np.linalg.solve(A.T@A+penalty,A.T@y)
    return (m,sd,beta)
def predict(X,model):
    m,sd,b=model
    return np.column_stack((np.ones(len(X)),(X-m)/sd))@b

def main(player_path,injury_path,out):
    # Played box rows ONLY; missing row is not necessarily confirmed injured.
    played=defaultdict(dict); scores=defaultdict(float); player_hist=defaultdict(list)
    invalid=Counter(); duplicates=set()
    for r in rows(player_path):
        try:
            day=r["Date"];datetime.fromisoformat(day)
            team=r["Team"].upper();opp=r["Opp"].upper()
            minute=float(r["Minutes"]);points=float(r["Points"])
            pid=r["ID"];name=norm(r["Player"])
            if not pid or not name or team not in TEAM or opp not in TEAM or team==opp or not 0<=minute<=65 or not 0<=points<=100:raise ValueError()
            k=(day,team,opp,pid)
            if k in duplicates:invalid["duplicate_played_row"]+=1;continue
            duplicates.add(k)
            played[(day,team,opp)][pid]=(name,minute,points)
            scores[(day,team,opp)]+=points
            player_hist[(team,name)].append((day,minute))
        except (KeyError,ValueError,TypeError):invalid["invalid_player_box"]+=1
    # For membership and previous-minute averages only use older game dates.
    for k in player_hist:player_hist[k].sort()
    # One nominal previous-day 5PM snapshot per player per matchup, never a postgame version.
    report=defaultdict(dict);state=defaultdict(set);lineups=defaultdict(set)
    invalid_injury=Counter()
    for r in rows(injury_path):
        try:
            gd=decode_date(r["game_date"])
            prev=(datetime.fromisoformat(gd).date()-timedelta(days=1)).isoformat()
            if (r["snapshot_date"],r["snapshot_time"])!=(prev,"05PM"):continue
            matchup=r["matchup"]
            if "@" not in matchup:continue
            away,home=matchup.split("@",1)
            if home not in TEAM or away not in TEAM:continue
            team=NAME_TEAM.get(re.sub(r"[^a-z]","",r["team"].lower()))
            if team not in (home,away):invalid_injury["unknown_team"]+=1;continue
            key=(gd,home,away,team)
            if r["status"]=="NOT YET SUBMITTED":state[key].add("UNSUBMITTED");continue
            if r["status"] not in STATUS or not r["player"]:invalid_injury["invalid_designation"]+=1;continue
            pname_=pname(r["player"])
            if pname_ in report[key]:invalid_injury["duplicate_injury_player"]+=1;continue
            report[key][pname_]=r["status"]
            state[key].add("PUBLISHED");lineups[key].add(pname_)
        except (KeyError,ValueError,TypeError):invalid_injury["invalid_row"]+=1
    # True results built from reciprocal player-scoring boxes, NOT from odds.
    fixtures={}
    for (day,team,opp),points in scores.items():
        if (day,opp,team) not in scores:continue
        pair=tuple(sorted((team,opp)));key=(day,*pair)
        # Whether home can be recovered from verified injury report matchup.
        matches=[(d,h,a) for d,h,a,t in report if d==day and set((h,a))==set(pair)]
        if len(set(matches))!=1:continue
        d,h,a=matches[0]
        home=(day,h,a);away=(day,a,h)
        if home not in scores or away not in scores:continue
        fixtures[(day,h,a)]={
            "margin":scores[home]-scores[away],
            "total":scores[home]+scores[away]}
    byday=defaultdict(list)
    for (day,h,a),res in fixtures.items():byday[day].append((h,a,res))
    team_history=defaultdict(list)
    sample=[];excluded=Counter()
    for day in sorted(byday):
        batch=[]
        for h,a,res in byday[day]:
            # Missing snapshot or unsubmitted is UNKNOWN, not empty designation.
            hm=(day,h,a,h);am=(day,h,a,a)
            if "PUBLISHED" not in state[hm] or "PUBLISHED" not in state[am] or "UNSUBMITTED" in state[hm] or "UNSUBMITTED" in state[am]:
                excluded["missing_published_snapshot"]+=1;continue
            if len(team_history[h])<3 or len(team_history[a])<3:
                excluded["insufficient_prior_team_games"]+=1;continue
            avg=lambda vals:sum(vals[-7:])/len(vals[-7:])
            x=[avg(team_history[h])-avg(team_history[a]),
               avg(team_history[h]),avg(team_history[a])]
            # Mean historical minutes for previously played games only; never current box stats.
            injured=[]
            for team,key,sign in ((h,hm,1),(a,am,-1)):
                impact=0.0;missing_ids=0
                for name,st in report[key].items():
                    history=[mins for date,mins in player_hist.get((team,name),[]) if date<day]
                    if len(history)<3:
                        missing_ids+=1;continue
                    # A minutes-missing proxy, not a causal per-player impact coefficient.
                    impact+=(1-STATUS[st])*sum(history[-7:])/len(history[-7:])
                injured.append(impact)
                excluded["unmatched_injury_name"]+=missing_ids
            x_plus=x+injured
            batch.append((day,h,a,x,x_plus,res["margin"],res["total"]))
        # Avoid label leakage: update rolling team form after *all* same-day games.
        for h,a,res in byday[day]:
            team_history[h].append(res["margin"])
            team_history[a].append(-res["margin"])
        sample.extend(batch)
    train=[r for r in sample if r[0]<"2025-02-01"]
    embargo=[r for r in sample if "2025-02-01"<=r[0]<"2025-03-01"]
    test=[r for r in sample if "2025-03-01"<=r[0]<="2025-04-13"]
    result={"status":"BLOCKED_FROM_PRODUCTION_RESEARCH_ONLY","input_files":{"players_sha256":hashlib.sha256(Path(player_path).read_bytes()).hexdigest(),"injuries_sha256":hashlib.sha256(Path(injury_path).read_bytes()).hexdigest()},
            "counts":{"reciprocal_scored_games":len(fixtures),"fit":len(train),"embargo":len(embargo),"test":len(test)},
            "excluded":dict(excluded),"invalid_player":dict(invalid),"invalid_injury":dict(invalid_injury),
            "injury_snapshot":"NOMINAL_PRIOR_DAY_05PM_ET_NOT_PUBLICATION_VERIFIED",
            "features":"baseline: past-only team rolling margin; enhanced: baseline + past-only minutes weighted by nominated report status",
            "limitation":"No verified publish times; absence status not necessarily medical; no formal player replacement/minute share model; same-season research holdout already studied; no market odds",
            "promotion_allowed":False}
    if len(train)>=120 and len(test)>=80:
        result["models"]={}
        prob_forecasts={}
        calibrations={}
        for target in ("margin","total"):
            ycol=5 if target=="margin" else 6
            y=np.asarray([r[ycol] for r in train]);yt=np.asarray([r[ycol] for r in test])
            result["models"][target]={}
            for label,col in (("baseline",3),("injury_proxy",4)):
                X=np.asarray([r[col] for r in train],float)
                Xt=np.asarray([r[col] for r in test],float)
                fitted=fit_ridge(X,y)
                pred=predict(Xt,fitted)
                # Calibrate residual spread only on the embargo-era set (never on test).
                # This split was held aside from fitting; it is calibration for this
                # exploratory study, not a pristine independent production holdout.
                Xe=np.asarray([r[col] for r in embargo],float)
                ye=np.asarray([r[ycol] for r in embargo],float)
                resid=ye-predict(Xe,fitted)
                bias=float(np.mean(resid))
                sigma=float(max(np.std(resid,ddof=1),1.0))
                pred=pred+bias
                prob_forecasts[(target,label)]={"means":pred,"sigma":sigma}
                calibrations[(target,label)]={"bias":bias,"sigma":sigma}
                result["models"][target][label]={"MAE":float(np.mean(abs(yt-pred))),
                    "RMSE":float(np.sqrt(np.mean((yt-pred)**2)))}
            result["models"][target]["MAE_delta_injury_minus_baseline"]=result["models"][target]["injury_proxy"]["MAE"]-result["models"][target]["baseline"]["MAE"]
        def prob_score(target,threshold):
            key="margin" if target=="margin" else "total"
            yy=np.asarray([r[5 if key=="margin" else 6] for r in test],float)
            actual=(yy>threshold).astype(float)
            output={}
            for label in ("baseline","injury_proxy"):
                fv=prob_forecasts[(key,label)]
                p=np.array([.5*(1+math.erf((v-threshold)/(fv["sigma"]*math.sqrt(2))))
                            for v in fv["means"]],float)
                p=np.clip(p,1e-8,1-1e-8)
                output[label]={"Brier":float(np.mean((p-actual)**2)),
                               "LogLoss":float(np.mean(-(actual*np.log(p)+(1-actual)*np.log(1-p))))}
            output["Brier_delta_injury_minus_baseline"]=output["injury_proxy"]["Brier"]-output["baseline"]["Brier"]
            return output
        result["fixed_threshold_probability_research"]={
            "home_win_margin_gt_0":prob_score("margin",0.0),
            "total_over_225_5_NOT_BOOKMAKER":prob_score("total",225.5)}
        result["calibration"]="residual mean and sigma from 57 embargo-era games, never test"
        result["status"]="RESEARCH_HOLDOUT_COMPUTED_NO_PRODUCTION_PROMOTION"
    else:
        result["status"]="BLOCKED_INSUFFICIENT_MATCHED_CHRONOLOGICAL_GAMES"
    Path(out).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--players",required=True);p.add_argument("--injuries",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();main(a.players,a.injuries,a.out)
