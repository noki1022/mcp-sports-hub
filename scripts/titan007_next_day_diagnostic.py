#!/usr/bin/env python3
"""One-off read-only diagnostic of target-day NBA/CBA market-identity joins.

Only aggregate counts are printed; raw downloaded source records are ephemeral.
Never substitute nearby dates or assume source display timezone.
"""
import collections,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import titan007_join_daily as source
import titan007_bf_snapshot as odds

def main():
    date="2026-10-31"
    market=odds.parse(odds.download_once())
    matches,rejected=source.identify(source.public_get(source.SCORES_URL))
    odds_ids={str(x["game_id"]) for x in market["records"]}
    src_ids=set(matches)
    dates=collections.Counter(x["display_date"] for x in matches.values())
    leagues=collections.Counter(x["league"] for x in matches.values())
    nba_cba=[x for x in matches.values() if x["league"] in source.VALID_LEAGUES]
    intersection=src_ids&odds_ids
    matched=[matches[x] for x in intersection]
    dates_joined=collections.Counter(x["display_date"] for x in matched)
    dates_nba=collections.Counter(x["display_date"] for x in nba_cba)
    nba_matched=[x for x in matched if x["league"] in source.VALID_LEAGUES]
    report={
      "target_date":date,
      "identity_feed":source.SCORES_URL,"market_feed":odds.SOURCE,
      "scoreboard_records":len(matches),"odds_records":len(odds_ids),
      "ids_intersection_all_dates":len(intersection),
      "id_intersection_nba_cba":len(nba_matched),
      "source_dates":dict(sorted(dates.items())),
      "nba_cba_source_dates":dict(sorted(dates_nba.items())),
      "joined_dates_all_leagues":dict(sorted(dates_joined.items())),
      "nba_cba_scoreboard_total":len(nba_cba),
      "nba_cba_target_date_in_scoreboard":sum(x["display_date"]==date for x in nba_cba),
      "nba_cba_target_date_ids_in_odds":sum(x["display_date"]==date for x in nba_matched),
      "all_target_date_ids_in_odds":sum(x["display_date"]==date for x in matched),
      "scoreboard_rejects":len(rejected),"odds_rejects":len(market["rejected"]),
      "time_zone":"UNVERIFIED",
      "raw_data_stored":False,
    }
    print("TITAN_NEXT_DAY_JOIN_DIAGNOSTIC "+json.dumps(report,ensure_ascii=False,sort_keys=True),flush=True)

if __name__=="__main__":main()
