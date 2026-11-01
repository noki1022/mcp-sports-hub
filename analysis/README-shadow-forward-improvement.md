# NBA Shadow Forward Improvement Research

## Scope
This isolated research experiment does not alter production probabilities, reports, schedules, GitHub Actions production workflows, or PushPlus. It intentionally excludes the previously inspected 2025-26 holdout and 2026-27 monitor.

## Pre-registered folds
- 2022-23 late-season: fit 2021-22, calibrate 2022-23 through 2023-01-15, evaluate 2023-02-01 through 2023-04-09.
- 2023-24 late-season: fit 2021-22 and 2022-23, calibrate 2023-24 through 2024-01-15, evaluate 2024-02-01 through 2024-04-14.
- 2024-25 late-season: fit through 2024-12-15, calibrate 2024-12-16 through 2025-01-31, evaluate 2025-02-08 through 2025-04-13.
- A seven-day embargo separates calibration and evaluation in each fold. Every split is by complete calendar date.
- Ridge alpha is frozen at 100; no tuning on evaluation labels.

## Candidate experiments
1. Existing form + H2H + Elo features.
2. Add calendar rest/B2B, games in previous four days, and recency-weighted H2H features.
3. For both feature sets compare normal residual probabilities against a smoothed empirical residual CDF (Silverman bandwidth), fitted only on the separate calibration partition.

## Outcomes
Report margin/total MAE and RMSE; Brier, log loss and ECE for pre-registered spread/total thresholds; paired calendar-day bootstrap intervals for key threshold comparisons.

## Limits
Thresholds are research probes, not historical bookmaker lines. Historical source publication timestamps and matched 007 JC/Crown odds are unavailable in these files, so no EV/ROI claim is possible. No candidate can be promoted from this report alone; a new untouched future evaluation is required.
