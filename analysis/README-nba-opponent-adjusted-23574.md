# NBA opponent-adjusted historical model evaluation (23,574 games)

**Objective:** challenge existing independent score-only margin and total models with opponent strength adjustment.

The available historical game-score dataset is used to compute date-frozen online opponent-adjusted Elo, power, offensive and defensive scoring ratings. Any current-day result updates the ratings only *after all games that day have been predicted*. This prevents same-date contamination. Ratings are regressed to mean between seasons. No target-game bookmaker quote, after-tip update, sportsbook line, or result may be a pregame feature.

Fit the same standard regularized linear score models on the 20,444 oldest games. Lock selection from 1,255 2023-24 validation games with minimum MAE improvement: 0.08 margin points or 0.10 total points. Evaluate the frozen candidates against the 1,875 previously exposed 2024-26 games and the cross-scored 1,312 2024-25 real closing-market spreads and totals.

The latter dates were used by prior project studies. This is not fresh untouched OOS. Quote update timestamps of retrospective cross-bookmaker source are unverified. Market is a comparison reference, not a validated actual 007 historical quote or user-facing Crown ID3. No five-market profit claim.

Model acceptance requires meaningful validation and genuinely new prospective game results, stable proper probability metrics and actual side-verified 007 snapshots. No model is automatically inserted into production and the existing scheduler, original 007 feeds, injury prerequisites, Cloudflare and PushPlus are untouched.

Reproduce:

    python3 analysis/nba_opponent_adjusted_23574.py --selftest
    python3 analysis/nba_opponent_adjusted_23574.py --out /tmp/nba-opponent-adjusted-23574.json

All evaluated results and rejections are CI artifacts for 60 days.
