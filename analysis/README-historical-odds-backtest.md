# Historical odds feature backtest

`analysis/nba_odds_feature_backtest.py` is a fail-closed research path for adding verified
pregame market information to the NBA model. It consumes only locally archived, normalized
The Odds API rows and a frozen completed-results file; it never calls an API.

The feature vector is built from one latest pre-tip quote per bookmaker and market in the
selected phase (default `PRE_GAME_FIXED`):

- no-vig home moneyline probability;
- no-vig home spread-side probability and home handicap line;
- no-vig over probability and total line;
- bookmaker counts.

Rows are joined by event ID first, then by an exact home/away pair with a unique result within
36 hours. Quotes after tipoff, malformed timestamps, ambiguous joins, incomplete markets, and
other phases are rejected. The model is a ridge probability model fit on the first 60% of
chronological settled events; the final 20% is held out and never used for tuning. It reports
Brier and log loss against the market-only probability and a base-rate baseline.

The current repository snapshot intentionally contains no completed results for the archived
2026-10-28 odds snapshot, so the report must return `INSUFFICIENT_SETTLED_ODDS` rather than
manufacture a backtest. Once completed, timestamp-matched result rows are archived, rerunning
the workflow will produce the first honest market-feature comparison.
