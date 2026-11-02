# NBA multi-book as-of score backfill — 2026-11-02 UTC

**Purpose:** Fill genuinely frozen, pre-tip NBA sportsbook quotes with verified
final-score labels; do not disturb production collection, prediction, or PushPlus.

## Reproduced results

Input: repository's two previously archived The Odds API NBA captures
(2026-10-28 and 2026-10-29), existing settled scores, and independent ESPN
completed scoreboards for the missing matches.

- **15 independent completed NBA games**, 9 quote providers.
- **405 validated bookmaker-market observations**: 135 h2h, 135 signed home
  handicap, 135 full-game O/U. These are **15 games**, not 405 independent
  observations; never split different books from one event into train and test.
- Pre-tip snapshot, actual bookmaker market-last-update UTC, signed home
  handicap, price-side labels, both decimal prices, score source and score are
  retained; price staleness at most 90 minutes and >=30 minutes before tip.
- Original saved odds-score records graded 3 events (81 quote rows). An ESPN
  completed-score crosscheck supplies **12 additional complete events (324
  newly graded market/book rows)**.
- Exact line multi-book benchmark (>=3 books on the identical spread/total):
  moneyline 15 games, Brier **0.185273**, 11/15 direction hits; spread 15,
  Brier **0.249338**, 9/15; O/U 15, Brier **0.250749**, 6/15. These are
  **market no-vig consensus scores, not performance of our predictive model**.

## Cross-source ledger correction

The existing research-only #207 unified ledger has 1,375 pre-tip quote
observations spanning 36 games: 970 from 007 plus 405 from the independent
bookmaker source. Prior settlement coverage was 20 unique games (17 from 007
and 3 from the independent provider). After strictly joining all 405 rows by
**event ID, bookmaker, market, capture time, price, source last update,
team, market line and tipoff**, 32 **distinct** games have linked final-score
labels (17 from 007, 15 from the independent provider). The 12 new scored
games are not new quotes or new independent original games. A separate
`nba_multisource_score_backfill.py` script performs this update without
mutating 007 raw slot direction or existing labels.

## Remaining gates

- 32 score-labeled games with authentic pre-tip quote captures are not enough
  to train and validate a five-market model reliably.
- 007 raw quote slot-to-side pricing needs separate source certification; it
  is *not* price-probability-ready.
- The 23,574 retrospective historical NBA odds+results records are a useful
  larger date-level market benchmark but **lack independently verified quote
  timestamps**. They must not be silently treated as 23,574 timestamped
  market changes.
- Different line levels are not the same event; the exact-line benchmark
  avoids blindly averaging probability values across different handicaps.

## Reproducible execution

```sh
python3 analysis/nba_multibook_asof_settled_ledger.py \
  --repo-root . --out /tmp/nba-multibook-asof
python3 analysis/nba_multibook_same_line_consensus.py \
  --source /tmp/nba-multibook-asof/multibook_asof_settled_only.jsonl \
  --out /tmp/nba-multibook-asof/consensus
# After producing #207 cross-source JSONL:
python3 analysis/nba_multisource_score_backfill.py \
  --prior-ledger /path/to/all_providers_pretip_odds.jsonl \
  --new-scores /tmp/nba-multibook-asof/multibook_asof_settled_only.jsonl \
  --out /tmp/nba-multibook-verified-union
```

All new workflows are research-only and on-demand/PR-triggered; no schedule,
weights, production fixtures or notifications changed. Do not auto-promote
on the basis of the 15-game sample.
