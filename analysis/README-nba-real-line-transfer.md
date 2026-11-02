# 23,574 pregame scores -> 1,312 cross-checked real opening/closing market thresholds

## Goal

Prior score-only model (#210) estimated margin and total MAE, but its 225.5 total diagnostic is not a market quote. This research tests independent predicted margin/total distribution at **actual historical NBA opening and closing point spreads and totals**, and compares to source-provided fair market probabilities when they exist.

## Data and chronology

- 23,574 unique historical NBA records (source SHA256 pin), including completed scores. No target-game historical price or market line is a score model input.
- 20,444 old games train score-only ridge candidates; 1,255 games from 2023-24 choose baseline/enhanced/decay via pre-fixed validation MAE thresholds.
- 1,312 real source opening/closing game-level consensus prices and line stages from 2024-25, cross-checked against independently scored NBA line sheet. The exact historical quote-update timestamps are unavailable; quoted stages are not guaranteed to have been available at arbitrary 30m/2h cutoffs.
- This 2024-25 season has been previously inspected by other research. These results are retrospective diagnostic evidence, not untouched prospective validation.
- Join strictly by ET game date, independently normalized home and away, unique match identity and final score. Reject mismatches and push grades.
- Model home-cover probabilities evaluate P(home margin + signed home spread > 0); total over probabilities evaluate P(final total > line); spread signs come from source explicit signed-home line validated by score.
- Closing source market provides h2h, ATS, total probability. Opening source only provides h2h probability; no fake opening spread/over prices are inferred. The entire 1,312-game dataset is used only for evaluation, not training model weights.

## Reproduce

    python3 analysis/nba_historical_real_line_transfer.py --selftest
    python3 analysis/nba_historical_real_line_transfer.py --out /tmp/nba-real-line-transfer

The workflow outputs six real-line cohorts, Brier/accuracy/log loss, pair-by-date confidence intervals for compared model/market probabilities, source rejections, and strict no-promotion flags. Does not change existing collectors, independent model weights, Crown ID3, Jingcai, Cloudflare, PushPlus, or regular production workflows.

## Promotion rule

A lower score on historical line data does not justify adding a model to production. Promotion requires independent genuine pregame quote time, source licensing and identities, actual production five-market calibration on newly frozen prospects, and statistically defensible improvement over the currently running model at each market line.
