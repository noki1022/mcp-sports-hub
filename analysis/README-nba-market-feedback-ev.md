# Genuine as-of multibook market feedback (research-only, no production changes)

## What we have implemented

This study connects existing captured real sportsbook prices, actual book last-update clocks and independent completed finals. It does not claim the production NBA model is profitable or imply real bets were executed.

- Reuse the existing multibook source validator and score ledger (15 independent completed games, nine books, 405 book/market rows in the last documented cohort). Never treat 405 rows as independent games.
- Require a published pre-tip snapshot between 30 minutes and 24 hours prior to tip, with each book price update at most 120 minutes before snapshot.
- For each game and market (moneyline, signed-home handicap, total), take the latest eligible snapshot; require three separate bookmakers at the EXACT SAME line. Never merge -5.5 and -6.5 or different totals.
- Compute a target bookmaker's benchmark from the median no-vig probabilities of OTHER bookmakers at the exact line. Exclude the target's own price; examine both first and second side EV using the target's own decimal price.
- Select at most one opportunity per game/market using a fixed 3% estimated EV rule; choose without seeing results. Push pays zero, win pays decimal price minus one, loss pays minus one. Score realized SIMULATED ROI and net units, never claim executable odds or positive expected returns.
- Optional genuine independent model prediction requires exact source event ID, teams, market, line, tip, before-quote capture and frozen model artifact SHA. Without this input model vs market comparison is explicitly unavailable.
- Fail closed on unknown raw 007 price slot directions, unverified odds clocks, duplicate book-market snapshot, score mismatch, unverified score final observation clock, price/no-vig disagreement, invalid or conflicting team identities.

## Key scientific and production limits

The current real bookmaker ledger supplies three broad markets, NOT a certified corresponding five-market Jingcai/Crown outcome/price tape. Crown stays the known 007 institution ID3. Existing 007 raw slot-to-price side mapping still lacks independent source proof, and must be resolved before an EV claim for that source.

Historical 23,574 odds/result rows and 1,312 open/close records do not have independently certified original bookmaker price-update times. They may be studied retrospectively but are not true archived 30-minute quotes. Repeated bookmaker rows or intraday snapshots of one match are not independent games.

The acceptance counter requires at least 100 independent games and 24 separate Beijing calendar dates PER market to even consider a later chronological OOS evaluation; it does not prove enough power, positive EV, or profitability. Model weight selection must be validation-only and final results assessed on genuinely untouched future cohorts. This module never changes the existing model, 007 collection, Jingcai, Crown ID3, official injury gate, mobile pushes, Cloudflare or scheduled workflows.

## Reproduce with real preexisting sources

    python3 analysis/nba_market_feedback_ev.py --selftest
    python3 analysis/nba_multibook_asof_settled_ledger.py --repo-root . --out /tmp/nba-multibook-asof
    python3 analysis/nba_market_feedback_ev.py --source /tmp/nba-multibook-asof/multibook_asof_settled_only.jsonl --out /tmp/nba-market-feedback

The PR/manual workflow writes source-hashed market_feedback_scorecard.json and asof_feedback_opportunities.jsonl artifacts retained for 60 days; it does not add any cron or paid odds API request.

## Optional frozen independent model input

One JSONL prediction per exact event, market and line must have these fields: source_type=INDEPENDENT_PRETIP_MODEL; event_id; market (h2h/spreads/totals); line (null for h2h); home; away; tipoff_utc; captured_at_utc; probability_first_side; frozen_model_artifact_sha256 (64 hex digits). Independent verification of the SHA against the real immutable original artifact remains the ingestion workflow's responsibility. Never pass a market-derived no-vig probability as a supposed independent model.

## Next meaningful improvement

Certify the raw 007 first/second water-price sides and real timestamped JC/Crown quote exposure, link the already sealed actual production model probabilities by game+line+decision slot, and run paired market-only versus model-only versus model+market comparisons with time-aware bookmaker executable prices, Brier/logloss/calibration and returns. Add clustered uncertainty and a true chronological untouched holdout. No market-fusion or production promotion without evidence.
