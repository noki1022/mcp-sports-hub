# SBR archive ingestion: research-only, no repository bloat

Source index: https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba/nbaoddsarchives.htm

## Current evidence
- SBR is already in `data/odds_sources.yml` as `pending_license_and_raw_fetch_audit`. The live index returned 404 to the web reader on 2026-10-29. **No complete seasons have been downloaded.**
- A public third-party [2019-20 SBR-format CSV](https://github.com/garfjohnson/Nba-Sports-Betting-Model/blob/master/nba%20odds%202019-20.csv) displays the `Date,Rot,VH,Team,Final,Open,Close,ML` fields. Upstream rights and accuracy remain unverified.
- `Open` and `Close` each mix **a total in one team row** and **an unsigned favorite spread magnitude in the other**. The parser reconstructs home-signed handicap and totals separately. `ML` is American closing moneyline; it does **not** provide a precise timestamp, side-specific bid/ask availability, or verified intra-game updates.

## Safe use

```bash
python3 analysis/sbr_archive_import.py --self-test
python3 analysis/sbr_archive_import.py --input /tmp/sbr/2019-20.csv --season 2019-20 --out /tmp/sbr/2019-20-audit.json
```

XLSX requires `openpyxl`. Input is **locally obtained with appropriate rights**; this importer makes no network calls. Invalid teams, duplicate games, mixed visitor/home order, missing score, malformed lines, ambiguous spread/total, and inconsistent closing moneyline/spread direction are excluded. Output is marked `CLOSING_MARKET_BENCHMARK_ONLY` / `training_eligible: false`. Do not pass it to the current `nba_odds_feature_backtest.py` (that expects timestamped The Odds API snapshots).

Strict research policy:
1. Download only to `/tmp` or a GitHub Actions temporary workspace. Never commit source archives or rejected rows. Delete raw files when audit completes; persist only small manifests and summary diagnostics after checking upstream rights.
2. Validate exact source URL, SHA256, rights, season, unique (date, home, away), pre-game field semantics, and completed score. Keep rejection counts but not invalid records.
3. For **score/form features**, enforce `feature_source_date < target_date`, batch same-day features, embargo, and train/validation/calibration/holdout partitions.
4. For **odds-assisted predictive features**, require verifiable pre-tip **as-of timestamps**, matchable bookmaker/market side and price. Opening/closing labels alone do not prove precise availability. Do not use a game's closing odds if the prediction scenario is earlier than that close.
5. A research dataset may be suitable for **closing market benchmark** without being suitable for pregame **model training**. Do not state EV, ROI, or accuracy uplift without an untouched chronological holdout.
6. Existing historical game results from BoxScore Lab are already used by `nba_chronological_backtest.py`; avoid adding duplicate seasons to the Git repository.

## Additional candidates investigated (not automatically ingested)
- [nba-line-sheet](https://github.com/aaryanshah607/nba-line-sheet), ~23,586 game-level odds/results: benchmark only until quote timestamps and field provenance confirmed; already registered.
- [BoxScore Lab](https://boxscorelab.com/downloads/): 2022-23 onward, used by current historical model; licensed and score checked at source; re-downloading here wastes space.
- [llimllib/nba_data](https://github.com/llimllib/nba_data): historical game logs, team efficiency, player logs, game-level Four Factors. Candidate for independent validation and additional **historical pregame rolling features**, subject to source rights and same-day anti-leak audit.
- [basketball-data-index](https://github.com/nickth3man/basketball-data-index): game results plus apparent detailed NBA odds timestamps; audit underlying origins/licensing and row-level timestamps before any training import.
- [DunkAPI](https://dunkapi.com/data): historical NBA odds since 2013-14, some opening/closing series. API access, terms, price and precise source timestamps must be inspected before ingestion.
- [Kaggle NBA betting datasets](https://www.kaggle.com/datasets): search candidate archives 2007-2024; check data card license, duplicates, exact source and publication timing first.
