# 007 genuine pre-tip quote — independent final-score gap fill (research only)

## Why

PR #207 admitted 970 genuine stored 007 market observations across 21 games,
but only 17 fixtures had independently linked settled scores. PR #208 filled
12 previously ungraded **non-007** games; 007's remaining missing finals were
not independently backfilled. A quote count is not an independent game count.

This new module attempts the missing 007 finals using ESPN's *completed*
postgame NBA scoreboards. It does **not** fetch past 007 prices today or
create unobserved historical odds timestamps.

## Source and matching gates

1. Reconstruct only original archived 007 pre-tip observations via
   \`nba_007_historical_odds_backfill.reconstruct\`. Source-fetched timestamps
   (not underlying bookmaker tick times) remain unchanged.
2. Request the real ESPN completed scoreboard for each required UTC game day
   and its adjacent US date, with a maximum of 10 day requests. The source is
   used **only for final-score labels**, never as a pre-game feature.
3. Accept only an exact ESPN event ID, matching canonical home and away NBA
   team abbreviations, and tipoff difference within three hours.
4. Reject unresolved scores, source conflicts, changed 007 identities and
   old-vs-independent final-score disagreements. The latter are quarantined,
   never overwritten or counted as usable labels.
5. Recompute spread/total result using the existing 007 canonical settled
   direction calculation. Preserve the user-confirmed Crown company ID3
   and existing raw quote side slots; do **not** claim their price-side
   orientation is independently certified.
6. Persist JSONL and a SHA256-based audit as CI artifacts for 60 days. Original
   007 reporting and scheduled workflows are not touched.

## Run

\`\`\`sh
python3 analysis/nba_007_independent_score_backfill.py --selftest
python3 analysis/nba_007_independent_score_backfill.py \
  --repo-root . --out /tmp/nba-007-independent-score-backfill
\`\`\`

Outputs:

- \`007_real_pretip_quotes_with_independent_final_scores.jsonl\`
- \`audit.json\`

Watch \`newly_labeled_games\` rather than added quote-row count. Previously
settled games and this new backfill belong to the **same original 21-game
cohort**; do not add them as new market matches. The 23,574 game-date archive
still lacks authentic quote publication times and remains a separate research
benchmark.

## Production gate

No automated model promotion, EV/ROI claim, write to original 007 data,
Cloudflare/GitHub schedules, or PushPlus notification. Historical work must
not contaminate training with postgame scores as model input.

**A real increase in eligible historical samples is confirmed only by the
GitHub Actions artifact's \`newly_labeled_games\` and CI acceptance result,
not by the presence of this script.**
