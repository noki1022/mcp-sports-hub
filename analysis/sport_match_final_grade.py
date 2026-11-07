#!/usr/bin/env python3
"""Single scorecard for independently sealed, latest-pretip football and NBA finals.

No odds collection and no model recomputation. Football grading additionally
requires the original bytes of the independently audited 007 FULL-TIME feed.
NBA scoring must be supplied from the established independent official scorer.
"""
from __future__ import annotations
import argparse,json,hashlib,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parent))
import sport_match_final_registry as registry
import football_jc_prospective_score as ft
from nba_five_market_settlement import settle as nba_settle, MARKETS as NBA_MARKETS

LABELS={"football":("had","hhad","ttg"),"basketball":tuple(NBA_MARKETS)}
def validate_final(f):
    registry.require(f.get("schema_version")=="sport-per-match-locked-final-v1","NOT_PER_MATCH_PRETIP_FINAL")
    registry.require(f.get("final_sha256")==registry.digest({k:v for k,v in f.items() if k!="final_sha256"}),
                     "PER_MATCH_FINAL_HASH_MISMATCH")
    registry.require(f.get("prematch_lock_only_no_result_source_read") is True,"PREGAME_SOURCE_MISSING")
    registry.require(f.get("sport") in LABELS and set(f.get("markets",{}))==set(LABELS[f["sport"]]),
                     "FINAL_MARKET_IDENTITY_MISMATCH")
    registry.require(registry.stamp(f["generated_utc"])<registry.stamp(f["kickoff_utc"]),"NOT_PREKICKOFF")
    registry.require(registry.stamp(f["capture_utc"])<=registry.stamp(f["generated_utc"]),"CAPTURE_GENERATION_REVERSED")
    registry.require(bool(f.get("source_snapshot_sha256")) and bool(f.get("original_candidate_sha256")),
                     "MISSING_HASHED_ORIGINAL")
    registry.require(f.get("kickoff_beijing_day")==registry.stamp(f["kickoff_utc"]).astimezone(
                     ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"),"KICKOFF_DAY_MISMATCH")
    return True

def load_finals(root,sport,day):
    registry.require(sport in LABELS,"BAD_SPORT")
    registry.require(len(day)==8 and day.isdigit(),"INVALID_DAY")
    base=Path(root)/sport/day
    files=sorted(base.glob("*.final.json")) if base.exists() else []
    rows=[];seen=set()
    for file in files:
        data=json.loads(file.read_text(encoding="utf-8"))
        validate_final(data)
        registry.require(data["sport"]==sport and data["kickoff_beijing_day"]==day,"FINAL_FILE_DAY_OR_SPORT_DRIFT")
        mid=data["match_id"]
        registry.require(mid not in seen,"DUPLICATE_FINAL_FOR_ONE_MATCH")
        seen.add(mid);rows.append(data)
    return rows

def football_grade(finals,results,raw_evidence):
    # A 007 status label with no original bytes is NOT an independently verified FT.
    verified=ft.validate_results(results,raw_evidence)
    graded=[];total={k:Counter() for k in LABELS["football"]}
    for f in finals:
        validate_final(f)
        mid=f["match_id"];res=verified.get(mid)
        line=(f["markets"]["hhad"] or {}).get("signed_home_handicap")
        info={"match_id":mid,"jc_number":f["jc_number"],"home_team":f["home_team"],
              "away_team":f["away_team"],"kickoff_utc":f["kickoff_utc"],
              "pregame_candidate_sha256":f["original_candidate_sha256"],
              "actual_score":None,"markets":{}}
        if res is not None:
            ft.verify_join({"match_id":mid,"jc_number":f["jc_number"],"kickoff_beijing":f["kickoff_utc"],
                            "home_team_id_007":f["home_id"],"away_team_id_007":f["away_id"]},
                           res,registry.stamp(f["generated_utc"]))
            h,a=res["home_goals"],res["away_goals"]
            info["actual_score"]={"home":h,"away":a}
        for key in LABELS["football"]:
            m=f["markets"][key]
            prices=m.get("jc_odds")
            predicted=(m.get("goal_selection") or {}).get("goals") if key=="ttg" else [m.get("direction")]
            if not isinstance(predicted,list):predicted=[]
            predicted=[v for v in predicted if isinstance(v,str) and v]
            actual=None
            if res is not None:
                if key=="had":actual="主胜" if h>a else "平" if h==a else "客胜"
                elif key=="hhad" and type(line) is int:
                    n=h+line-a
                    actual="让胜" if n>0 else "让平" if n==0 else "让负"
                elif key=="ttg":
                    actual=str(h+a)+"球" if h+a<7 else "7+球"
            if res is None:status="UNSETTLED"
            elif prices is None:status="EXCLUDED_NOT_ON_SALE"
            elif actual is None or not predicted:status="EXCLUDED_NO_VALID_DIRECTION"
            else:status="HIT" if actual in predicted else "MISS"
            total[key][status]+=1
            info["markets"][key]={"direction":predicted,"actual":actual,"status":status,
                                    "official_home_handicap":line if key=="hhad" else None}
        if f.get("selection_rule")=="ONLY_BEIJING_2100_IMMUTABLE_FORECAST":
            info["selection_rule"]=f["selection_rule"]
        graded.append(info)
    return graded,total

def verify_nba_final_score_identity(final,source):
    """Do not turn a completed score for a wrong home/away or postponed event into a hit."""
    if source.get("completed") is not True:
        return
    if type(source.get("home_points")) is not int or type(source.get("away_points")) is not int:
        raise ValueError("NBA_COMPLETED_WITHOUT_VALID_INTEGER_SCORE")
    if source["home_points"]==source["away_points"] or min(source["home_points"],source["away_points"])<0:
        raise ValueError("NBA_INVALID_FINAL_SCORE")
    tip=source.get("tip_beijing")
    registry.require(tip is not None and abs((registry.stamp(tip)-registry.stamp(final["kickoff_utc"])).total_seconds())<=300,
                     "NBA_FINAL_EVENT_TIPOFF_NOT_SAME_PRETIP_MATCH")
    # 007 Chinese teams were already crossed to the ESPN official fixture at source capture.
    # Re-verify the FULL-TIME feed's sides with that same controlled name mapping.
    from titan007_ev_analysis import NAMES
    home=NAMES.get(final["home_team"])
    away=NAMES.get(final["away_team"])
    registry.require(home is not None and away is not None and home[0]!=away[0],
                     "NBA_UNVERIFIED_FROZEN_TEAM_IDENTITY")
    # Normalize the ESPN scoreboard codes confirmed against official fixtures.
    # Keep the home and away comparisons independent.
    def canonical(value):
        code=str(value or "").upper()
        return {"GS":"GSW", "WSH":"WAS"}.get(code,code)
    registry.require(canonical(source.get("home_abbr"))==home[0] and
                     canonical(source.get("away_abbr"))==away[0],
                     "NBA_OFFICIAL_RESULT_HOME_AWAY_SWAPPED_OR_UNKNOWN")

def basketball_grade(finals,scores,day):
    for f in finals:
        validate_final(f)
        if f.get("official_game_id") in scores:
            verify_nba_final_score_identity(f,scores[f["official_game_id"]])
    board={"target_date":datetime.strptime(day,"%Y%m%d").strftime("%Y-%m-%d"),
           "games":[{"game_id":f["match_id"],"nba_game_id":f["official_game_id"],
                     "jingcai_number":f["jc_number"],"home_team":f["home_team"],
                     "away_team":f["away_team"],"tipoff_beijing":f["kickoff_utc"],
                     "markets":f["markets"]} for f in finals]}
    settled=nba_settle(board,scores,board["target_date"])
    per=settled["games"]
    byid={f["match_id"]:f for f in finals}
    totals={k:Counter() for k in LABELS["basketball"]}
    for item in per:
        f=byid[item["game_id"]]
        item["pregame_candidate_sha256"]=f["original_candidate_sha256"]
        item["kickoff_utc"]=f["kickoff_utc"]
        if f.get("selection_rule")=="ONLY_BEIJING_2100_IMMUTABLE_FORECAST":
            item["selection_rule"]=f["selection_rule"]
        for k,v in item["markets"].items():
            totals[k][v["outcome"]]+=1
    return per,totals

def result(sport,day,rows,counters):
    details={}
    for k,c in counters.items():
        good=c["HIT"];bad=c["MISS"];den=good+bad
        details[k]={"hits":good,"misses":bad,"graded":den,
                    "hit_rate":round(good/den,6) if den else None,
                    "pushes":c["PUSH"],
                    "unsettled":c["UNSETTLED"],
                    "excluded":sum(v for x,v in c.items() if x.startswith("EXCLUDED"))}
    report={"schema_version":"sports-latest-pretip-scoring-v1","sport":sport,"beijing_day":day,
            "prediction_source":"LATEST_VERIFIED_PREKICKOFF_PER_MATCH_IMMUTABLE",
            "historical_2130_not_graded_separately":True,
            "official_result_validation_required":True,
            "matches":rows,"summary":details}
    if rows and all(r.get("selection_rule")=="ONLY_BEIJING_2100_IMMUTABLE_FORECAST" for r in rows):
        report["prediction_source"]="ONLY_BEIJING_2100_IMMUTABLE_FORECAST"
    report["review_sha256"]=registry.digest(report)
    return report

def render_iphone(report):
    """One compact scored answer per fixture, for both sports without restating raw feeds."""
    from html import escape as esc
    sport=report["sport"]
    market_names={
      "had":"竞彩胜平负","hhad":"竞彩让球胜平负","ttg":"竞彩总进球数",
      "JINGCAI_WIN":"竞彩胜负","JINGCAI_HANDICAP":"竞彩让分",
      "JINGCAI_TOTAL":"竞彩大小分","CROWN_HANDICAP":"皇冠让分",
      "CROWN_TOTAL":"皇冠大小分",
    }
    title=("NBA 五玩法" if sport=="basketball" else "足球竞彩三玩法")
    day=report["beijing_day"]
    html=["<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
          "<meta name='viewport' content='width=device-width, initial-scale=1'>",
          "</head><body style='margin:auto;padding:12px;max-width:560px;",
          "font:14px/1.55 -apple-system,BlinkMacSystemFont,Arial,sans-serif;color:#26364b'>",
          "<h2 style='font-size:19px;margin:0 0 6px'>北京时间 "+esc(day)+" "+title+"复盘</h2>",
          "<div style='font-size:12px;color:#64748b;margin-bottom:10px'>",
          ("只评价北京时间21:00原始赛前冻结版。" if report.get("prediction_source")=="ONLY_BEIJING_2100_IMMUTABLE_FORECAST"
           else "历史复盘：只评价每场最后一次有效赛前冻结版。")+"走盘与未入样不计命中率。</div>"]
    for key,stats in report["summary"].items():
        ratio=(f'{stats["hit_rate"]*100:.1f}%（{stats["hits"]}/{stats["graded"]}）'
               if stats["graded"] else "暂无有效样本")
        more=(f'　走盘{stats["pushes"]}' if stats["pushes"] else "")
        more+=(f'　未入样{stats["excluded"]}' if stats["excluded"] else "")
        more+=(f'　待核{stats["unsettled"]}' if stats["unsettled"] else "")
        html.append("<div style='padding:5px 0;border-bottom:1px solid #e5e9ef'><b>"+
                    esc(market_names[key])+"</b>　<b>"+esc(ratio)+"</b>"+
                    esc(more)+"</div>")
    for game in report["matches"]:
        score=game.get("actual_score")
        if isinstance(score,dict):
            hs,aw=score.get("home"),score.get("away")
        else:
            hs,aw=game.get("home_points"),game.get("away_points")
        scores=(f"{hs}:{aw}" if type(hs) is int and type(aw) is int else "待核实")
        idx=game.get("jingcai_number") or game.get("jc_number") or "编号待核"
        html.extend(["<section style='padding:10px;margin:10px 0;border-radius:10px;",
                    "border:1px solid #dbe3ee'><b>"+esc(str(idx))+"　"+
                    esc(str(game.get("home_team") or "主队待核"))+"（主） vs "+
                    esc(str(game.get("away_team") or "客队待核"))+"（客）</b>",
                    "<div style='color:#65768a;font-size:12px'>最终比分（主:客）："+
                    esc(scores)+"</div>"])
        for key,market in game["markets"].items():
            status=market.get("outcome",market.get("status","UNSETTLED"))
            desc={"HIT":"命中","MISS":"未中","PUSH":"走盘",
                  "UNSETTLED":"待核实"}.get(status,"未入样")
            choice=market.get("direction")
            if isinstance(choice,list): choice="/".join(map(str,choice))
            choice=str(choice or "暂无有效判断")
            sign=market.get("signed_home_handicap",market.get("official_home_handicap"))
            if key.endswith(("HANDICAP","hhad")) and isinstance(sign,(int,float)):
                choice+=f"（主{sign:+g}）"
            if key.endswith("TOTAL") and isinstance(market.get("line"),(int,float)):
                choice+=f"（总分{market['line']:g}）"
            extra=""
            if status=="MISS":
                actual=market.get("actual")
                extra=(" 实际："+str(actual) if actual is not None else "")+"　赛果："+scores
            html.append("<div style='padding:5px 0;border-top:1px solid #ecf0f5'>"+
                        esc(market_names[key])+"　"+esc(choice)+"　<b>"+esc(desc)+"</b>"+
                        esc(extra)+"</div>")
        html.append("</section>")
    html.extend(["<div style='font-size:11px;color:#64748b'>未核实赛果不评分；",
                 "历史赔率或开赛后的模型计算不能反向修改本报告。</div></body></html>"])
    return "".join(html)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--final-root",required=True);p.add_argument("--sport",required=True,choices=tuple(LABELS))
    p.add_argument("--day",required=True);p.add_argument("--results",required=True)
    p.add_argument("--raw-dir");p.add_argument("--out",required=True)
    p.add_argument("--html")
    a=p.parse_args()
    finals=load_finals(a.final_root,a.sport,a.day)
    if not finals:raise ValueError("NO_SEALED_PER_MATCH_FINALS_NO_SCORECARD")
    results=json.loads(Path(a.results).read_text(encoding="utf-8"))
    if a.sport=="basketball":
        if not isinstance(results,dict):raise ValueError("INVALID_NBA_OFFICIAL_RESULTS_MAP")
        rows,totals=basketball_grade(finals,results,a.day)
    else:
        if not a.raw_dir:raise ValueError("ORIGINAL_007_RAW_FT_BYTES_MANDATORY")
        raw={p.stem: p.read_bytes() for p in Path(a.raw_dir).glob("*.bin")}
        rows,totals=football_grade(finals,results,raw)
    report=result(a.sport,a.day,rows,totals)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if a.html:
        dest=Path(a.html)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(render_iphone(report),encoding="utf-8")
    print("VERIFIED_PER_MATCH_REVIEW",a.sport,[(k,x["graded"]) for k,x in report["summary"].items()])

if __name__=="__main__":main()

