# Three NBA market probabilities: cross-book odds baseline vs evidence-based calibration

## P0 question

Can a source-verified 23,574-score opponent-strength model improve **moneyline, home spread, and over/under** Brier and accuracy at actual cross-book consensus closing lines, instead of producing weaker independent probabilities?

An earlier 1,312-game analysis showed the independent score model underperformed markets on all three. This experiment tests whether calibrated small *residual corrections* to market probabilities help, and absolutely permits the market alone to win selection.

## Provenance and time boundaries

Historical training set: 23,574 unique NBA final-score game dates; opponent-adjusted model fitted ONLY on completed games in seasons through 2022-23. Its 2023-24 development work was previously examined.

Real market cohort: 1,312 independently cross-checked game-level consensus opening+closing prices and signed-home spreads/total lines from 2024-25. Games are disjoint and grouped by Eastern calendar date. Split the 2024-25 dates chronologically: initial 46% for fitting market corrections, next 25% for candidate selection, final 29% for later evaluation. No same-day game may enter two partitions.

Candidates: market-only, calibrated logit intercept, calibrated logit intercept/slope, market plus opponent-adjusted independent-strength disagreement, and market plus strength+observed closing line movement. Corrections have strong predeclared L2 penalties and use true completed scores ONLY from earlier chronological calibration games. A challenger must improve previous validation Brier by >0.0005; otherwise retain **unmodified market probability**. Evaluation prints Brier, logloss, accuracy, per-calendar-date paired 95% uncertainty intervals.

Closing spread and total outcomes are computed from source-verified explicitly signed home line and total line. Pushes excluded, never counted as wins. Actual bookmaker quote-update UTC is UNKNOWN, and the source is cross-book consensus, NOT verified 007/Jingcai/Crown tick history. Retrospective 2024-25 outcomes already examined in the project: the later split cannot be represented as untouched blind validation or 2026-27 profitability.

## Acceptance

Training evidence, real date boundaries, cohort sizes, and zero live production changes are all checked by an isolated PR/manual GitHub Actions workflow. No deployed model, injury prerequisite, market parser, 007 ID3 Crown feed, Jingcai priority, Cloudflare scheduling or PushPlus notification is changed. Research only; eventual promotion requires newly frozen pregame 007 snapshots and genuinely new outcomes, superiority to current production forecasts and proper calibration.

Run:

    python3 analysis/nba_market_conditional_calibration.py --selftest
    python3 analysis/nba_market_conditional_calibration.py --out /tmp/nba-market-conditional-calibration.json

Full report is retained as Actions artifact for 60 days.
