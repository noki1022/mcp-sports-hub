#!/usr/bin/env python3
"""Rank relative model attention matches for priority 21:30 and 06:30 PushPlus.

NOT a betting recommendation, edge estimate, or proof of calibrated hit rate.
No user-selected numeric confidence threshold: rank model-determined relative
certainty after excluding invalid/extreme-calibration or provenance conflicts.
"""
from __future__ import annotations
import argparse,json,math,re
from pathlib import Path

VERSION="nba-priority-focus-v1"
MARKET_DISAGREEMENT_FLAG=0.20  # Existing PushPlus probability-anomaly diagnostic, not a pick threshold.
RAW_CALIBRATION_FLAG=0.15      # Existing calibration diagnostic, not a pick threshold.
LABEL=re.compile(r"周[一二三四五六日天]\d{3}")

def n(v):
    try:
        if v is None or isinstance(v,bool):return None
        v=float(v)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def unique(rows):
    out={}
    for row in rows or []:
        gid=str(row.get("game_id") or "")
        if not gid or gid in out:raise ValueError("DUPLICATE_OR_MISSING_GAME_ID")
        out[gid]=row
    return out

def odds_home(row):
    mk=((row.get("markets") or {}).get("win_lose") or {})
    if mk.get("status")!="OBSERVED":return None
    q=((mk.get("data") or {}).get("current") or {})
    a,b=n(q.get("first_side")),n(q.get("second_side"))
    if a is None or b is None or a<=1 or b<=1:return None
    return (1/a)/(1/a+1/b)

def choose(joined,model,jingcai,sop,slot):
    if slot not in ("2130","0630"):raise ValueError("PRIORITY_SLOT_ONLY")
    source=unique([x for x in joined.get("nba_cba_games",[]) if x.get("league")=="NBA"])
    predictions=unique(model.get("games",[]))
    sop_rows=unique(sop.get("games",[]))
    identities=(jingcai.get("jc_007_match_numbers") or {}).get("games") or {}
    shadow=unique((jingcai.get("jc_007_public_odds_shadow") or {}).get("games",[]))
    candidates,excluded=[],[]
    for gid,game in source.items():
        p=predictions.get(gid) or {}
        info=sop_rows.get(gid) or {}
        label=(identities.get(gid) or {}).get("label")
        verified=((identities.get(gid) or {}).get("status")=="VERIFIED_JC_NUMBER" and
                  isinstance(label,str) and LABEL.fullmatch(label) is not None)
        home=n((p.get("model_probability") or {}).get("home"))
        raw=n((p.get("model_probability_raw") or {}).get("home"))
        margin=n(p.get("margin_mean_home_minus_away"))
        total=n(p.get("total_mean"))
        reasons=[]
        if not verified:reasons.append("竞彩编号或身份未核验")
        if p.get("model_status")!="OK" or (p.get("data_quality") or {}).get("quality")!="PASS":
            reasons.append("独立模型数据质量未完整通过")
        if home is None or not 0<home<1 or margin is None or total is None:
            reasons.append("校准概率端点/均值缺失或异常")
        if raw is not None and home is not None and abs(home-raw)>=RAW_CALIBRATION_FLAG:
            reasons.append("原始与校准概率分歧大，需核查校准样本")
        # The market is comparison context, not a source of real probabilities.
        # Only compare after a verified, fresh 007 odds clock in the SOP.
        market_p=odds_home(shadow.get(gid) or {})
        fresh=bool((info.get("jingcai") or {}).get("fresh_for_comparison"))
        # Divergence from bookmaker odds is a RESEARCH SIGNAL, not a veto.
        # Never anchor an independent model to market-implied probabilities.
        market_gap=(home-market_p) if verified and fresh and home is not None and market_p is not None else None
        contrarian=market_gap is not None and abs(market_gap)>=MARKET_DISAGREEMENT_FLAG
        if reasons:
            excluded.append({"game_id":gid,"reasons":reasons})
            continue
        assert home is not None and margin is not None
        side="主胜" if home>0.5 else "客胜"
        favorite_prob=home if home>0.5 else 1-home
        injury=(p.get("injury_context") or {}).get("quality") or info.get("injury_quality")
        caution=[]
        if injury not in ("PUBLISHED_LISTED","PUBLISHED_AFFECTED"):
            caution.append("伤停资料不完整")
        else:
            caution.append("已记录伤停；球员影响未量化")
        if market_p is None or not fresh:
            caution.append("竞彩胜负价格未同步核验，不推断价值")
        if contrarian:
            caution.append("与竞彩去水概率显著相反：独立逆向研究信号，必须复核，不等于正期望")
        if raw is None:caution.append("缺少原始胜率，不把校准概率视为真实命中率")
        if favorite_prob>0.95:caution.append("模型概率处于极端尾部，需关注校准稳定性")
        candidates.append({
            "game_id":gid,"jingcai_number":label,"home_team":game.get("home_team"),
            "away_team":game.get("away_team"),"tipoff_beijing":game.get("start_time_beijing"),
            "model_direction":side,"model_direction_probability":round(favorite_prob,6),
            "model_home_probability":round(home,6),
            "model_margin_home_minus_away":round(margin,2),
            "model_total":round(total,2),"model_quality":"PASS",
            "market_no_vig_home":round(market_p,6) if fresh and market_p is not None else None,
            "model_minus_market_home_pp":round(100*market_gap,2) if market_gap is not None else None,
            "contrarian_market_signal":bool(contrarian),
            "injury_quality":injury,"cautions":caution,
            "explanation":"独立模型对"+side+"的相对倾向较明确；按同批比赛的概率偏离50%幅度排序"
        })
    candidates.sort(key=lambda x:(-abs(x["model_home_probability"]-.5),
                                  x["jingcai_number"],x["game_id"]))
    # Model focus membership and ordering MUST be entirely odds-blind.
    # Bookmaker changes cannot promote, demote, remove, or replace a model pick.
    top=candidates[:min(3,len(candidates))]
    # Divergences are separately displayed as post-model market comparisons.
    # This list must NEVER feed back into the independent ranking.
    divergence=sorted((x for x in candidates if x["contrarian_market_signal"]),
                      key=lambda x:(-abs(x["model_minus_market_home_pp"]),x["game_id"]))
    market_divergences=[{
        "game_id":x["game_id"],"jingcai_number":x["jingcai_number"],
        "home_team":x["home_team"],"away_team":x["away_team"],
        "model_direction":x["model_direction"],
        "model_home_probability":x["model_home_probability"],
        "market_no_vig_home":x["market_no_vig_home"],
        "model_minus_market_home_pp":x["model_minus_market_home_pp"],
    } for x in divergence[:3]]
    for index,record in enumerate(top,1):record["focus_rank"]=index
    return {
        "schema_version":VERSION,"slot":slot,
        "target_beijing_date":joined.get("requested_display_date"),
        "selection_method":"ODDS_BLIND_RELATIVE_MODEL_PROBABILITY_RANK_AFTER_MODEL_SAFETY_CHECKS",
        "confidence_threshold":None,"max_displayed":3,
        "focus_games":top,"focus_count":len(top),
        "market_divergences":market_divergences,
        "odds_independent_focus":True,
        "eligible_count":len(candidates),"total_nba_games":len(source),
        "contrarian_signal_count":len(divergence),
        "excluded_count":len(excluded),"excluded":excluded,
        "statement":"赔率高低不决定模型胜率；重点关注独立排序，逆向分歧单独观察；五玩法仍逐场展示",
        "research_only":True
    }

def self_test():
    j={"requested_display_date":"2026-11-01","nba_cba_games":[]}
    md={"games":[]}
    jd={"jc_007_match_numbers":{"games":{}},"jc_007_public_odds_shadow":{"games":[]}}
    sop={"games":[]}
    for gid,hp,label in [("1",.82,"周六301"),("2",.63,"周六302"),("3",.91,"周六303"),
                         ("4",.0,"周六304"),("5",.96,"周六305"),("6",.55,"周六306")]:
        j["nba_cba_games"].append({"game_id":gid,"league":"NBA","home_team":"主"+gid,
                                   "away_team":"客"+gid,"start_time_beijing":"2026-11-01T09:00:00+08:00"})
        md["games"].append({"game_id":gid,"model_status":"OK","data_quality":{"quality":"PASS"},
           "model_probability":{"home":hp},"margin_mean_home_minus_away":8 if hp>.5 else -8,
           "total_mean":225,"injury_context":{"quality":"PUBLISHED_AFFECTED"}})
        jd["jc_007_match_numbers"]["games"][gid]={"status":"VERIFIED_JC_NUMBER","label":label}
        sop["games"].append({"game_id":gid,"jingcai":{"fresh_for_comparison":False}})
    z=choose(j,md,jd,sop,"2130")
    assert z["focus_count"]==3 and z["confidence_threshold"] is None
    assert [x["game_id"] for x in z["focus_games"]]==["5","3","1"]
    assert "4" in [x["game_id"] for x in z["excluded"]]
    assert choose(j,md,jd,sop,"0630")["focus_games"][0]["jingcai_number"]=="周六305"
    md["games"][4]["model_probability_raw"]={"home":.61}
    assert "5" not in [x["game_id"] for x in choose(j,md,jd,sop,"0630")["focus_games"]]
    # Low odds must NOT overwrite model probabilities or alter model focus.
    before=choose(j,md,jd,sop,"2130")
    before_ids=[x["game_id"] for x in before["focus_games"]]
    before_p=[x["model_home_probability"] for x in before["focus_games"]]
    jd["jc_007_public_odds_shadow"]["games"]=[{"game_id":"6","markets":{"win_lose":{
       "status":"OBSERVED","data":{"current":{"first_side":1.11,"second_side":7.5}}}}}]
    sop["games"][5]["jingcai"]["fresh_for_comparison"]=True
    contrary=choose(j,md,jd,sop,"2130")
    assert before_ids==[x["game_id"] for x in contrary["focus_games"]]
    assert before_p==[x["model_home_probability"] for x in contrary["focus_games"]]
    assert contrary["market_divergences"][0]["game_id"]=="6"
    assert contrary["odds_independent_focus"] is True
    # A 1.44 home price versus independent model home=9.9% is retained, not vetoed.
    md["games"][5]["model_probability"]["home"]=0.099
    jd["jc_007_public_odds_shadow"]["games"][0]["markets"]["win_lose"]["data"]["current"]={"first_side":1.44,"second_side":2.80}
    extreme=choose(j,md,jd,sop,"2130")
    assert any(x["game_id"]=="6" for x in extreme["focus_games"])
    needle=next(x for x in extreme["market_divergences"] if x["game_id"]=="6")
    assert needle["model_home_probability"]==0.099
    assert needle["model_minus_market_home_pp"] < -50
    # Flip market quotes; the independent ranked list remains untouched.
    jd["jc_007_public_odds_shadow"]["games"][0]["markets"]["win_lose"]["data"]["current"]={"first_side":5.0,"second_side":1.10}
    flip=choose(j,md,jd,sop,"2130")
    assert [x["game_id"] for x in flip["focus_games"]]==[x["game_id"] for x in extreme["focus_games"]]
    assert [x["model_home_probability"] for x in flip["focus_games"]]==[x["model_home_probability"] for x in extreme["focus_games"]]
    for row in md["games"]:row["model_status"]="DISABLED"
    empty=choose(j,md,jd,sop,"2130")
    assert empty["focus_count"]==0 and empty["total_nba_games"]==6
    try:choose(j,md,jd,sop,"1200")
    except ValueError:pass
    else:raise AssertionError("NONPRIORITY_SLOT_SHOULD_FAIL")
    print("NBA_PRIORITY_RELATIVE_MODEL_FOCUS_SELF_TEST_PASS")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--joined");a.add_argument("--model");a.add_argument("--jingcai")
    a.add_argument("--sop");a.add_argument("--slot",choices=("2130","0630"))
    a.add_argument("--out");a.add_argument("--self-test",action="store_true")
    v=a.parse_args()
    if v.self_test:self_test()
    else:
        if not all((v.joined,v.model,v.jingcai,v.sop,v.slot,v.out)):raise SystemExit("FOCUS_INPUT_MISSING")
        def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
        focus=choose(load(v.joined),load(v.model),load(v.jingcai),load(v.sop),v.slot)
        Path(v.out).write_text(json.dumps(focus,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_PRIORITY_FOCUS",v.slot,focus["focus_count"],"/",focus["total_nba_games"])
