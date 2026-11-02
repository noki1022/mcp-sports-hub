#!/usr/bin/env python3
"""Find EXACT cause of repeated 007 JC fixture-number identity failures.

Audit is DATA-ONLY and never repairs by fabricated home/away reversal. This
script logs the *original* team aliases in 007's JC fixture XML alongside
the 007 market-board home/away, for exact 007 game ids only. It does not
read results, scores, independent model, odds, or secrets.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_007_jc_fixture_identity import records,comparable,TARGET,MAX_BYTES
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy

AUDIT_IDS=("728298","728884")
def sides(board,feed,game_id):
    game=next((g for g in board.get("nba_cba_games",[])
               if str(g.get("game_id"))==str(game_id)),None)
    if not game:return {"game_id":game_id,"status":"NOT_IN_THIS_BOARD"}
    row=feed.get(game_id)
    if not row:return {"game_id":game_id,"status":"EXACT_ID_NOT_IN_LIVE_JC_FIXTURE_FEED",
                       "board_home":game.get("home_team"),
                       "board_away":game.get("away_team")}
    h=game["home_team"];a=game["away_team"]
    hh=comparable(h,row["home_aliases"])
    aa=comparable(a,row["away_aliases"])
    ha=comparable(h,row["away_aliases"])
    ah=comparable(a,row["home_aliases"])
    return {
        "game_id":game_id,"board_home":h,"board_away":a,
        "raw_source_home_aliases":row["home_aliases"],
        "raw_source_away_aliases":row["away_aliases"],
        "raw_source_sale_label":row["match_label"],
        "exact_game_id_match":True,
        "home_matches_source_home":hh,
        "away_matches_source_away":aa,
        "home_matches_SOURCE_AWAY":ha,
        "away_matches_SOURCE_HOME":ah,
        "same_side_identity_verified":hh and aa,
        "reversed_source_side_identity":ha and ah and not(hh and aa),
        "name_variant_or_one_side_mismatch":not(hh and aa) and not(ha and ah),
        "original_feed_trust_not_upgraded":True,
    }
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--board",required=True)
    p.add_argument("--fixture-bytes")
    p.add_argument("--out",required=True)
    a=p.parse_args()
    board=json.loads(Path(a.board).read_text(encoding="utf-8"))
    if a.fixture_bytes:
        raw=Path(a.fixture_bytes).read_bytes()
        method="ORIGINAL_EXPLICIT_FILE"
    else:
        policy,status=robots_policy()
        if policy is False or (policy is not None and not policy.can_fetch(UA,ORIGIN+TARGET)):
            raise RuntimeError("SOURCE_NOT_PERMITTED_"+str(status))
        raw=get_bytes(ORIGIN+TARGET,MAX_BYTES)
        method="PERMITTED_LIVE_PUBLIC_007_JC_FIXTURE"
    feed=records(raw)
    data={"schema_version":"nba-jc-identity-incident-forensics-v1",
          "source":ORIGIN+TARGET,"method":method,
          "fixture_feed_exact_id_count":len(feed),
          "requested_display_date":board.get("requested_display_date"),
          "cases":[sides(board,feed,gid) for gid in AUDIT_IDS],
          "not_a_forecast_or_result":True,
          "no_predictions_or_prices_rewritten":True}
    Path(a.out).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    print("JC_IDENTITY_DIAGNOSIS",
          json.dumps(data,ensure_ascii=False))
if __name__=="__main__":main()
