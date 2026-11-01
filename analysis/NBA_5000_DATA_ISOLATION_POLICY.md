# NBA 5,000-game research: isolation and acceptance policy

This document applies only to branch `research/nba-5000-game-history-20261031`. No production-model modification is authorized by an audit count.

## Dataset partitions (immutable by purpose)

- **Raw corpus**: source games and metadata. Never describe its size as training size.
- **Feature-eligible**: independently validated fixtures with point-in-time historical features. Exclude games lacking enough prior form; report excluded counts.
- **Fit**: seasons 2018-19 through 2023-24, chronological and deduplicated. This is the candidate expanded training window, not an assertion that 5,000 fit rows exist.
- **Tune**: 2024-25 through January 31, 2025, for predefined hyperparameter selection only.
- **Embargo**: February 1-7, 2025, excluded from tuning/calibration.
- **Calibration**: February 8, 2025 through the end of 2024-25; calibrate using predictions from frozen fit parameters.
- **Untouched test**: 2025-26 regular season; do not use to choose feature sets, hyperparameters, source inclusion rules, model thresholds, or revisions.
- **2026-27**: excluded from this study; future live inference may use only verified results available before each forecast.

If the **fit partition itself** has fewer than 5,000 feature-eligible fixtures, report that shortfall. Do not borrow tune, calibration or test fixtures to reach the target.

## Hard failure checks

1. Unique canonical fixture ID; consistent home/away, date, season, final points and reciprocal team-game records. No duplicates, postponed/unplayed rows, preseason, playoffs, All-Star or simulated fixtures.
2. Team identifiers mapped consistently across seasons. Validate source season labels, dates, score plausibility, missing values and provenance. Quarantine invalid rows; never silently impute final results.
3. Every feature must be reproducible from information available strictly before the target game's tipoff. Date-only game logs require at least prior-day cutoff; same-day completed games cannot be used. Publication-lag sensitivity is a separate shadow experiment.
4. Compute rolling statistics inside chronological folds; never use full-season final averages, season-end standings, future injury status, future opponent results or full-dataset scalers.
5. Fit all preprocessing, scaling, selection and calibration on the authorized earlier partitions only. Group duplicate provider rows by canonical game and prevent shared game identities across splits.
6. Betting-market prices, bookmaker lines, 007/Crown odds, closing lines and post-game labels are forbidden as model input features. Market comparisons happen downstream only.
7. Reject overlapping fixture IDs, temporal overlap, failed source hashes, unverified provenance, implausible values, or missing split-count evidence. Preserve a machine-readable exclusion reason per rejected row.
8. Freeze baseline, test protocol, metric definitions and candidate before touching the untouched test. Compare identical test games; include Brier, log loss, calibration, margin/total MAE and uncertainty. A single favorable number is insufficient.

## Repository hygiene

- Keep source CSV downloads and intermediate derived tables out of commits. Prefer ephemeral CI downloads, with source URL, timestamp, content SHA-256, parser version, row counts and exclusion counts captured in run artifacts.
- Commit only small scripts, tests, source manifests, documentation and compact aggregate reports. Keep raw data and large artifacts outside Git; do not commit secrets, credentials or PushPlus tokens.
- Use the research branch and draft PR; no changes to main, production predictions, scheduled pushes, live betting recommendations or existing historical snapshots.
- Record an explicit FAIL/PASS gate. A count of >=5,000 in the raw corpus is **not** acceptance. Acceptance requires >=5,000 **fit** rows plus all integrity gates and an independent chronological evaluation. A non-improving candidate remains shadow-only.
- On failure, quarantine the data and stop promotion; do not silently change test years or redefine the test to obtain a favorable result.
