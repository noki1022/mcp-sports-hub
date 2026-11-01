# NBA Shadow Forward Improvement Research

## Scope
This isolated research experiment does not alter production probabilities, reports, schedules, GitHub Actions production workflows, or PushPlus. It intentionally excludes the previously inspected 2025-26 holdout and 2026-27 monitor.

## Pre-registered folds
- 2023-24 forward 1: fit through 2023-04-10, calibrate 2023-10-24 through 2023-12-01, evaluate 2023-12-09 through 2024-01-15.
- 2023-24 forward 2: fit through 2023-12-01, calibrate 2023-12-02 through 2024-01-15, evaluate 2024-01-23 through 2024-02-29.
- 2023-24 forward 3: fit through 2024-01-15, calibrate 2024-01-16 through 2024-02-29, evaluate 2024-03-08 through 2024-04-14.
- 2024-25 late-season: fit through 2024-12-15, calibrate 2024-12-16 through 2025-01-31, evaluate 2025-02-08 through 2025-04-13.
- Evaluation windows are disjoint; each fold is a separate rolling-origin deployment simulation.
- A seven-day embargo separates calibration and evaluation in each fold. Every split is by complete calendar date.
- Ridge alpha is frozen at 100; no tuning on evaluation labels.

## Candidate experiments
1. Existing form + H2H + Elo features.
2. Add calendar rest/B2B, games in previous four days, and recency-weighted H2H features.
3. For both feature sets compare normal residual probabilities against a smoothed empirical residual CDF (Silverman bandwidth), fitted only on the separate calibration partition.

## Outcomes
Report margin/total MAE and RMSE; Brier, log loss and ECE for pre-registered spread/total thresholds; per-fold and pooled metrics across all disjoint evaluation windows; paired calendar-day bootstrap intervals for key threshold comparisons.

## Limits
Thresholds are research probes, not historical bookmaker lines. Historical source publication timestamps and matched 007 JC/Crown odds are unavailable in these files, so no EV/ROI claim is possible. No candidate can be promoted from this report alone; a new untouched future evaluation is required.
