#!/usr/bin/env python3
"""Extract deeper time-safe 007 match context from preserved hashed raw pages.

This is a READ-ONLY research evidence ledger, not a trained model or predicted
player effect. No betting odds, no result after kickoff, no PushPlus changes.
007 lists suspensions, but that is not proof of minutes/value/lineup absence.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import gzip,hashlib,json,math,re
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_analysis_extract as src

VERSION="football-007-deep-context-evidence-v1"
UTC=timezone.utc


def dt(raw):
    value=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    if value.tzinfo is None:raise ValueError("DEEP_EVIDENCE_NAIVE_TIMESTAMP")
    return value.astimezone(UTC)


def num(value,lower=0,upper=1000):
    if type(value) not in (int,float) or not math.isfinite(value) or not lower<=value<=upper:
        return None
    return round(float(value),4)


def attack_source(data,game):
    raw=data.get("constract") or {}
    rows=raw.get("normal") if isinstance(raw,dict) else None
    if not isinstance(rows,list):
        return {"status":"UNAVAILABLE","home":None,"away":None}
    found={}
    for side in ("home","away"):
        source_id=str(game.get(side+"_team_id_007"))
        matching=[r for r in rows if isinstance(r,dict) and str(r.get("teamId"))==source_id]
        if len(matching)!=1:raise ValueError("DEEP_RECENT_STAT_TEAM_IDENTITY_MISMATCH")
        groups={}
        for row in matching[0].get("datas") or []:
            if not isinstance(row,dict):continue
            kind=row.get("kind")
            if kind not in ("NEAR_5","NEAR_10","NEAR_15") or kind in groups:continue
            total=row.get("total")
            if type(total) is not int or not 0<=total<=15:continue
            if total!=int(kind.split("_")[-1]):continue
            fields={
              "source_avg_goals_for":num(row.get("avgGetGoal"),0,15),
              "source_avg_goals_against":num(row.get("avgLoseGoal"),0,15),
              "source_possession_percent":num(row.get("avgControl"),0,100),
              "source_wasShots_UNVERIFIED_MEANING":num(row.get("wasShots"),0,100),
              "source_avg_corners":num(row.get("avgCorner"),0,30),
              "source_avg_yellows":num(row.get("avgYellow"),0,15)
            }
            if fields["source_avg_goals_for"] is None or fields["source_avg_goals_against"] is None:continue
            groups[kind]={"total":total,**fields}
        found[side]=groups
    return {"status":"SOURCE_AGGREGATES_NO_CAUSAL_WEIGHT",
            "home":found["home"],"away":found["away"],
            "wasShots_semantics_unverified":True}


def opposition_tiers(data):
    raw=data.get("matchFeature") or {}
    rows=raw.get("features") if isinstance(raw,dict) else None
    n=raw.get("matchNumber") if isinstance(raw,dict) else None
    if not isinstance(rows,list) or type(n) is not int or not 5<=n<=20:
        return {"status":"UNAVAILABLE"}
    found={"home":{},"away":{}}
    for row in rows:
        if not isinstance(row,dict):continue
        text=row.get("title") or ""
        match=re.fullmatch(r"(主队|客队)对阵(前|后)(\d+)名",str(text))
        if not match or int(match.group(3))!=n:continue
        side="home" if match.group(1)=="主队" else "away"
        bracket="upper_half" if match.group(2)=="前" else "lower_half"
        vals={}
        for k in ("win","draw","loss"):
            rawv=row.get(k)
            if not isinstance(rawv,str) or not rawv.isdigit() or int(rawv)>60:
                break
            vals[k]=int(rawv)
        if len(vals)!=3:continue
        total=sum(vals.values())
        if total>60:continue
        found[side][bracket]={"matches":total,**vals,
           "points_per_match":round((3*vals["win"]+vals["draw"])/total,4) if total else None}
    status="SOURCE_RECORDED_OPPONENT_TIER_WDL_NOT_ID_MATCHED" if all(len(v)==2 for v in found.values()) else "PARTIAL_OR_UNAVAILABLE"
    return {"status":status,"league_half_boundary":n,**found,
            "not_an_exact_opponent_strength_rating":True}


def suspension_facts(data,game):
    raw=data.get("injury") or {}
    if not isinstance(raw,dict):return {"status":"UNAVAILABLE","home":[],"away":[]}
    out={}
    for side,field in (("home","homeStop"),("away","awayStop")):
        group=raw.get(field)
        if not isinstance(group,list):
            return {"status":"INCOMPLETE_OR_UNAVAILABLE","home":[],"away":[]}
        chosen=[];seen=set()
        for row in group[:80]:
            if not isinstance(row,dict):continue
            pid=row.get("id")
            if type(pid) is not int or pid<=0 or pid in seen:continue
            seen.add(pid)
            chosen.append({"player_id_007":pid,"team_id_007":game.get(side+"_team_id_007"),
                "position":src.localized(row.get("position")),
                "role":src.position_role(row.get("position")),
                "source_reason":str(row.get("reason") or "")[:150],
                "status":"007_LISTED_STOP_NOT_CONFIRMED_PLAYER_IMPACT"})
        out[side]=chosen
    return {"status":"SOURCE_LISTED_SUSPENSION_NO_CONFIRMED_MINUTES",
            "home":out["home"],"away":out["away"],
            "player_importance_not_inferred":True}


def future_schedule(data,game,captured,kickoff):
    raw=data.get("future3Matches") or {}
    if not isinstance(raw,dict):return {"status":"UNAVAILABLE"}
    vals={}
    for side,field in (("home","homeMatches"),("away","awayMatches")):
        group=raw.get(field) or {}
        rows=group.get("matches") if isinstance(group,dict) else None
        if not isinstance(rows,list) or str(group.get("teamId"))!=str(game.get(side+"_team_id_007")):
            return {"status":"INCOMPLETE_OR_TEAM_MISMATCH"}
        found=[]
        for row in rows[:10]:
            if not isinstance(row,dict):continue
            try:when=datetime.fromtimestamp(int(row["matchTime"]),UTC)
            except (ValueError,TypeError,OverflowError,KeyError):continue
            if when<=kickoff:continue
            ident=game.get(side+"_team_id_007")
            if str(ident) not in (str(row.get("homeTeamId")),str(row.get("awayTeamId"))):
                continue
            mid=row.get("id")
            if type(mid) is not int or mid<=0:continue
            found.append({"match_id":str(mid),"kickoff_utc":when.isoformat(),
                "after_current_game_days":round((when-kickoff).total_seconds()/86400,2),
                "league_id_007":row.get("leagueId") if type(row.get("leagueId")) is int else None})
        found.sort(key=lambda x:x["kickoff_utc"])
        vals[side]=found[:3]
    return {"status":"SOURCE_FUTURE_FIXTURE_TIME_ONLY_NO_RESULTS",
            **vals,"rotation_consequence_unverified":True}


def verify_bytes(snapshot,game,raw,observed):
    if len(raw)>src.MAX_HTML:raise ValueError("DEEP_RAW_TOO_LARGE")
    proof=game.get("analysis_source_evidence") or {}
    if game.get("analysis_source_status")!="007_EMBEDDED_JSON_VALIDATED":
        raise ValueError("UNVERIFIED_ANALYSIS_ORIGINAL")
    if hashlib.sha256(raw).hexdigest()!=proof.get("sha256"):
        raise ValueError("RAW_HTML_SHA256_MISMATCH")
    captured=dt(snapshot["captured_at_utc"])
    time=dt(proof["captured_at_utc"])
    tip=dt(game["kickoff_beijing"])
    if captured>=tip or time>=tip or time<captured or (time-captured).total_seconds()>600:
        raise ValueError("DEEP_RESEARCH_AFTER_KICKOFF_OR_SOURCE_CLOCK")
    if dt(observed)!=time:raise ValueError("INCONSISTENT_SOURCE_OBSERVATION_TIME")
    return time,tip


def run(snapshot,raw_dir):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("NOT_VERIFIED_007_SNAPSHOT")
    out=[];done=set();folder=Path(raw_dir)
    for g in snapshot.get("games") or []:
        mid=str(g.get("match_id"))
        if not re.fullmatch(r"\d{4,10}",mid) or mid in done:
            raise ValueError("DUPLICATE_OR_INVALID_MATCH")
        done.add(mid)
        row={"match_id":mid,"jc_number":g.get("jc_number"),
             "status":"DEEP_CONTEXT_UNAVAILABLE"}
        try:
            filename=folder/f"analysis_{mid}.html.gz"
            if filename.stat().st_size>1_300_000:raise ValueError("OVERSIZED_GZ_SOURCE")
            raw=gzip.decompress(filename.read_bytes())
            observed=(g.get("analysis_source_evidence") or {}).get("captured_at_utc")
            captured,tip=verify_bytes(snapshot,g,raw,observed)
            data=src.decode_json(raw,mid)
            # Independently verify original analysis fixture IDs.
            near=data.get("nearMatches") or {}
            if str((near.get("homeMatches") or {}).get("teamId"))!=str(g.get("home_team_id_007")):
                raise ValueError("HOME_DEEP_TEAM_ID_DRIFT")
            if str((near.get("awayMatches") or {}).get("teamId"))!=str(g.get("away_team_id_007")):
                raise ValueError("AWAY_DEEP_TEAM_ID_DRIFT")
            row.update(status="SOURCE_CONTEXT_EXTRACTED_NO_WEIGHT",
                source_raw_sha256=hashlib.sha256(raw).hexdigest(),
                source_observed_at_utc=captured.isoformat(),
                recent10_15=attack_source(data,g),
                opponent_tiers=opposition_tiers(data),
                suspensions=suspension_facts(data,g),
                next_three=future_schedule(data,g,captured,tip),
                market_odds_used_in_features=False)
        except (OSError,EOFError,ValueError,TypeError,KeyError) as ex:
            row["reason"]=str(ex)[:160]
        out.append(row)
    return {"schema_version":VERSION,
            "source_snapshot_sha256":hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            "research_only":True,"never_modify_model_probabilities":True,
            "counts":{"games":len(out),"ready":sum(r["status"]=="SOURCE_CONTEXT_EXTRACTED_NO_WEIGHT" for r in out),
                      "quarantined":sum(r["status"]!="SOURCE_CONTEXT_EXTRACTED_NO_WEIGHT" for r in out)},
            "games":out}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",required=True)
    p.add_argument("--raw-dir",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    raw=Path(args.snapshot).read_bytes()
    if not raw or len(raw)>25_000_000:raise ValueError("DEEP_SNAPSHOT_INPUT_SIZE")
    doc=run(json.loads(raw),args.raw_dir)
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_007_DEEP_CONTEXT",json.dumps(doc["counts"],sort_keys=True))


if __name__=="__main__":main()
