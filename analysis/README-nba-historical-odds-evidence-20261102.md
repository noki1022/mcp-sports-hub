# NBA Historical Odds Evidence Cohorts — 2026-11-02 (Beijing time)

## Research deliverables, verified by actual GitHub Actions

| Cohort | Independent games | Quote rows | Labeled games | Gate |
| --- | ---: | ---: | ---: | --- |
| NBA historical game-date market benchmark 2007–2026 | 23,574 | 23,574 game-level | 23,574 | Research training/benchmark with unknown original quote publication time |
| 2024–25 **opening + closing** market, cross-scored against independent history | 1,312 | 1,312 two-stage games | 1,312 | Historical OPEN/CLOSE event stage but NO independent quote update time |
| Multi-provider **actually captured pre-tip** 007 + other sports books | 36 | 1,375 quote rows | 20 | Per-quote time auditable; 007 price direction still unverified |
| └─ 007 Jingcai + 007 company ID3 (Crown) | 21 | 970 | 17 | Source captured time and market line, raw price slot orientation not certified |
| └─ The Odds API v4 stored snapshots | 15 | 405 | 3 | Snapshot UTC + bookmaker market last_update UTC + verified price side |

**Do not add 1,312 to 23,574:** the matched open-close games are already inside the historical benchmark. Do not treat 1,375 quote rows as independent games either.

### Source-specific evidence

**Game-date benchmark:** 23,609 rows downloaded; rejected 35 (1 inconsistent moneyline winner, 7 inconsistent score/point margins, 11 anomalous moneyline pairs, 16 missing/invalid totals). The 23,574 accepted games belong to 19 NBA seasons with explicit recorded game date, teams, winner, spread raw value, totals, American moneylines and score. Unknown bookmaker, unknown exact quote publication/offer time, and unknown spread-side sign; NO 007 provenance claimed. Historical standalone model training and market baseline scoring is possible at **date granularity**, but a 30-minute pre-tip backtest is not.

**Open/close dataset:** upstream CC-BY-4.0 claimed; 1,314 rows, 1,312 accepted after cross-checking home, away, date and final score against independent benchmark. Reject 2 score disagreements. The source distinguishes opening and closing stages for win probability, signed-home spread and total with actual UTC tip. Original bookmaker change timestamps are still missing. At 1,312 independently matched games: **home moneyline Brier** 0.205747557 at opening and 0.200951523 at close. This is evidence of market information accumulation, NOT our model's uplift. 1,019 spread-line movements and 1,191 total-line movements. Do not count any 2024–25 same-game benchmark row twice.

**True capture UTC dataset:** 007 stored archive contains 970 actual odds observations over 21 fixtures; 405 snapshot/bookmaker/market observations from The Odds API over 15 more fixtures. All 1,375 passed timestamp-before-tipoff checks, plus bookmaker last-update freshness where provided. Distinct overall fixtures 36; score-matched fixtures 20. Only **81** scored quote rows (3 distinct games × 9 books × 3 markets) from The Odds API have independently validated price-side orientation and bookmaker last-update. 007 keeps user-confirmed company ID3 as Crown, but raw 007 odds slot direction is not independently proven and its price-based probabilities remain blocked. Only 46 market rows over 10 games at the strict 30m source-fetch freshness cohort (<=120 minutes old), with 41 scored market rows over 9 games.

### Chronological independent-market model experiment

- Train: **20,444** games (through season 2022–23; latest 2023-06-12).
- Validation: **1,255** games (2023–24).
- Untouched evaluation: **1,875** games (2024–25 and partial 2025–26).
- Baseline no-vig home moneyline **holdout Brier 0.205217999**, directional accuracy **67.95%**.
- Adding prior-date team form and fitting regularized logistic calibration failed the validation-only selection threshold; the baseline was retained. Totals form model also failed validation against a 50/50 baseline. These numbers are measured research scores and **not proof of NBA five-market profit or sportsbook returns**.
- No model coefficients, production scheduling, notifications, or betting recommendations were changed.

### Code and reproducible outputs

- `analysis/nba_historical_market_benchmark.py` — pinned SHA, strict 23,574 normalized games and quality rejection report.
- `analysis/nba_historical_market_model_oos.py` — time-ordered validation/holdout on 23,574 games.
- `analysis/nba_hf_open_close_crosscheck.py` — 1,312 open/close market vs independent final score with UTC tip.
- `analysis/nba_multi_provider_odds_asof_archive.py` — The Odds API snapshot/book price timestamps plus 007 true saved captures with distinct game/bookmaker identity.
- `analysis/nba_007_historical_odds_backfill.py` — 007 actual pre-tip observations and frozen cutoff tables, with no post-fetched historical date manufacturing.

CI:

- [Game-date market normalization](https://github.com/noki1022/mcp-sports-hub/actions/runs/41383833281)
- [Historically split model training](https://github.com/noki1022/mcp-sports-hub/actions/runs/41383833177)
- [1,312 matched opening/closing odds](https://github.com/noki1022/mcp-sports-hub/actions/runs/41383833237)
- [1,375 genuine multi-provider pre-tip quote rows](https://github.com/noki1022/mcp-sports-hub/actions/runs/41383833381)
- [970 genuine 007 quote snapshots and true movement](https://github.com/noki1022/mcp-sports-hub/actions/runs/41383833229)

Datasets are uploaded as **GitHub Actions JSONL artifacts** for each CI run (retention: 60 days), not committed as multi-megabyte Git histories. Rebuild by re-running the relevant research workflows; the version-pinned date-level upstream SHA ensures silent changes fail closed. Upstream raw source rights and quote publication time remain independently unverifiable for the 23,574-game public candidate; retain its status as an internal retrospective research reference.

**Promotion rule:** Only a genuine frozen, as-of-each-decision sample with complete price signs, odds, time, verified result, injury-report release chronology, and untouched holdout can be used to claim five-market production uplift. Do not poison existing 007 model data or GitHub/Cloudflare automation with missing timing evidence.
