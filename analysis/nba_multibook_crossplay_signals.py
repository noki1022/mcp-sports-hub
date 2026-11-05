#!/usr/bin/env python3
"""Independent, result-free multi-book NBA direction research signals.

Consumes ONLY sanitized pre-tip 007 quote snapshots. Never imports baseline
NBA model, settlement, training labels or post-game results. Estimates are
new *candidate* forecasts, not trained incremental predictive power. Keep
original independent baseline as the production-facing shadow score until
independent frozen 21:30 outcomes prove candidate improvement.

Positive 007 spread line = HOME gives points; inverse JC/Crown handicap
side must be handled by caller. 007 water slot direction is NOT certified:
NO use of water price for home/away/over/under probability.
"""
from __future__ import annotations
from datetime import datetime, timezone
from statistics import median
import math

SPREAD_SIGMA=15.55
TOTAL_SIGMA=19.47
MIN_BOOKS=3
MAX_PAST_SNAPSHOTS=18
SCHEMA="nba-shadow-independent-multibook-candidate-v2"

def stamp(value):
    if not isinstance(value,str):return None
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:return None

def number(x):
    if isinstance(x,bool):return None
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (TypeError,ValueError):return None

def cdf(x):
    return max(.001,min(.999,.5*math.erfc(-x/math.sqrt(2))))

def books(m,clock):
    """Only current real, distinct non-outlier bookmaker quotes, no repeats.

    007 source capture is *observation time*, NOT the timestamp at which
    individual bookmakers changed their odds.
    """
    if m.get("status")!="CONSENSUS_AVAILABLE":
        return {}
    output={};duplicates=set()
    for r in m.get("quotes",[]):
        cid=str(r.get("company_id") or "")
        line=number(r.get("line"))
        t=stamp(r.get("source_capture_utc"))
        if not cid or line is None or t is None or t>clock:
            continue
        if r.get("excluded_as_line_outlier"):
            continue
        if cid in output:
            output.pop(cid,None);duplicates.add(cid)
        elif cid not in duplicates:
            output[cid]=(line,t)
    return output

def center(m,asof,kind):
    """One vote per actual independent company; Huber-bounded mean.

    A median is a sturdy market anchor; Huber-bounded mean is a
    precommitted alternative. Clamp rather than guessing "sharp" weights.
    """
    pairs=books(m,asof)
    if len(pairs)<MIN_BOOKS:
        return {"status":"INSUFFICIENT_BOOKS","independent_books":len(pairs)}
    lines=[v[0] for v in pairs.values()]
    med=median(lines)
    declared=number(m.get("median_line"))
    if declared is None or abs(declared-med)>4.0:
        # Upstream 007 consensus median can be the modal LINE median,
        # different from the across-company median. Retain both distinctly.
        if declared is None:
            return {"status":"NO_UPSTREAM_MARKET_CENTER","independent_books":len(pairs)}
    cap=2.0 if kind=="full_spread" else 4.0
    robust=med+sum(max(-cap,min(cap,v-med)) for v in lines)/len(lines)
    mad=median(abs(x-med) for x in lines)
    avg_disp=sum(abs(x-med) for x in lines)/len(lines)
    return {
        "status":"AVAILABLE","independent_books":len(lines),
        "median_all_independent_companies":round(med,5),
        "upstream_007_consensus_median":declared,
        "bounded_robust_center":round(robust,6),
        "median_absolute_deviation":round(mad,6),
        "mean_absolute_deviation":round(avg_disp,6),
        "max_winsorized_distance_points":cap,
        "crown_id3_in_group":("3" in pairs),
        "raw_price_water_not_interpreted_as_direction":True,
    }

def movement(older,newer,oldtime,newtime):
    result={"same_company_pairs":0,"increased":0,"decreased":0,
            "unchanged":0,"agreement_among_all":None,
            "agreement_among_movers":None,
            "market_signal":"INSUFFICIENT_PAIRED_DATA",
            "matched_price_change_is_observation_not_book_event_timestamp":True}
    if not oldtime or not newtime or not oldtime<newtime:
        return result
    old=books(older,oldtime)
    new=books(newer,newtime)
    pairs=[]
    paired_ids=[]
    for cid in sorted(old.keys() & new.keys()):
        a,at=old[cid];b,bt=new[cid]
        if at<bt:
            pairs.append(b-a)
            paired_ids.append(cid)
    if len(pairs)<MIN_BOOKS:
        result["same_company_pairs"]=len(pairs)
        return result
    up=sum(x>0 for x in pairs);dn=sum(x<0 for x in pairs)
    unchanged=len(pairs)-up-dn
    changed=up+dn
    consensus_diff=number(newer.get("median_line"))
    initial=number(older.get("median_line"))
    composition_delta=(consensus_diff-initial if consensus_diff is not None and initial is not None else None)
    # A changing company mix must not reverse/suppress a genuine paired move.
    # Use the median of same-company deltas, not two unrelated group medians.
    median_delta=median(pairs)
    dominant=max(up,dn)
    frac_all=dominant/len(pairs)
    frac_movers=dominant/changed if changed else None
    if not changed:signal="UNCHANGED"
    elif up>=3 and up/len(pairs)>=.6 and median_delta is not None and median_delta>0:
        signal="BROAD_RISING"
    elif dn>=3 and dn/len(pairs)>=.6 and median_delta is not None and median_delta<0:
        signal="BROAD_FALLING"
    else:signal="MIXED_OR_THIN_MOVEMENT"
    return {**result,"same_company_pairs":len(pairs),"increased":up,
            "decreased":dn,"unchanged":unchanged,
            "median_change":round(median_delta,5) if median_delta is not None else None,
            "unpaired_consensus_change":composition_delta,
            "paired_company_ids":paired_ids,
            "composition_change_excluded_from_signal":True,
            "agreement_among_all":round(frac_all,5),
            "agreement_among_movers":round(frac_movers,5) if frac_movers is not None else None,
            "market_signal":signal}

def case(gid,current,asof,history,kind):
    m=(current.get("markets") or {}).get(kind) or {}
    cur=center(m,asof,kind)
    info=[]
    for snapshot in history[-MAX_PAST_SNAPSHOTS:]:
        older_time=stamp(snapshot.get("collection_completed_at_utc"))
        if not older_time or older_time>=asof:
            raise ValueError("FUTURE_OR_UNSTAMPED_COMPANY_SNAPSHOT_IN_SHADOW_HISTORY")
        row=next((g for g in snapshot.get("games",[]) if str(g.get("game_id"))==str(gid)),None)
        if row is None:
            continue
        prev=(row.get("markets") or {}).get(kind) or {}
        if prev.get("status")!="CONSENSUS_AVAILABLE":
            continue
        info.append((older_time,prev))
    info.sort(key=lambda z:z[0])
    snapshots=info+[(asof,m)]
    moves=[{**movement(a,b,at,bt),"old_capture_utc":at.isoformat(),
            "new_capture_utc":bt.isoformat()}
        for (at,a),(bt,b) in zip(snapshots,snapshots[1:])]
    signals=[x["market_signal"] for x in moves if x["market_signal"].startswith("BROAD_")]
    reversal=(len(signals)>=2 and signals[-1]!=signals[-2])
    all_up=sum(x["increased"] for x in moves)
    all_down=sum(x["decreased"] for x in moves)
    initial=number(info[0][1].get("median_line")) if info else None
    latest=number(m.get("median_line"))
    return {**cur,"kind":kind,
            "historical_capture_count":len(info),
            "history_first_capture_utc":info[0][0].isoformat() if info else None,
            "latest_capture_utc":asof.isoformat(),
            "net_change_earliest_to_current":round(latest-initial,5)
               if latest is not None and initial is not None else None,
            "paired_book_observation_up_events":all_up,
            "paired_book_observation_down_events":all_down,
            "last_step":moves[-1] if moves else None,
            "intervals":moves,
            "directional_reversal_after_confirmed_movement":reversal,
            "compared_prices_are_independent_same_company":True,
            "no_bookmaker_update_time_claim":True}

def candidates_for_game(gid,market,history,asof,targets,baseline):
    spread=case(gid,market,asof,history,"full_spread")
    total=case(gid,market,asof,history,"full_total")
    features={"full_spread":spread,"full_total":total,
              "source":"007_CERTIFIED_ASOF_DISTINCT_BOOKS_ONLY",
              "not_a_value_or_arbitrage_finder":True,
              "not_yet_a_validated_forecast_uplift":True}
    variants={}
    for name,entry in baseline.items():
        is_spread=name=="JINGCAI_WIN" or name.endswith("HANDICAP")
        stat=spread if is_spread else total
        if stat["status"]!="AVAILABLE" or len(stat.get("intervals",[]))<1:
            # Book-only cross section can still produce a forecast when
            # historical movement history is not available, but evidence
            # status is explicit; do not fabricate directional agreement.
            pass
        if stat["status"]!="AVAILABLE":
            continue
        mu=stat["bounded_robust_center"]
        limit=number(entry.get("line"))
        signed=number(entry.get("signed_home_handicap"))
        if name=="JINGCAI_WIN":
            point=mu; sigma=SPREAD_SIGMA
        elif is_spread:
            if signed is None or limit is None:continue
            point=mu+signed;sigma=SPREAD_SIGMA
        else:
            if limit is None:continue
            point=mu-limit;sigma=TOTAL_SIGMA
        # The spread of quoted *lines* indicates disagreement between
        # companies, not independent samples of eventual outcomes.
        # Merely use it as conservative variance inflation in a candidate,
        # not assert a fitted confidence or jump probability.
        sigma_adj=math.sqrt(sigma*sigma+stat["mean_absolute_deviation"]**2)
        p=cdf(point/sigma_adj)
        direction=(("HOME_WIN" if p>.5 else "AWAY_WIN" if p<.5 else "TIE")
                   if name=="JINGCAI_WIN" else
                   ("HOME_COVER" if p>.5 else "AWAY_COVER" if p<.5 else "TIE")
                   if is_spread else
                   ("OVER" if p>.5 else "UNDER" if p<.5 else "TIE"))
        variants[name]={
            "variant_name":"ROBUST_EQUAL_COMPANY_CENTER_WITH_DISAGREEMENT",
            "market":name,"line":entry.get("line"),
            "signed_home_handicap":entry.get("signed_home_handicap"),
            "first_side_probability":round(p,9),"direction":direction,
            "independent_companies":stat["independent_books"],
            "market_center":mu,"uncertainty_sigma":round(sigma_adj,7),
            "baseline_probability":entry.get("first_side_probability"),
            "not_trained_or_promoted":True,
            "no_water_side_assumption":True,
        }
    return features,variants

def selftest():
    from datetime import timedelta
    t=stamp("2026-11-02T13:35:00Z")
    def market(v,s):
        return {"status":"CONSENSUS_AVAILABLE","median_line":v,
                "quotes":[{"company_id":str(i+1),"line":v+d,
                           "source_capture_utc":s,
                           "excluded_as_line_outlier":False}
                          for i,d in enumerate((-.5,0,.5,1,0))]}
    a=market(-7.5,"2026-11-02T09:00:00Z")
    b=market(-9.5,"2026-11-02T13:30:00Z")
    assert center(b,t,"full_spread")["independent_books"]==5
    m=movement(a,b,stamp("2026-11-02T09:02:00Z"),t)
    assert m["market_signal"]=="BROAD_FALLING"
    assert m["same_company_pairs"]==5 and m["decreased"]==5
    # Three identical companies all strengthen HOME, but departing high-line
    # companies make the unrelated group medians move in the opposite direction.
    from copy import deepcopy
    old=market(5,"2026-11-02T09:00:00Z")
    new=market(6,"2026-11-02T13:30:00Z")
    old['median_line']=10;new['median_line']=6
    paired=movement(old,new,stamp("2026-11-02T09:02:00Z"),t)
    assert paired['median_change']==1 and paired['unpaired_consensus_change']==-4
    assert paired['market_signal']=='BROAD_RISING'
    unchanged=deepcopy(new)
    for q in unchanged['quotes']:q['line']-=1
    unchanged['median_line']=20
    assert movement(old,unchanged,stamp("2026-11-02T09:02:00Z"),t)['market_signal']=='UNCHANGED'
    # Never allow the opposite price slot or home/away reversal to leak.
    a["quotes"][0]["company_id"]="2"
    assert len(books(a,t))==3
    assert not movement(a,b,t,t)["same_company_pairs"]
    print("NBA_INDEPENDENT_007_MULTIBOOK_CROSSPLAY_FEATURE_SELFTEST_PASS")
if __name__=="__main__":selftest()

