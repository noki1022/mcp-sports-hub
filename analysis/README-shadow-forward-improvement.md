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

## Results from the completed 4-window run

Verified paired game history: 3,685 games (5 invalid/unpaired records excluded). Evaluation covers 1,275 fixtures across four disjoint windows; previously viewed 2025-26 and 2026-27 records were not accessed.

| Regression target | Existing features MAE | Fatigue + weighted-H2H MAE | Existing RMSE | Candidate RMSE |
|---|---:|---:|---:|---:|
| Margin | 11.258 | 11.207 | 14.320 | 14.276 |
| Total | 15.102 | 15.121 | 19.061 | 19.085 |

The margin improvement is small (MAE -0.051; RMSE -0.043). Total points slightly worsen (MAE +0.018; RMSE +0.024).

Across all fixed spread thresholds, candidate features reduce mean Gaussian Brier by 0.00064 and mean LogLoss by 0.00116, while mean ECE worsens by 0.00048. Across all fixed total thresholds, candidate features worsen mean Gaussian Brier by 0.00035 and LogLoss by 0.00089, while ECE improves by 0.00299. This is a mixed, market-specific effect, not a general model upgrade.

For the empirical KDE residual distribution, pooled average Brier and LogLoss are slightly worse than Gaussian for both margin (Brier +0.00022, LogLoss +0.00096) and total (Brier +0.00006, LogLoss +0.00051). Better ECE on some margin bins does not offset the proper-score deterioration. KDE is therefore rejected as a general replacement.

Pooled paired calendar-day bootstrap on three pre-registered lines:
- Fatigue/H2H features vs baseline Gaussian: margin -5.5 Brier delta -0.00065 (95% CI -0.00168 to +0.00040); margin +5.5 -0.00049 (CI -0.00173 to +0.00061); total 225.5 +0.00009 (CI -0.00088 to +0.00104). All intervals cross zero.
- KDE vs Gaussian with candidate features: margin -5.5 -0.00030 (CI -0.00102 to +0.00031); margin +5.5 +0.00080 (CI +0.00027 to +0.00127, significantly worse); total 225.5 -0.00044 (CI -0.00124 to +0.00041).

## Research decision

**Do not promote either change.** Retain the current production feature and Gaussian probability path. Keep fatigue/weighted-H2H as a weak margin-only research candidate; do not add it to total-points forecasts. Reject KDE as a blanket residual-distribution replacement. A later candidate-specific promotion would need a new untouched future evaluation and the real, timestamp-matched 007 market lines before any betting-value claims.
