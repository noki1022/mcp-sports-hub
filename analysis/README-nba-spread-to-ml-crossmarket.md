# Spread movement as evidence for NBA independent moneyline probability (research only)

## Why this is the correct cross-market question

When a signed HOME handicap moves from **-7.5 to -9.5**, the market's implied expected home margin typically strengthens by two points. It can corroborate a higher probability of HOME MONEYLINE winning even though the home team's probability of covering the **new -9.5 line** need not rise. These three statements are not interchangeable.

Existing project research has mostly used multi-book consensus as same-line price reference or arbitrage/EV study. This experiment explicitly measures the signal transferred between **NBA spread movement and home moneyline probability** using the 1,312 independently score-crosschecked 2024–25 cross-book opening/closing consensus games. It tests whether spread changes tell us something *in addition to what closing moneyline has already priced in.*

## Valid source and strict boundaries

- Reuses `nba_hf_open_close_crosscheck.py` and the pinned historical game/score cross-check. Those source lines have actual source-defined **OPEN vs CLOSE stages and verified game tip UTC**, but original bookmaker quote-update times are unknown. Never interpret closing odds as something available at 12:00, 18:00, 21:30 or 30 minutes pretip.
- Signed home handicap convention: home -7.5 becomes home -9.5 => opening signed line -7.5, closing signed line -9.5, `open_minus_close = +2.0` means **movement in favor of home**. For home +7.5 to home +5.5, the same home-favorable movement is +2.0.
- The raw 1,312 matches are a subset of the preexisting ~23.6k historical games; never count them twice. Dates and game IDs split exclusively by Eastern calendar date into earlier training, middle calibration selection and a later **previously investigated** evaluation period.
- Estimate an actual fitted historical *market response* of home moneyline log-odds to every two points of spread movement from earlier training only. Report an illustrative 80% open ML plus +2-point spread change as a **research-only** market-price bridge. It is not an independently validated player/roster/team model probability or a fixed +5pp adjustment.
- Independently, test whether adding the same spread signal to the **already moved closing ML probability** reduces actual outcome Brier/logloss, compared against unmodified closing ML. Earlier training fits coefficient under heavy shrinkage; only previous validation chooses among fixed weights (0/0.25/0.5/1) if Brier improves >=0.0005 without excessive logloss deterioration. No holdout-driven tuning.
- Compare empirical win rates when the spread moved >=1.5 in favor of home vs >=1.5 in favor of away, including their opening and closing market probabilities. These raw groups are **not causal estimates** and not the incremental predictive result; the close-market-plus-movement comparison tests incremental information.
- All analyses are isolated PR/manual research. No production 007 collection, Jingcai, Crown ID3, injury, shadow live probabilities, model weights, Cloudflare, PushPlus or automated schedules are changed. A later real-asof prospective experiment, live model pairing, independent ML probabilities and additional real outcomes are needed before any adjustment can be considered.

## Reproducible run

    python3 analysis/nba_spread_to_ml_shadow.py --selftest
    python3 analysis/nba_spread_to_ml_shadow.py --out /tmp/nba-spread-to-ml-shadow.json

The PR/manual CI runs the historical source crosschecks, the conservative selftest, quantitative evaluation and non-promotion guards. Artifacts are retained for 60 days, not committed as bulky raw datasets.

## Next-stage multi-book extension

The already-merged `nba_market_feedback_ev.py` preserves genuine timestamped nine-book same-line snapshots, per-book no-vig probabilities and changes. Once **two or more** independently captured pretip snapshots per match exist for a representative future cohort, the same signed-home-line movement, breadth across distinct institutions, agreement/disagreement with contemporaneous ML price and **asof-before-forecast model** can be scored without using a closing quote that was not known at decision time. This research does not claim to have historical nine-company tick-by-tick line movement for the 1,312 cross-book records.
