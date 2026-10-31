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

## P0 stricter comparison: recalibration-only placebo (2026-10-31)

Updated CI: https://github.com/noki1022/mcp-sports-hub/actions/runs/41183282835

The same 764 games receive (A) original rolling production probability, (B) **calibration-only control** with the exact same 300 earlier calibration games and identical isotonic procedure, and (C) that calibration plus injury proxy.

| Home-win metric | A production | B recalibration only | C injury shadow |
|---|---:|---:|---:|
| Brier | 0.198650 | 0.199787 | 0.195127 |
| LogLoss | 0.695332 | 0.654903 | 0.639490 |
| ECE10 | 0.069215 | 0.075658 | 0.048495 |

Paired C-B injury-specific Brier change: **−0.004660**, calendar-day bootstrap 95% CI **[−0.009746,+0.000515]**, **includes zero**. Therefore the incremental *probability* value of the injury input is NOT statistically secured in this previously explored sample. Compared with A, C improves margin MAE by −0.2049 with CI [−0.3795,−0.0294].

Fixed handicap thresholds −5.5 / −0.5 / +5.5 have Brier improvements in this research replay, but **are not authentic time-stamped 007 market prices**, and no investment return can be claimed.

The baseline production rolling training and calibration cutoff checks are now explicit; historical archive clocks and an untouched prospective season are still missing. The production switch and player-impact catalog stay **disabled**. This study uses a frozen candidate design only, is not causal player effect attribution and has already inspected this season.
