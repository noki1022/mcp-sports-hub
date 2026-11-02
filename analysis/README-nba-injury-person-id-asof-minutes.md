# Existing injury shadow: stable player ID and genuine earlier-game minutes

## Purpose

Do not create another injury model. The existing 21:30 NBA injury shadow archives pretip original-model probabilities and official NBA injury-report status. It has **zero qualified injury-model paired probabilities** until a real frozen player-availability correction exists.

This module uses actual 2025-26 and 2026-27 *played NBA player-game logs* and matches each archived official injury name to source player IDs. All player-minute statistics are computed from only strictly **earlier game dates**, never the forecasted game's minutes, later game results or a different team's roster. An inability to find a played row does **not** prove that the player was healthy or had zero minutes.

## Strict data gates

- Read the original archived `nba_injury_prospective_2130.json`, same-snapshot `nba_priority_model.json` and verified fixture. Match exact ESPN event ID, 007 ID, original home and away, official report timestamp and original probability. Preserve source SHA256.
- Read two versioned season Parquet files from `cbratkovics/nba-game-logs`: player stable `player_id`, `game_id`, game date, name, team and minutes. Source data originates from third-party NBA/Kaggle derivatives; its claimed license does not certify NBA underlying rights.
- Reject duplicate player games, invalid teams and minutes; quarantine a stable player ID if it has inconsistent normalized names. A shared name with multiple unique player IDs is **ambiguous**, not joined.
- Match official report name to stable ID and reported team, require at least 3 prior games for same team and use the last up-to-8 games' historical minutes. Prior player team must match the reported team, otherwise fail closed for trades.
- Distinguish **current-season verified played membership** from a player last seen with that team in a previous season, rather than assuming the latter is a valid 2026-27 roster confirmation.
- A name-only official report is not a verified NBA player ID. Match results and prior-minute data are research evidence only, NOT a production `replacement_pregame_features` vector.
- No inferred original injury-report publication clock, no historic source price timestamps, no injury effect coefficient or final recommendation probability manufactured. Never use target-game outcomes as training input.

## Outputs

`audit.json` and `injury_existing_shadow_player_asof_evidence.jsonl` with the original frozen event IDs, archived snapshot hash, per-player matching status and verified earlier-game minutes. Unknown, stale prior-team membership, ambiguous names and insufficient histories remain explicitly unresolved.

Reproduce through PR-only CI:

    python3 analysis/nba_injury_person_id_asof_minutes.py --selftest
    python3 analysis/nba_injury_person_id_asof_minutes.py --root . --out /tmp/nba-injury-stable-identity-asof-minutes

No automatic promotion or edits to production model, 007 Crown ID3/Jingcai sources, the already running original injury shadow, 21:30/06:30 scheduling, Cloudflare or PushPlus.

## Remaining evidence requirement

For *genuinely paired* injury probabilities the team still needs independently confirmed current roster membership for players not yet seen this season, historical player rotation/replacement signals available at the original as-of clock, a frozen validated coefficient artifact matching the current production base model, and an actually prospective game cohort sufficiently large to measure Brier and five-market impact. Historical studies on previously inspected 2025-26 results cannot fill that gate.
