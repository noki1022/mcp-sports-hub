# 23,574 historical NBA games: independent score-only strength study

## Goal and data evidence

Can actual NBA score history improve independently predicted game margins and totals, not merely copy market prices?

The 23,574 accepted NBA games have date, teams and home/away final scores. The original historical bookmaker quote-update timestamps, spread-side orientation, and upstream data redistribution rights are unverified. Research uses NO historical prices or market lines as features.

## Leakage protection

- All features on date D built strictly from games dated before D. Same-day games are updated after all features are constructed.
- Short/long team form, scored/allowed points, venue, rest, wins and prior completed-game league scoring levels only.
- Train: seasons through 2022-23. Validation-only model choice: 2023-24.
- Evaluation: 2024-25 and 2025-26, already looked at by other project studies; these are NOT a truly untouched holdout.
- Compare baseline ridge, richer score-only ridge, and recency weighted richer ridge for score margin and total; precommitted minimum MAE gains.
- Report MAE, RMSE, accuracy and Brier with training-derived residual spread; fixed 225.5 total line diagnostic is NOT bookmaker evidence.
- Refit on all 23,574 original games separately for prospective shadow coefficients, not retroactive model validation.

## Reproduce

    python3 analysis/nba_23574_score_only_strength.py --selftest
    python3 analysis/nba_23574_score_only_strength.py --out /tmp/nba-23574-score-only.json

The CI artifact includes model coefficients, split counts, actual errors, validation choices, paired-game-date bootstrap and provenance. Research never touches production features, 007/Crown collection, scheduled workflows, cloud scheduler, injury gates, PushPlus, or final recommendation model.

No production deployment is authorized by one historical evaluation. Any prospective integration needs genuine post-2026 training-free score verification, reliable as-of data and market side tests.

## Additional market-plus-strength experiment

On the same historical game-date benchmark only, compare market no-vig moneyline
to a prespecified weighted blend with independent prior-score win probability.
Weights 0/10/20/30/40/50% strength are selected solely on 2023-24
validation Brier, with a required >=0.0005 improvement over market-only.
Score the chosen blend on previously examined 2024-26 evaluation, including
date-grouped paired Brier confidence intervals. This is a retrospective test
and **does not imply the historical price was actually available pre-tip**.
Only if a fresh independent prospective dataset proves improvement could
such a blending strategy be considered for existing production.
