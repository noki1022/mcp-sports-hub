# P0 NBA replacement-aware injury shadow versus ACTUAL production rolling fitter

CI: https://github.com/noki1022/mcp-sports-hub/actions/runs/41185301124

## What actually ran

The unchanged original production algorithm `nba_independent_predictions._fit_production_model`, with rolling Elo/form/H2H and per-date calibration. Source for injury: archived NBA reports (SportsDataverse files 2023–26). Source for players: genuine season-specific regular-season player/game logs (Hugging Face Sangameshsb nba-game-logs; NBA ID and player ID). All injury inputs derive from earlier report-version date and **previous calendar-day** player minutes/points. Replacement-depth proxy uses past-only same-franchise bench appearances, never a target-game roster. Exact original home/away and final margin was independently matched; 16 conflicting matches quarantined.

Sample: 1763 matched historical rolling production fixtures; candidate margin residual fit 378 games in 2023–24, disjoint recalibration 673 in 2024–25, 712 tested 2025–26. 2025–26 outcomes had already been examined by earlier project research and CANNOT be claimed untouched.

| Metric | Original rolling production | Recalibration only | Injury + replacement shadow |
|---|---:|---:|---:|
| Home win Brier | 0.1982185 | 0.2014958 | **0.1936255** |
| Home win LogLoss | 0.7030958 | 0.6161454 | **0.5690998** |
| ECE10 | 0.0732719 | 0.0883201 | **0.0361936** |
| Final margin MAE | 11.08914 | 11.08914 | **10.86828** |

Paired cluster bootstrap with 161 NBA game dates and 500 samples:

- Enhanced minus **recalibration-only** Brier: **−0.0078703**, 95% CI **[−0.0122747, −0.0031957]**.
- Enhanced minus **original production** Brier: **−0.0045930**, 95% CI **[−0.0094206, +0.0007430]**; **includes zero**.
- Enhanced minus original production margin MAE: **−0.2208609 points**, 95% CI **[−0.3944390, −0.0422716]**.

## Strict production decision

Research signal is positive for independent moneyline and margin prediction, but **NOT ACCEPTED for production**.

1. Original HTTP issuance of each historical report version was not verified, nor was per-report availability compared with independently proven actual UTC game tipoff. File clock is a nominal report version clock only.
2. The 2025–26 year was previously used during development, so this is not a fresh unobserved post-freeze holdout. Multiple study iterations can inflate apparent performance.
3. Learned weights describe team-level injury and bench **proxy signals**, not separately validated actual per-player on/off contribution and lineup replacement behavior.
4. No genuine timestamped 007 Jingcai and Crown spread/total prices were paired. Fixed thresholds are not bookmaker bets.
5. The statistically paired interval of **injury vs original production** Brier still includes zero.

No `config/nba_player_impact_validated.json` should be created from this study and no live PushPlus probabilities are changed. Running code saves read-only research evidence only. Next mandatory P0 stage: seal frozen production+replacement candidate forecasts before real 2026–27 games; verify official NBA source PDF and per-game early capture, then independent real postgame scoring when enough true new games exist.

