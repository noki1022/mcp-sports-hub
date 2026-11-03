#!/usr/bin/env python3
"""Audit ACTUAL recently completed NBA fixtures against archived pretip injuries.

This is a retrospective, frozen-forecast EVALUATION, not a newly generated
injury-adjusted prediction. Model and report/source timestamps must predate
tip. Incomplete official reports remain UNKNOWN, not "no injury".
An injury-model uplift is null unless a genuinely pretip frozen paired
candidate probability exists. No network, code refit, scores before tip,
live workflow, Crown/Jingcai collection or PushPlus.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse, hashlib, json, math

BJ=ZoneInfo("Asia/Shanghai")
ET=ZoneInfo("America/New_York")
MARKETS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL",
         "CROWN_HANDICAP","CROWN_TOTAL")
SCHEMA="nba-recent-settled-injury-frozen-outcome-audit-v1"

def clock(x):
    if not isinstance(x,str):return None
    try:
        d=datetime.fromisoformat(x.replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:return None

def num(x):
    if isinstance(x,bool) or x is None:return None
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def unique(rows,kind):
    d={}
    for row in rows:
        k=str(row.get("game_id") or "")
        if not k or k in d:raise ValueError("DUPLICATE_OR_MISSING_"+kind+"_GAME_ID")
        d[k]=row
    return d

def summary(rows):
    n=len(rows)
    return {"n":n,"hits":sum(bool(x["hit"]) for x in rows),
            "accuracy":round(sum(bool(x["hit"]) for x in rows)/n,6) if n else None,
            "brier":round(sum(x["brier"] for x in rows)/n,8) if n else None}

def grade(mkt,row,home,away):
    if not isinstance(row,dict) or row.get("status")!="DIRECTION_ISSUED":
        return None
    probability=num(row.get("model_direction_probability"))
    if probability is None or not 0<probability<1:return None
    direction=row.get("direction")
    if mkt=="JINGCAI_WIN":
        observed="HOME_WIN" if home>away else "AWAY_WIN" if away>home else None
    elif mkt.endswith("HANDICAP"):
        handicap=num(row.get("signed_home_handicap"))
        if handicap is None:return None
        # Critical: signed HOME handicap, not raw positive HOME-GIVES Crown line.
        v=home-away+handicap
        observed="HOME_COVER" if v>0 else "AWAY_COVER" if v<0 else None
    elif mkt.endswith("TOTAL"):
        line=num(row.get("line"))
        if line is None:return None
        v=home+away-line
        observed="OVER" if v>0 else "UNDER" if v<0 else None
    else:raise ValueError("UNKNOWN_MARKET")
    if observed is None or direction not in (
        ("HOME_WIN","AWAY_WIN") if mkt=="JINGCAI_WIN" else
        ("HOME_COVER","AWAY_COVER") if mkt.endswith("HANDICAP") else
        ("OVER","UNDER")):
        return None
    hit=direction==observed
    return {"direction":direction,"observed":observed,"hit":hit,
            "probability":round(probability,9),
            "brier":(1-probability)**2 if hit else probability**2,
            "line":row.get("line"),
            "signed_home_handicap":row.get("signed_home_handicap")}

def context_features(ctx,tip,prediction_time):
    time=clock(ctx.get("source_captured_at_utc"))
    et=tip.astimezone(ET).date().isoformat()
    source_ok=(time is not None and time<=prediction_time and time<tip and
               ctx.get("source_date_matches_tip") is True and
               ctx.get("source_report_et_date")==et and
               ctx.get("capture_before_tip_verified") is True and
               ctx.get("parsed_player_ambiguity") is False)
    complete=(source_ok and ctx.get("quality") in
              ("PUBLISHED_AFFECTED","PUBLISHED_LISTED") and
              all((ctx.get(side) or {}).get("report_state")=="PUBLISHED"
                  for side in ("home","away")))
    observed={"home":[],"away":[]}
    counts=Counter()
    if source_ok:
        for side in ("home","away"):
            # This is a SOURCE OBSERVATION even when the other team did not
            # submit a report. Only COMPLETE games enter verified subgroups.
            if (ctx.get(side) or {}).get("report_state")!="PUBLISHED":continue
            players=ctx[side].get("players") or []
            if not isinstance(players,list):raise ValueError("INVALID_INJURY_PLAYERS")
            seen=set()
            for p in players:
                name=str(p.get("name") or "").strip()
                status=p.get("status")
                if not name or name.casefold() in seen or status not in (
                    "Out","Doubtful","Questionable","Probable","Available"):
                    raise ValueError("DUPLICATE_OR_BAD_OFFICIAL_PLAYER")
                seen.add(name.casefold())
                why=str(p.get("reason") or "")
                medical=why.casefold().startswith("injury/illness")
                obs={"name":name,"status":status,"medical_reason_observed":medical}
                observed[side].append(obs)
                counts[status]+=1
                if medical and status in ("Out","Doubtful","Questionable"):
                    counts["explicit_medical_out_or_uncertain"]+=1
    return {"source_capture_valid":bool(source_ok),
            "both_teams_official_report_verified":bool(complete),
            "official_quality":ctx.get("quality"),
            "source_report_et_date":ctx.get("source_report_et_date"),
            "source_capture_utc":ctx.get("source_captured_at_utc"),
            "reported_statuses":dict(sorted(counts.items())),
            "confirmed_medical_absence_or_uncertainty_listed":bool(
                counts.get("explicit_medical_out_or_uncertain",0)),
            "official_players":observed,
            "core_player_minutes_or_oncourt_impact_verified":False,
            "no_healthy_from_unpublished_report":True}

def evaluate_day(root,day):
    base=root/"reports"/"daily"/day/"2130"
    settlement=root/"reports"/"five-market-settled"/day/"settlement.json"
    inputs={"joined":base/"titan007_priority_joined.json",
            "model":base/"nba_priority_model.json",
            "injury_shadow":base/"nba_injury_prospective_2130.json",
            "five":base/"nba_five_market_forecast.json",
            "settlement":settlement}
    if not settlement.is_file():return None
    if any(not p.is_file() for k,p in inputs.items() if k!="five"):
        return {"date":day,"source_files_present":False,
                "block_reason":"MISSING_PREGAME_INJURY_OR_MODEL_ARCHIVE",
                "recent_completed_games":len(load(settlement).get("games",[])),
                "rows":[]}
    docs={k:load(p) for k,p in inputs.items() if p.is_file()}
    if docs["settlement"].get("schema_version")!="nba-five-market-settlement-v1" or (
        docs["settlement"].get("beijing_date")!=day):
        raise ValueError("SETTLEMENT_DATE_OR_SCHEMA_MISMATCH")
    if docs["joined"].get("requested_display_date")!=day:
        raise ValueError("PRETIP_BOARD_DATE_MISMATCH")
    board=unique(docs["joined"].get("nba_cba_games",[]),"BOARD")
    models=unique(docs["model"].get("games",[]),"MODEL")
    shadow={}
    for s in docs["injury_shadow"].get("games",[]):
        key=str(s.get("007_game_id") or "")
        if not key or key in shadow:raise ValueError("DUPLICATE_INJURY_SHADOW_GAME")
        shadow[key]=s
    five=unique(docs.get("five",{}).get("games",[]),"FIVE")
    finals=unique(docs["settlement"].get("games",[]),"SETTLED")
    captures={k:sha(p) for k,p in inputs.items() if p.is_file()}
    rows=[]
    for gid,s in sorted(finals.items()):
        j=board.get(gid);m=models.get(gid);r=shadow.get(gid)
        if not j or not m or not r:
            rows.append({"game_id":gid,"eligible":False,"block_reason":"PREGAME_GAME_OR_SHADOW_MISSING"})
            continue
        if j.get("league")!="NBA" or any(
            z.get("game_id")!=gid or
            (str(z.get("nba_game_id"))!=str(j.get("nba_game_id")) and z is not r)
            for z in (s,m)):
            raise ValueError("SETTLED_AND_PRETIP_NBA_ID_CONFLICT")
        if str(r.get("game_id"))!=str(j.get("nba_game_id")):
            raise ValueError("SHADOW_AND_007_NBA_ID_MISMATCH")
        for key in ("home_team","away_team"):
            if m.get(key)!=j.get(key) or s.get(key)!=j.get(key):
                raise ValueError("HOME_AWAY_TEAM_SIDE_MISMATCH")
        if (r.get("home"),r.get("away"))!=(j.get("home_team"),j.get("away_team")):
            raise ValueError("INJURY_SHADOW_TEAM_SIDE_MISMATCH")
        tip=clock(j.get("tipoff_utc"))
        when=clock(r.get("predicted_at_utc"))
        boardtime=clock(docs["joined"].get("captured_at_utc"))
        context=m.get("injury_context") or {}
        source=clock(context.get("source_captured_at_utc"))
        if not tip or not when or not boardtime or not source or not (
            boardtime<=source<=when<tip):
            rows.append({"game_id":gid,"eligible":False,"block_reason":"INVALID_PRETIP_CAPTURE_SEQUENCE"})
            continue
        if r.get("source_report_captured_at_utc")!=context.get("source_captured_at_utc"):
            raise ValueError("FROZEN_INJURY_CONTEXT_TIMESTAMP_CONFLICT")
        hp=num(m.get("model_probability",{}).get("home"))
        frozen=num(r.get("base_home_prob"))
        if hp is None or frozen is None or not 0<hp<1 or abs(hp-frozen)>1e-8:
            raise ValueError("FROZEN_MODEL_BASELINE_PROBABILITY_MISMATCH")
        home=s.get("home_points");away=s.get("away_points")
        if any(isinstance(x,bool) or not isinstance(x,int) or not 0<=x<=250
               for x in (home,away)) or home==away:
            raise ValueError("INVALID_REAL_FINAL_SCORE")
        inj=context_features(context,tip,when)
        truth=int(home>away)
        hit=(hp>.5 and truth==1) or (hp<.5 and truth==0)
        if hp==.5:hit=False
        five_record=five.get(gid)
        five_clock=clock(docs.get("five",{}).get("analysis_generated_at_utc"))
        five_valid=bool(five_clock and boardtime<=five_clock<tip and
                        five_record and
                        five_record.get("home_team")==j.get("home_team") and
                        five_record.get("away_team")==j.get("away_team") and
                        str(five_record.get("nba_game_id"))==str(j.get("nba_game_id")))
        market_scores={key:grade(key,(five_record.get("markets") or {}).get(key),home,away)
                       for key in MARKETS} if five_valid else {key:None for key in MARKETS}
        paired=r.get("status")=="PAIRED_SHADOW_CAPTURED"
        candidate=num(r.get("injury_home_prob"))
        if paired and (candidate is None or not 0<candidate<1 or
                       not r.get("candidate_sha256")):
            raise ValueError("UNSEALED_INJURY_PAIR_ATTEMPTED_SCORE")
        if not paired and candidate is not None:
            raise ValueError("UNAPPROVED_RETROACTIVE_INJURY_PROBABILITY")
        entry={
            "game_id":gid,"nba_game_id":str(j["nba_game_id"]),
            "home_team":j["home_team"],"away_team":j["away_team"],
            "tipoff_utc":tip.isoformat(),
            "frozen_original_injury_shadow_at_utc":when.isoformat(),
            "actual_score":{"home":home,"away":away},
            "eligible":True,
            "official_2130_clock_window":bool(
                (tip.astimezone(BJ).date()-when.astimezone(BJ).date()).days==1
                and when.astimezone(BJ).hour==21
                and 30<=when.astimezone(BJ).minute<=59),
            "injury":inj,
            "original_moneyline":{"home_win_probability":round(hp,9),
                                  "hit":bool(hit),"brier":round((hp-truth)**2,9)},
            "five_market_pretip_timestamp_verified":five_valid,
            "original_five_market":market_scores,
            "injury_adjusted_paired_probability":candidate if paired else None,
            "injury_paired_research_score_eligible":bool(paired and inj["both_teams_official_report_verified"]),
            "injury_model_uplift_over_original":None,
            "note":"Retrospective score of frozen, unchanged original forecast. Injury impact not inferred."
        }
        rows.append(entry)
    return {"date":day,"source_files_present":True,"source_sha256":captures,
            "recent_completed_games":len(finals),"rows":rows,
            "five_market_prediction_timestamp_missing":not bool(
                clock(docs.get("five",{}).get("analysis_generated_at_utc")))}

def run(root,start,end):
    low=date.fromisoformat(start);high=date.fromisoformat(end)
    if high<low or (high-low).days>45:raise ValueError("INVALID_RECENT_DAY_RANGE")
    days=[];day=low
    while day<=high:
        cohort=evaluate_day(Path(root),day.isoformat())
        if cohort is not None:days.append(cohort)
        day+=timedelta(days=1)
    if not days:raise ValueError("NO_LOCAL_SETTLED_RECENT_GAME_ARCHIVES")
    allrows=[r for day in days for r in day["rows"]]
    valid=[r for r in allrows if r.get("eligible") is True]
    complete=[r for r in valid if r["injury"]["both_teams_official_report_verified"]]
    unknown=[r for r in valid if not r["injury"]["both_teams_official_report_verified"]]
    def ml(v):
        return summary([{"hit":r["original_moneyline"]["hit"],
                         "brier":r["original_moneyline"]["brier"]} for r in v])
    def five(v):
        return {key:summary([r["original_five_market"][key] for r in v
                             if r["original_five_market"][key] is not None])
                for key in MARKETS}
    paired=[r for r in valid if r["injury_paired_research_score_eligible"]]
    paired_comparison=None
    if paired:
        b=ml(paired)
        c=sum((r["injury_adjusted_paired_probability"]-
               int(r["actual_score"]["home"]>r["actual_score"]["away"]))**2
              for r in paired)/len(paired)
        paired_comparison={"paired_n":len(paired),"original_brier":b["brier"],
                           "injury_candidate_brier":round(c,8),
                           "injury_candidate_minus_original_brier":round(c-b["brier"],8),
                           "not_a_proven_production_uplift":True}
    report={
        "schema_version":SCHEMA,"date_start":start,"date_end":end,
        "cohort_days":[v["date"] for v in days],
        "completed_games_in_settlements":sum(x["recent_completed_games"] for x in days),
        "strict_frozen_baseline_evaluable_games":len(valid),
        "blocked_games":len(allrows)-len(valid),
        "blocked_reasons":dict(sorted(Counter(x.get("block_reason","UNKNOWN") for x in allrows
                                             if not x.get("eligible")).items())),
        "same_game_21_30_clock_window_n":sum(r["official_2130_clock_window"] for r in valid),
        "verified_official_both_teams_n":len(complete),
        "official_report_incomplete_or_unknown_n":len(unknown),
        "verified_explicit_medical_out_or_uncertain_n":sum(
            r["injury"]["confirmed_medical_absence_or_uncertainty_listed"] for r in complete),
        "original_model_moneyline":{"all":ml(valid),
                                    "both_official_verified":ml(complete),
                                    "injury_unverified":ml(unknown)},
        "original_model_five_market":{"all":five(valid),"both_official_verified":five(complete)},
        "injury_adjusted_genuine_pretip_paired_n":len(paired),
        "injury_adjusted_vs_original":paired_comparison,
        "injury_role_identity_reconstructed_after_tip":False,
        "official_pdf_original_release_clock_independently_verified":False,
        "older_21_20_21_25_not_reclassified_as_certified_21_30":True,
        "research_only":True,
        "does_not_create_a_new_injury_prediction_after_outcome":True,
        "never_treat_unsubmitted_injury_report_as_healthy":True,
        "no_production_or_pushplus_changes":True,
        "source_daily_audits":[{k:v for k,v in x.items() if k!="rows"} for x in days],
        "games":allrows
    }
    return report

def selftest():
    assert grade("JINGCAI_HANDICAP",{
        "status":"DIRECTION_ISSUED","direction":"AWAY_COVER",
        "model_direction_probability":.62,"signed_home_handicap":-6.5,
        "line":-6.5},112,117)["hit"] is True
    assert grade("CROWN_HANDICAP",{
        "status":"DIRECTION_ISSUED","direction":"AWAY_COVER",
        "model_direction_probability":.62,"signed_home_handicap":-4.5,
        "line":4.5},112,117)["hit"] is True
    assert grade("CROWN_TOTAL",{
        "status":"DIRECTION_ISSUED","direction":"UNDER",
        "model_direction_probability":.62,"line":229.5},112,117)["hit"] is True
    assert grade("CROWN_TOTAL",{
        "status":"DIRECTION_ISSUED","direction":"OVER",
        "model_direction_probability":.62,"line":229},112,117) is None
    assert grade("CROWN_HANDICAP",{
        "status":"DIRECTION_ISSUED","direction":"AWAY_COVER",
        "model_direction_probability":.62,"signed_home_handicap":-5.},120,115) is None
    t=clock("2026-11-03T00:00:00Z")
    good={"source_captured_at_utc":"2026-11-02T13:30:00Z",
          "source_date_matches_tip":True,"source_report_et_date":"2026-11-02",
          "capture_before_tip_verified":True,"parsed_player_ambiguity":False,
          "quality":"PUBLISHED_AFFECTED",
          "home":{"report_state":"PUBLISHED","players":[
              {"name":"Medical Player","status":"Out","reason":"Injury/Illness - ankle"},
              {"name":"Nonmedical Player","status":"Out","reason":"G League - Two-Way"}]},
          "away":{"report_state":"PUBLISHED","players":[]}}
    result=context_features(good,t,clock("2026-11-02T13:40:00Z"))
    assert result["both_teams_official_report_verified"] is True
    assert result["reported_statuses"]["explicit_medical_out_or_uncertain"]==1
    assert result["reported_statuses"]["Out"]==2
    bad={**good,"away":{"report_state":"NOT_SUBMITTED","players":[]}}
    assert context_features(bad,t,clock("2026-11-02T13:40:00Z"))[
        "both_teams_official_report_verified"] is False
    too_late={**good,"source_captured_at_utc":"2026-11-03T01:00:00Z"}
    assert context_features(too_late,t,clock("2026-11-02T13:40:00Z"))[
        "source_capture_valid"] is False
    print("RECENT_INJURY_FROZEN_OUTCOMES_HARD_GATES_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo",default=".")
    p.add_argument("--start",default="2026-10-31")
    p.add_argument("--end",default="2026-11-03")
    p.add_argument("--out",default="")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:return selftest()
    report=run(a.repo,a.start,a.end)
    if a.out:
        target=Path(a.out)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True,
                                     allow_nan=False)+"\n",encoding="utf-8")
    print("NBA_RECENT_SETTLED_INJURY_FROZEN_BACKTEST",json.dumps({
        "range":[a.start,a.end],
        "completed":report["completed_games_in_settlements"],
        "frozen_evaluable":report["strict_frozen_baseline_evaluable_games"],
        "blocked":report["blocked_games"],
        "21_30_clock":report["same_game_21_30_clock_window_n"],
        "official_both_teams_verified":report["verified_official_both_teams_n"],
        "original_moneyline":report["original_model_moneyline"],
        "original_five_market":report["original_model_five_market"]["all"],
        "genuine_frozen_injury_candidate_pairs":report["injury_adjusted_genuine_pretip_paired_n"],
        "injury_brier_lift":report["injury_adjusted_vs_original"],
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
