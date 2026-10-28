#!/usr/bin/env python3
"""Daily NBA/CBA market analysis with strict freshness and availability gates.

Reads the matching day's real Titan007 joined markets; outputs no-vig probabilities
and official injury matchup states. DOES NOT publish independent win probabilities,
EV claims, or bets from stale NBA team data.
"""
from __future__ import annotations
import argparse,csv,json,sys
from datetime import datetime,timedelta,date,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analysis"))
import titan007_market_math as odds
from titan007_ev_analysis import NAMES

def flatten_report(board,injury,quality=None):
    check={(str(r.get("game_id")),r.get("market")):r for r in (quality or {}).get("details",[]) if r.get("game_id") and r.get("market")}
    stamp=datetime.now(timezone.utc).isoformat()
    rows=[]
    allgames=board.get("nba_cba_games",[])
    for game in allgames:
        homes=NAMES.get(game.get("home_team",""))
        aways=NAMES.get(game.get("away_team",""))
        matchup=(aways[0]+"@"+homes[0]) if game.get("league")=="NBA" and homes and aways else None
        info=(injury or {}).get("matchups",{}).get(matchup,{}) if matchup else {}
        home_state=info.get(homes[1],{}).get("report_state","NOT_LISTED") if homes else "NOT_APPLICABLE"
        away_state=info.get(aways[1],{}).get("report_state","NOT_LISTED") if aways else "NOT_APPLICABLE"
        for kind in ("full_spread","full_total"):
            market=game.get("markets",{}).get(kind,{})
            for stage in ("opening","current"):
                point=market.get(stage,{})
                line=point.get("line")
                a,b=point.get("first_side_water"),point.get("second_side_water")
                row={
                  "game_id":game["game_id"],"league":game["league"],
                  "display_date":game["display_date"],"display_clock":game["display_clock"],
                  "home_team":game["home_team"],"away_team":game["away_team"],
                  "market":kind,"stage":stage,"line":line,
                  "hk_side1":a,"hk_side2":b,
                  "market_status":"MISSING","injury_report":(injury or {}).get("source_url"),
                  "injury_home_state":home_state,"injury_away_state":away_state,
                  "matchup":matchup,
                  "value_signal":"UNAVAILABLE_UNCALIBRATED",
                  "recommendation":"NO_BET"}
                qc=check.get((str(game["game_id"]),kind))
                if qc is not None:
                    row["independent_crown_check"]=qc["status"]
                else:
                    row["independent_crown_check"]="NOT_SAMPLED"
                if None not in (line,a,b):
                    try:
                        p=odds.devig(a,b)
                        row.update(market_status="OK",
                            decimal_side1=p["decimal_side1"],decimal_side2=p["decimal_side2"],
                            devig_side1=p["no_vig_conditional_side1"],
                            devig_side2=p["no_vig_conditional_side2"],
                            overround=p["overround"])
                        if qc is not None and qc["status"]!="MATCH":
                            row["market_status"]="QUOTE_DRIFT_OR_UNVERIFIED"
                            row["value_signal"]="BLOCKED_SOURCE_MISMATCH"
                    except (ValueError,OverflowError):
                        row["market_status"]="ODDS_INVALID"
                rows.append(row)
    return {"captured_at_utc":stamp,"target_display_date":board["requested_display_date"],
        "source_007":board["odds_source"],"source_injuries":(injury or {}).get("source_url"),
        "games":len(allgames),"market_rows":len(rows),
        "statistics_freshness":"NO_VERIFIED_CURRENT_TEAM_EFFICIENCY_PROVIDER",
        "real_ev_status":"DISABLED_PENDING_OUT_OF_SAMPLE_CALIBRATION_AND_FRESH_STATS",
        "independent_crown_sample":{k:(quality or {}).get(k) for k in ("matching_markets","mismatching_markets","unverified_markets")},
        "row_data":rows,
        "recommendations":[],
        "warnings":["Market implied probability is not a model estimate.","Normalized no-vig probabilities conditional on non-push.","Site display timezone not independently verified.","Official injury report statuses are matchup-specific and may be outdated or NOT_SUBMITTED.",
                    "This report contains no independent fair probability estimate and no validated positive EV picks."]}

def save(obj,out):
    base=Path(out)
    base.parent.mkdir(parents=True,exist_ok=True)
    base.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    csvfile=base.with_suffix(".csv")
    rows=obj["row_data"]
    cols=["display_date","display_clock","league","home_team","away_team","game_id","matchup","market","stage","line","hk_side1","hk_side2","decimal_side1","decimal_side2","devig_side1","devig_side2","overround","market_status","independent_crown_check","injury_home_state","injury_away_state","recommendation"]
    with csvfile.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    from html import escape
    body=[]
    games={}
    for row in rows:
        if row["stage"]!="current":continue
        g=games.setdefault(row["game_id"],{"meta":row,"markets":[]})
        p1=row.get("devig_side1");p2=row.get("devig_side2")
        text=(f'{p1*100:.1f}% / {p2*100:.1f}%' if p1 is not None and p2 is not None else "数据缺失")
        g["markets"].append(f'<p>{escape(row["market"])}：盘口 {escape(str(row["line"]))} · 去水概率 {escape(text)}</p>')
    for g in games.values():
        x=g["meta"]
        body.append(f'<section><h3>{escape(x["home_team"])} vs {escape(x["away_team"])}</h3>'
            +f'<p>{escape(x["league"])} · {escape(x["display_clock"])} · 比赛 ID {escape(x["game_id"])}</p>'
            +"".join(g["markets"])
            +f'<p>伤停：主 {escape(x["injury_home_state"])} / 客 {escape(x["injury_away_state"])}</p>'
            +'<p><strong>不推荐下注：独立模型尚未校准，无法判断真实 EV</strong></p></section>')
    html=('<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
       '<style>body{max-width:850px;margin:auto;padding:16px;background:#f5f6f8;font-family:-apple-system,sans-serif;color:#223}'
       'section{border-radius:12px;background:white;padding:16px;margin:10px 0}p{font-size:13px;line-height:1.5}</style>'
       '</head><body><h1>NBA/CBA 赛前盘口市场概率监测</h1><p>仅展示市场去水概率、官方伤停状态；没有可靠的独立概率和正 EV 结论。</p>'
       +''.join(body)+'</body></html>')
    base.with_suffix(".html").write_text(html,encoding="utf-8")
    print("DAILY_MARKET_REPORT",obj["games"],"games",obj["market_rows"],"market rows")
    return csvfile

def self_test():
    board={"requested_display_date":"2026-10-29","odds_source":"fixture","nba_cba_games":[{
      "game_id":"746353","league":"NBA","display_date":"2026-10-29","display_clock":"07:00",
      "home_team":"亚特兰大老鹰","away_team":"迈阿密热火",
      "markets":{"full_spread":{"current":{"line":3.5,"first_side_water":0.86,"second_side_water":1.0}}}}]}
    obj=flatten_report(board,None)
    r=next(x for x in obj["row_data"] if x["stage"]=="current" and x["market"]=="full_spread")
    assert abs(r["devig_side1"]-.5181347150259068)<1e-9
    assert r["recommendation"]=="NO_BET"
    assert r["injury_home_state"]=="NOT_LISTED"
    assert obj["real_ev_status"].startswith("DISABLED")
    print("DAILY_MARKET_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--joined",default="titan007_joined_nba_cba.json")
    p.add_argument("--injuries",default="nba_official_injuries.json")
    p.add_argument("--out",default="daily_market_analysis.json")
    p.add_argument("--quality",default="titan007_crown_quality_check.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test();raise SystemExit()
    board=json.loads(Path(a.joined).read_text(encoding="utf-8"))
    inj=json.loads(Path(a.injuries).read_text(encoding="utf-8")) if Path(a.injuries).exists() else None
    check=json.loads(Path(a.quality).read_text(encoding="utf-8")) if Path(a.quality).exists() else None
    output=flatten_report(board,inj,check)
    save(output,a.out)
