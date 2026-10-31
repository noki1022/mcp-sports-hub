# P0 same-production NBA injury shadow: 2026-10-31 evidence

GitHub Actions: https://github.com/noki1022/mcp-sports-hub/actions/runs/41182959337

This run uses the actual production fitting algorithm `nba_independent_predictions._fit_production_model` as a rolling historical baseline. Candidate correction is a two-feature linear residual adjustment trained **only before** the later-season test, with separate 2024-25 calibration and no artificial five-market quotes. Do not conflate the candidate with the already-deployed `nba_injury_probability.adjust` player-impact catalog.

| Split | Games |
|---|---:|
| 2024–25 residual fit | 357 |
| 2024–25 residual calibration | 300 |
| 2025–26 same-game test | 764 |

| Metric | Production rolling baseline | Injury shadow |
|---|---:|---:|
| Home-win Brier | 0.198650 | 0.195127 |
| Home-win LogLoss | 0.695332 | 0.639490 |
| ECE 10 bins | 0.069215 | 0.048495 |
| Margin MAE | 10.97337 | 10.76845 |
| Margin RMSE | 14.22364 | 13.93308 |

Paired day-cluster bootstrap: home-win ΔBrier (enhanced − baseline) −0.003523, 95% CI [−0.010380, +0.003184] **includes zero**. Margin ΔMAE −0.204921, 95% CI [−0.379481, −0.029375]. These intervals do not correct for multiple iterations on previously inspected 2025–26 data. This is a historical replay of the *same production fitting architecture*, not proof of production readiness.

## Deployment decision
**Fail closed: no live coefficients, no `config/nba_player_impact_validated.json`, no production probability change.** The historical source holds archived report version clocks, not independently verified original publication moments; 2025–26 was previously inspected for research; candidate parameters are aggregate proxy residual effects rather than identified player-specific impacts; 007 real pretip lottery/crown lines and any five-market EV are not established. Total is unchanged in this candidate and remains explicitly rejected for injury-based adjustment.

Additional gates required before production: independently certified original report availability and UTC tipoff, a newly sealed out-of-time evaluation on the *same frozen model*, player-level replacement/availability calibration, and historical genuine 007 market line verification. Do not self-certify `WALK_FORWARD_PASS` from this artifact.
