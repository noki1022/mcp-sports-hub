# P0 2022–24 injury and teammate replacement research (executed 2026-10-31)

CI evidence: https://github.com/noki1022/mcp-sports-hub/actions/runs/41184770963

## Source verified

- NBA official injury archived versions from SportsDataverse: 2023 season 183,846 designation/version rows and 2024 season 201,552 rows, total **385,398**. Records carry NBA game_id and person_id. Timestamp is an *archived report-version clock*, not proven HTTP publication time.
- Player-game logs from Sangameshsb/nba-game-logs (CC0 packaging, upstream NBA data terms separate): 2022–23 **25,687** player-game appearances, 2023–24 **26,095**. 1,230 unique games each, 70 and 77 players with multi-team history observed.
- Exact SHA256 source hashes, source URLs, coverage and exclusions are in the GitHub Actions artifacts. No original files redistributed.
- Training features use strictly earlier game-date player minutes/points, and the player ID must match the **same team** on that earlier date; missing official designation remains unknown rather than healthy.

## Historical cross-season model results

| Metric | Base only: trailing team margin | Plus pregame injury + replacement-aware proxies |
|---|---:|---:|
| 2023–24 test games | 654 | 654 |
| Home moneyline Brier | 0.231823 | **0.225051** |
| Home moneyline LogLoss | 0.656040 | **0.641689** |
| Final margin MAE | 11.86049 | **11.58286** |

Historical 2022–23 fit = 443 games, subsequent 2022–23 calibration = 251, 2023–24 test = 654. Paired calendar-day 500-resample bootstrap on 149 dates: injury minus baseline Brier −0.006772, 95% CI [−0.010386, −0.003038], margin MAE −0.277638, 95% CI [−0.412949, −0.139447].

### What was actually modeled

Ridge regression compares equal chronology with and without status-weighted *prior-only* rotation injury features. The enhanced model adds relative unavailable minutes, prior scoring and a team-specific bench-depth discount from at least three earlier appearances. It is **not a RAPM, causal replacement model or an individually validated player catalog**; the strength and status weights are research proxies. Test season was selected for historical research, not reserved as a future untouched prospective test.

### Production decision

**Do not create config/nba_player_impact_validated.json or modify PushPlus model percentages.** The model is an older-season research baseline, not same frozen 2026 production model. Original HTTP release timestamps vs official UTC tipoffs still need individual independent verification. Genuine timestamped 007 Jingcai/Crown market lines are not present; no five-market EV/backtest claim. The true 2026-27 prospective sealed-shadow evaluation remains required. Totals adjustment stays disabled due prior holdout harm.
