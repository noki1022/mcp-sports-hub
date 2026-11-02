# Current roster crosswalk: **prospective only**, never retroactive

## Why

Existing archived injury shadow #217 had 60 listed injury players, 39 with source player IDs and historical pretip minutes in #218, but only 25 with independently observed same-team playing history from the current 2026-27 season. It would be **incorrect** to assume a player who hasn't played this season is automatically still rostered with last year's team.

This separate research job captures the current ESPN team roster for each NBA franchise, with exact UTC fetch time, URL and SHA256. It joins ESPN `athletes[].id` to the player-game-log's **different NBA person-ID namespace** only through normalized unambiguous names and current team. It computes past same-team minutes from games dated **strictly before collection day**, and refuses ambiguous names, duplicate membership and insufficient past minutes. A player who just joined a new team gets no borrowed old-team minutes.

## Strict as-of limitations

A roster downloaded in November 2026 was **not available at the older October/November 1 frozen injury forecasts**. Do not attach this future evidence to the 11 historical shadow games or claim it retroactively qualified them. This artifact may only help predictions whose own tipoff follows the actual new roster capture (and must be rechecked for freshness/transfers at that tip). The roster source is ESPN's public roster endpoint, **not** NBA official injury PDF. It is not evidence of whether a particular player was healthy or expected to play. In particular, ESPN athlete IDs are NOT equal to NBA Stats player IDs.

This module exports only a standalone research JSONL plus audit. Its player-feature vectors cannot be loaded by the current production injury model, cannot automatically enable `PLAYER_IMPACT_APPLIED_EXPERIMENTAL`, do not change the existing frozen injury model predictions and never create fabricated injury coefficients. Original 007, confirmed Crown ID3, Jingcai, 21:30 and 06:30 slots, Cloudflare and PushPlus are untouched.

## Reproduce

    python3 analysis/nba_current_roster_id_crosswalk.py --selftest
    python3 analysis/nba_current_roster_id_crosswalk.py --out /tmp/nba-current-roster-crosswalk-research

Separate on-demand and PR-only CI artifact; source hashes/times included for future provenance. No recurring extra automation or new live signal.
