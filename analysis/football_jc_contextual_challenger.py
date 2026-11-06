#!/usr/bin/env python3
"""Pre-match 007 football model using measurable season/venue/form fundamentals.

NO betting price feeds are used in forecast construction. Scores are a
probability integration grid, not a selected 'safe' correct-score tip.
Season team and venue attack/defence, recency, cross-verified opponents and
schedule congestion each contribute a traceable log-intensity adjustment.

Research challenger / uncalibrated. Coefficients below are explicit regularised
starting hypotheses, not fitted model weights. No PushPlus or grading changes.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_jc_probability as core

VERSION="football-independent-season-context-v1"
PRIOR_HOME=1.42
PRIOR_AWAY=1.18
PRIOR_MATCHES=40
VENUE_PRIOR_GAMES=6
ALL_PRIOR_GAMES=10
RECENT_PRIOR_GAMES=8
MARKETS={"had":("主胜","平","客胜"),
         "hhad":("让胜","让平","让负"),
         "ttg":("0球","1球","2球","3球","4球","5球","6球","7+球")}


def stamp(raw):
    d=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("NAIVE_TIMESTAMP")
    return d.astimezone(timezone.utc)


def digest(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def capped(v,lo,hi):return max(lo,min(hi,v))


def safe_stat(scope):
    required=("total","win","draw","loss","getGoal","lossGoal","point","rank")
    if not isinstance(scope,dict) or any(type(scope.get(k)) is not int for k in required):
        raise ValueError("SEASON_STAT_MISSING_OR_NONINTEGER")
    if any(scope[k]<0 for k in required) or scope["total"]>80 or any(scope[k]>400 for k in ("getGoal","lossGoal")):
        raise ValueError("IMPOSSIBLE_SEASON_STAT")
    if scope["win"]+scope["draw"]+scope["loss"]!=scope["total"]:
        raise ValueError("SEASON_MATCH_TOTAL_MISMATCH")
    if scope["point"]!=3*scope["win"]+scope["draw"]:
        # Deductions exist in real leagues. Flag but do not invent a correction.
        pass
    return scope


def season_record(game):
    record=game.get("season_source_facts")
    if not isinstance(record,dict) or record.get("status")!="SOURCE_REPORTED_007_SEASON_PRETIP":
        raise ValueError("SEASON_OFFICIAL_SOURCE_UNAVAILABLE")
    expected_league=str(game.get("league_id_007"))
    season=record.get("season_id")
    if not isinstance(season,str) or not season:
        raise ValueError("SEASON_ID_UNKNOWN")
    result={}
    for side in ("home","away"):
        r=record.get(side)
        if not isinstance(r,dict):raise ValueError("SEASON_TEAM_RECORD_MISSING")
        if str(r.get("source_team_id_007"))!=str(game.get(side+"_team_id_007")):
            raise ValueError("SEASON_TEAM_ID_MISMATCH")
        if str(r.get("source_league_id_007"))!=expected_league or r.get("season_id")!=season:
            raise ValueError("SEASON_LEAGUE_OR_YEAR_MISMATCH")
        scopes=r.get("scopes") or {}
        full=safe_stat(scopes.get("ALL"))
        home=safe_stat(scopes.get("HOME"))
        away=safe_stat(scopes.get("AWAY"))
        for k in ("total","win","draw","loss","getGoal","lossGoal"):
            if full[k]!=home[k]+away[k]:
                raise ValueError("SEASON_HOME_AWAY_NOT_EQUAL_TOTAL")
        if full["total"]<3:
            raise ValueError("SEASON_TOO_SPARSE")
        result[side]={"ALL":full,"HOME":home,"AWAY":away}
    return season,result


def league_rates(games):
    """Small sample shrunk to explicit global empirical starting priors.

    Only actual source-reported season records of fixtures in this capture.
    Never borrow another competition's raw average without shrinkage.
    """
    per={}
    for game in games:
        try:season,rec=season_record(game)
        except (ValueError,TypeError,KeyError):continue
        league=(str(game.get("league_id_007")),season)
        for side in ("home","away"):
            ident=str(game.get(side+"_team_id_007"))
            if (league,ident) not in per:
                per[(league,ident)]=rec[side]
    source=defaultdict(lambda:{"home_for":0,"home_against":0,"home_games":0,
                               "away_for":0,"away_against":0,"away_games":0})
    for (league,_),scopes in per.items():
        s=source[league]
        h,a=scopes["HOME"],scopes["AWAY"]
        s["home_for"]+=h["getGoal"];s["home_against"]+=h["lossGoal"];s["home_games"]+=h["total"]
        s["away_for"]+=a["getGoal"];s["away_against"]+=a["lossGoal"];s["away_games"]+=a["total"]
    grand_home_n=sum(v["home_games"] for v in source.values())
    grand_away_n=sum(v["away_games"] for v in source.values())
    grand_h=(PRIOR_MATCHES*PRIOR_HOME+sum(v["home_for"] for v in source.values()))/(PRIOR_MATCHES+grand_home_n)
    grand_a=(PRIOR_MATCHES*PRIOR_AWAY+sum(v["away_for"] for v in source.values()))/(PRIOR_MATCHES+grand_away_n)
    rates={}
    for league,s in source.items():
        # A league represented by just one fixture is almost entirely pooled.
        h=(35*grand_h+s["home_for"]+s["away_against"])/(35+s["home_games"]+s["away_games"])
        a=(35*grand_a+s["away_for"]+s["home_against"])/(35+s["away_games"]+s["home_games"])
        rates[league]=(capped(h,.85,2.1),capped(a,.7,1.9),
                       min(s["home_games"],s["away_games"]))
    return rates,{"home":round(grand_h,4),"away":round(grand_a,4),
                  "unique_teams":len(per),"leagues":len(source)}


def season_effect(scopes,side,h_mu,a_mu):
    venue=scopes["HOME" if side=="home" else "AWAY"]
    full=scopes["ALL"]
    # Home fixture scoring baseline is (home goals, away-conceded);
    # reverse for away team. Respect which team is attacking.
    attacking_mu=h_mu if side=="home" else a_mu
    conceding_mu=a_mu if side=="home" else h_mu
    grand=(h_mu+a_mu)/2
    def estimate(key,venue_mu):
        venue_rate=(venue[key]+VENUE_PRIOR_GAMES*venue_mu)/(venue["total"]+VENUE_PRIOR_GAMES)
        full_rate=(full[key]+ALL_PRIOR_GAMES*grand)/(full["total"]+ALL_PRIOR_GAMES)
        # A common league mean is a safer reference for ALL venues.
        return .7*math.log(venue_rate/venue_mu)+.3*math.log(full_rate/grand)
    return {"attack":capped(estimate("getGoal",attacking_mu),-.48,.48),
            "concede":capped(estimate("lossGoal",conceding_mu),-.48,.48)}


def current_opponents(games):
    known={}
    for game in games:
        try:_,teams=season_record(game)
        except (ValueError,TypeError,KeyError):continue
        league=str(game["league_id_007"])
        for side in ("home","away"):
            known[(league,str(game[side+"_team_id_007"]))]=teams[side]["ALL"]
    return known


def form_effect(recent,season_all,asof,kickoff,league_id,opp_catalog,side):
    """Time-weighted last5 and per-opponent strength corrections when observed.

    Missing opponent strength is UNKNOWN, never rated league-average by fiat.
    Strongly shrink the last five because those matches overlap season stats.
    """
    if not isinstance(recent,list) or len(recent)<3 or len(recent)>5:
        raise ValueError("INSUFFICIENT_RECENT_FIVE")
    seen=set()
    total_w=0.0; attack=0.0;concede=0.0;opponents=0
    last=None
    for row in recent:
        if not isinstance(row,dict):raise ValueError("FORM_ITEM_INVALID")
        mid=str(row.get("match_id") or "")
        if not mid or mid in seen:raise ValueError("FORM_MATCH_ID_INVALID_OR_DUPLICATE")
        seen.add(mid)
        played=stamp(row.get("played_at"))
        age=(asof-played).total_seconds()/86400
        if age<.125 or played>=kickoff:raise ValueError("FORM_MATCH_NOT_FINISHED_BEFORE_CAPTURE")
        if row.get("venue") not in ("HOME","AWAY"):raise ValueError("FORM_VENUE_UNCONFIRMED")
        gf,ga=row.get("goals_for"),row.get("goals_against")
        if type(gf) is not int or type(ga) is not int or not 0<=gf<=30 or not 0<=ga<=30:
            raise ValueError("FORM_SCORE_INVALID")
        weight=2**(-age/38)
        opp=opp_catalog.get((str(league_id),str(row.get("opponent_team_id_007"))))
        if opp is not None and opp["total"]>=5:
            # Opponent attack/defence correction is capped and only applied
            # with a same-league, pre-capture opponent historical record.
            factor_d=capped((opp["lossGoal"]+8*1.35)/(opp["total"]+8)/1.35,.75,1.25)
            factor_a=capped((opp["getGoal"]+8*1.35)/(opp["total"]+8)/1.35,.75,1.25)
            gf=gf/(factor_d**.35);ga=ga/(factor_a**.35)
            opponents+=1
        attack+=weight*gf;concede+=weight*ga;total_w+=weight
        if last is None or played>last:last=played
    # Posterior blend with actual season all-venue goals, not market odds.
    all_n=max(1,season_all["total"])
    all_attack=season_all["getGoal"]/all_n
    all_concede=season_all["lossGoal"]/all_n
    avg_attack=(attack+RECENT_PRIOR_GAMES*max(.3,all_attack))/(total_w+RECENT_PRIOR_GAMES)
    avg_concede=(concede+RECENT_PRIOR_GAMES*max(.3,all_concede))/(total_w+RECENT_PRIOR_GAMES)
    da=capped(math.log(avg_attack/max(.3,all_attack)),-.19,.19)
    dd=capped(math.log(avg_concede/max(.3,all_concede)),-.19,.19)
    gap=(kickoff-last).total_seconds()/86400
    # Only a small, explicitly provisional schedule effect. Rotation, travel,
    # player minutes and injuries cannot be inferred from days alone.
    rest=capped(-.045*max(0,4-gap),-.09,0.0)
    density=sum((asof-stamp(r["played_at"])).total_seconds()<14*86400 for r in recent)
    return {"attack":da,"concede":dd,"rest_attack":rest,
            "last_kickoff_gap_days":round(gap,2),"recent14_fixture_count":density,
            "verified_opponent_strength_matches":opponents,"recent5_count":len(recent)}


def main_forecast(game,asof,rates,all_rates,opponents):
    if game.get("analysis_source_status")!="007_EMBEDDED_JSON_VALIDATED":
        raise ValueError("UNVERIFIED_007_ANALYSIS_SOURCE")
    kickoff=stamp(game["kickoff_beijing"])
    if asof>=kickoff:raise ValueError("POST_KICKOFF_MODEL_FORBIDDEN")
    season,teams=season_record(game)
    league=(str(game["league_id_007"]),season)
    h_mu,a_mu,league_sample=rates.get(league,(PRIOR_HOME,PRIOR_AWAY,0))
    home=season_effect(teams["home"],"home",h_mu,a_mu)
    away=season_effect(teams["away"],"away",h_mu,a_mu)
    hf=form_effect(game["home_last5"],teams["home"]["ALL"],asof,kickoff,
                   game["league_id_007"],opponents,"home")
    af=form_effect(game["away_last5"],teams["away"]["ALL"],asof,kickoff,
                   game["league_id_007"],opponents,"away")
    # Multiplicative team-quality adjustments in log-goals space. This is
    # deliberately auditable and shrinkage-regularised, not an odds estimate.
    log_h=math.log(h_mu)+home["attack"]+away["concede"]+hf["attack"]+af["concede"]+hf["rest_attack"]
    log_a=math.log(a_mu)+away["attack"]+home["concede"]+af["attack"]+hf["concede"]+af["rest_attack"]
    lamh=capped(math.exp(log_h),.30,3.6)
    lama=capped(math.exp(log_a),.30,3.6)
    hhad=(game.get("jc_markets") or {}).get("hhad")
    line=hhad.get("signed_home_handicap") if isinstance(hhad,dict) else None
    if line is not None and (type(line) is not int or abs(line)>12):
        raise ValueError("UNVERIFIED_JC_HANDICAP_LINE")
    had,hh,ttg,_=core.distribution(lamh,lama,line)
    vals={"had":had,"hhad":hh,"ttg":ttg}
    mk={}
    for name,labels in MARKETS.items():
        vec=vals[name]
        if vec is None:mk[name]={"status":"OFFICIAL_LINE_UNAVAILABLE","probabilities":None}
        else:
            idx=max(range(len(vec)),key=lambda x:vec[x])
            mk[name]={"status":"RESEARCH_UNCALIBRATED_INDEPENDENT",
                      "direction":labels[idx],
                      "probability":round(vec[idx],6),
                      "probabilities":{k:round(p,6) for k,p in zip(labels,vec)}}
    # Unlike older models, no 'most likely score' is advertised as a signal.
    return {"status":"RESEARCH_CANDIDATE_NOT_YET_BLIND_TESTED",
        "model_version":VERSION,"match_id":str(game["match_id"]),
        "jc_number":game.get("jc_number"),"league":game.get("league"),
        "home_team":game.get("home_team"),"away_team":game.get("away_team"),
        "kickoff_beijing":game["kickoff_beijing"],
        "goal_expectation":{"home":round(lamh,4),"away":round(lama,4),
                            "total":round(lamh+lama,4),"home_margin":round(lamh-lama,4)},
        "markets":mk,
        "factor_log_contributions":{
            "home_league_prior":round(math.log(h_mu),5),
            "away_league_prior":round(math.log(a_mu),5),
            "home_team_attack_season":round(home["attack"],5),
            "away_team_defence_season":round(away["concede"],5),
            "away_team_attack_season":round(away["attack"],5),
            "home_team_defence_season":round(home["concede"],5),
            "home_recent_attack":round(hf["attack"],5),
            "away_recent_concede":round(af["concede"],5),
            "away_recent_attack":round(af["attack"],5),
            "home_recent_concede":round(hf["concede"],5),
            "home_schedule_rest":round(hf["rest_attack"],5),
            "away_schedule_rest":round(af["rest_attack"],5)},
        "source_quality":{
            "007_verified_prematch_analysis":True,
            "season_currentpoints_source_recorded_not_independent_FT":True,
            "league_source_sample_games":league_sample,
            "home_recent5":hf["recent5_count"],"away_recent5":af["recent5_count"],
            "home_opponent_rated":hf["verified_opponent_strength_matches"],
            "away_opponent_rated":af["verified_opponent_strength_matches"],
            "home_rest_days":hf["last_kickoff_gap_days"],
            "away_rest_days":af["last_kickoff_gap_days"],
            "injury_status":game.get("injury_report_state","UNAVAILABLE"),
            "injury_adjustment":"ZERO_UNTIL_VALIDATED_PLAYER_AVAILABILITY_AND_VALUE",
            "transfers_status":(game.get("transfer_source_facts") or {}).get("status","UNAVAILABLE"),
            "transfers_impact":"UNKNOWN_NO_ARBITRARY_GOALS_WEIGHT",
            "exact_score_recommendation":"NONE",
            "market_odds_read_in_prediction":False,
            "coefficients":"PROVISIONAL_PREDECLARED_NOT_LEARNED"}
    }


def run(snapshot):
    if snapshot.get("schema_version")!="football-jc-007-v1":raise ValueError("UNVERIFIED_SNAPSHOT")
    asof=stamp(snapshot["captured_at_utc"])
    league,global_stats=league_rates(snapshot.get("games") or [])
    opponents=current_opponents(snapshot.get("games") or [])
    rows=[];rejected=0
    for game in snapshot.get("games") or []:
        try:row=main_forecast(game,asof,league,global_stats,opponents)
        except (ValueError,KeyError,TypeError,OverflowError,ZeroDivisionError) as error:
            rejected+=1
            row={"match_id":str(game.get("match_id")),"jc_number":game.get("jc_number"),
                 "status":"SOURCE_QUALITY_BLOCKED","reason":str(error)[:155]}
        rows.append(row)
    return {"schema_version":VERSION,"mode":"RESEARCH_ONLY_NO_PUSH_OR_AUTO_PROMOTION",
       "input_snapshot_sha256":digest(snapshot),"capture_utc":asof.isoformat(),
       "model":VERSION,"calibration_status":"UNTRAINED_WEIGHTS_PROSPECTIVE_TEST_REQUIRED",
       "no_odds_used_in_prediction":True,"no_exact_score_recommendation":True,
       "league_base_estimation":global_stats,
       "game_count":len(rows),"ready":len(rows)-rejected,"quarantined":rejected,
       "games":rows}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    raw=Path(a.snapshot).read_bytes()
    if not raw or len(raw)>25_000_000:raise ValueError("SNAPSHOT_SIZE_INVALID")
    result=run(json.loads(raw))
    dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_INDEPENDENT_CONTEXT_CHALLENGER",json.dumps({
        "games":result["game_count"],"ready":result["ready"],
        "quarantined":result["quarantined"]},sort_keys=True))


if __name__=="__main__":main()
