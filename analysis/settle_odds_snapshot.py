#!/usr/bin/env python3
"""Strictly join normalized odds rows to event-id scores and settle markets."""
import argparse,json
from pathlib import Path

TEAM_NAMES={"ATL":"Atlanta Hawks","BOS":"Boston Celtics","BKN":"Brooklyn Nets","CHA":"Charlotte Hornets","CHI":"Chicago Bulls","CLE":"Cleveland Cavaliers","DAL":"Dallas Mavericks","DEN":"Denver Nuggets","DET":"Detroit Pistons","GSW":"Golden State Warriors","HOU":"Houston Rockets","IND":"Indiana Pacers","LAC":"Los Angeles Clippers","LAL":"Los Angeles Lakers","MEM":"Memphis Grizzlies","MIA":"Miami Heat","MIL":"Milwaukee Bucks","MIN":"Minnesota Timberwolves","NOP":"New Orleans Pelicans","NYK":"New York Knicks","OKC":"Oklahoma City Thunder","ORL":"Orlando Magic","PHI":"Philadelphia 76ers","PHX":"Phoenix Suns","POR":"Portland Trail Blazers","SAC":"Sacramento Kings","SAS":"San Antonio Spurs","TOR":"Toronto Raptors","UTA":"Utah Jazz","WAS":"Washington Wizards"}
def canonical(name):
    s=str(name or '').strip().lower()
    for code,full in TEAM_NAMES.items():
        if s==code.lower() or s==full.lower(): return full.lower()
    return s

def settle(row, score):
    if not score.get("completed") or score.get("home_points") is None or score.get("away_points") is None:
        return "UNSETTLED"
    h,a=score["home_points"],score["away_points"]
    if row["market"]=="h2h": value=h-a
    elif row["market"]=="spreads": value=h-a+row["home_handicap_point"]
    elif row["market"]=="totals": value=h+a-row["total_point"]
    else: return "UNSETTLED"
    if abs(value)<1e-9:return "PUSH"
    if row["market"]=="totals": return "WIN_FIRST" if value>0 else "LOSS_FIRST"
    return "WIN_FIRST" if value>0 else "LOSS_FIRST"

def run(odds_path,scores_path,out):
    odds=json.loads(Path(odds_path).read_text()); scores=json.loads(Path(scores_path).read_text())
    by_id={x.get("event_id"):x for x in scores.get("games",[]) if x.get("event_id")}
    rows=[]; rejects={}
    for row in odds.get("rows",[]):
        s=by_id.get(row.get("event_id"))
        if not s: rejects["MISSING_EVENT_ID_RESULT"]=rejects.get("MISSING_EVENT_ID_RESULT",0)+1; continue
        if canonical(row["home"])!=canonical(s.get("home_team")) or canonical(row["away"])!=canonical(s.get("away_team")):
            rejects["TEAM_IDENTITY_MISMATCH"]=rejects.get("TEAM_IDENTITY_MISMATCH",0)+1; continue
        rows.append({**row,"home_points":s.get("home_points"),"away_points":s.get("away_points"),"settlement":settle(row,s)})
    counts={}
    for r in rows: counts[r["settlement"]]=counts.get(r["settlement"],0)+1
    report={"source_odds":odds_path,"source_scores":scores_path,"rows":rows,
            "audit":{"input_rows":len(odds.get("rows",[])),"linked_rows":len(rows),"rejections":rejects,"settlements":counts,
                      "no_roi_until_result_time_and_price_semantics_verified":True}}
    Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2)); print(json.dumps(report["audit"],ensure_ascii=False))

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--odds",required=True); p.add_argument("--scores",required=True); p.add_argument("--out",required=True); a=p.parse_args(); run(a.odds,a.scores,a.out)
