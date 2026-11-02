# Shadow model — actual performance and five-play audit (2026-11-02)

**Purpose: score the ability to predict NBA win, handicap cover and total over/under, NOT to find institutional price differences, betting EV or ROI.** This is a research scorecard, not a claim of production model uplift.

## A. Historical three-play market-stage research (score verified)

Data: 1,312 distinct independently completed NBA games from 2024–25 with source-defined opening/closing cross-book consensus stages, but WITHOUT bookmaker original quote update timestamps. 604 earliest games for fit, 328 chronologically later games for coefficient selection, 380 further games for retrospective later evaluation (2025-03-08 to 2025-06-22). This period has previously been explored, NOT a fresh untouched prospective holdout.

| Metric | Independent graded / correct | Direction accuracy | Earlier market baseline | Shadow historical Brier | Baseline Brier |
|---|---:|---:|---|---:|---:|
| Moneyline | 267 correct out of 379 non-tie forecasts | 70.45% | Opening odds market (not existing team model) | 0.19471062 | 0.19786754 |
| Spread (at historical OPEN line) | 169 / 288 | 58.68% | An uninformed 50/50, **NOT** bookmaker or production model | 0.24352969 | 0.25000000 |
| Totals (at historical OPEN line) | 197 / 344 | 57.27% | An uninformed 50/50, **NOT** bookmaker or production model | 0.24108672 | 0.25000000 |

Baseline and shadow moneyline non-tie sample denominators differ. Strictly apples-to-apples 374 paired non-tie games: **opening-market correct 264/374 (70.59%) vs shadow correct 263/374 (70.32%)**. The shadow's directional hit rate was **not better**, although Brier was numerically lower. Neither proves model superiority.

Spread and totals baselines always have p=0.5 and thus do NOT issue a directional prediction. There is no valid **original real team model vs new postmarket shadow** paired result for these historical 380 games, and none of those aggregate numbers are 007 Jingcai/ID3 Crown five-market prospective accuracy.

**Open/close stage time ambiguity**: The above model sees spread/total closing movements without independently proved exact capture time before a user's decision. Its historical scores are hypothesis-generating only, not timestamp-certified prospective trading or final model calibration.

## B. Actual 007 Nov 3 2026 future slate — newly generated shadow

Latest PR CI created a new model invocation after real saved source capture for 15 individual NBA fixtures and 75 original target play slots. 8 probability entries changed, **all eight are totals (JC and Crown in four games)**, and only **one directional prediction changed**:

| Home vs away | Market | Original P(Over) | New P(Over) | Direction after |
|---|---|---:|---:|---|
| NY Knicks vs Brooklyn Nets | JC totals | 53.98% | 51.60% | Over, unchanged |
| NY Knicks vs Brooklyn Nets | Crown totals | 53.98% | 51.60% | Over, unchanged |
| San Antonio Spurs vs Utah Jazz | JC totals | 53.35% | 55.72% | Over, unchanged |
| San Antonio Spurs vs Utah Jazz | Crown totals | 49.26% | 51.64% | **Under -> Over** |
| Houston Rockets vs Boston Celtics | JC totals | 64.07% | 63.51% | Over, unchanged |
| Houston Rockets vs Boston Celtics | Crown totals | 68.75% | 68.22% | Over, unchanged |
| Denver Nuggets vs Portland Trail Blazers | JC totals | 50.18% | 52.56% | Over, unchanged |
| Denver Nuggets vs Portland Trail Blazers | Crown totals | 58.32% | 60.63% | Over, unchanged |

No independent official Final outcomes for Nov 3 yet, so real new shadow-vs-baseline match/market **paired n=0, graded n=0, confirmed uplift unavailable**. The two originally unobserved JC moneyline quotes remain absent; do not infer JC odds. Real team model moneyline values still exist separately. Zero historical or newer quote prices are invented.

Research CI: https://github.com/noki1022/mcp-sports-hub/actions/runs/41433509059

## C. Promotion and reporting

The new research model remains **draft PR only** until automatic postreport frozen artifact delivery and later independent official score grading are proven. No actual production fusion, no revised PushPlus forecasts, no claim that historical model has outperformed the existing team's five real direct plays.

Performance panel must always include: **original games / real scored games / five per-market correct/graded and Brier / baseline vs candidate on the exact same line / number of frozen before kickoff / no quote or missing injury exclusions / a truthful result if no game is yet final**. Never substitute the mere count of adjusted probabilities for hits.

## D. Actual accepted 18:00 source -> newly generated postmarket forecasts

On 2026-11-02 19:24 Beijing (UTC 11:24:37), the real GitHub research job independently generated a NEW complete 15 NBA games x 5 direct markets = 75 forecasts, after checking the genuine original 18:00 successful PushPlus marker from run 41425286650. Eight first-side model probabilities changed, precisely one direction flipped, and two direct official Jingcai moneyline offers remained unavailable. No scores were known and no production probability or PushPlus output was modified.

Actual genuine run: https://github.com/noki1022/mcp-sports-hub/actions/runs/41436593663

Upon merger of PR #231, the separate research-only workflow nba-postmarket-shadow-auto.yml is triggered by the SUCCESSFUL original full-board 007 analysis workflow completion on main. It checks actual successful 18:00 report marker and matching source run ID, no stale or posttip quotes, original file hashes, correct teams, all five JC/ID3 thresholds and signed spread. It uploads only the immutable pretip candidate and original model bridge with 90-day artifact retention; no odds fetch, no duplicate PushPlus, no main branch writing.

The separately allowlisted research-only daily 23:25 Beijing workflow nba-shadow-prospective-final-grade.yml checks independent official NBA Final settlements. It downloads ONLY the EARLIEST genuine immutable main-branch pretip shadow artifact for that exact date, validates GitHub run timestamps, original source digests, full game/line identity and individual forecasts. Only then it scores each originally frozen and newly frozen direct JC and Crown ID3 prediction on the exact same game and line. It produces actual correct/graded and Brier per market with zero live fusion. A missed or incomplete final remains ungraded; there is no claim of positive prospective model lift until independently settled future games accumulate.

One isolated postgame research-score-only schedule is explicitly allowlisted in scripts/validate_nba_schedules.py. Existing original live PushPlus, Cloudflare, odds collection and pretip 12:00/18:00/21:30 run times are unchanged. The previously explored historical market-stage results do not establish incremental improvement against current production.

Future numeric model promotion remains blocked pending at least 100 independent completed fixtures on each of the five direct market targets, at least 24 separate Beijing dates, statistically credible same-game paired forecast-score improvement, verified original model inputs and additional truly untouched chronological prospective outcomes. No automatic promotion exists.
