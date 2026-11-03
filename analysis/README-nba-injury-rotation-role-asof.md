# NBA injury shadow: prior-role depth from real roster + same-team minutes

## Purpose and boundary

This is a **separate research-side** extension of the existing injury pipeline, not
another official five-market predictor and not a redefinition of a star player's
point value. The primary source is the genuinely observed NBA injury PDF, plus
ESPN rosters captured during the same research run and prior dated player logs
already used by `analysis/nba_injury_live_roster_feature_freeze.py`.

The official 21:30 locked original forecast, independent 007 market shadow,
Jingcai/Crown ID3 odds and PushPlus remain unchanged. No injury-driven probability
or spread/total adjustment is released.

## Research-only features frozen before tip

- Check official PDF ET report date against each fixture ET tip date and require
  actual before-tip source and roster capture timestamps.
- Link the official listed athlete to exactly one *current* roster athlete ID
  and a distinct verified historical NBA player-log ID. Neither numeric ID
  namespace is guessed or conflated.
- Rank only athletes with at least 3 previous same-team player-game appearances,
  their latest actual same-team appearance dated **before** the entire capture
  ET calendar day, and last appearance within 45 days of the fixture.
- An observable `verified_core_rotation_role` means **top 3 prior average
  minutes within at least 8 verified current-roster player-role records and at
  least 27 previous same-team minutes per game**. This is a deterministic
  descriptive threshold, **not a validated "star" classification** or actual
  active/starting prediction.
- A potential depth record means rank >=6 and at least 10 previous same-team
  minutes per game. A player not in the official injury PDF is
  `NOT_LISTED_NOT_CONFIRMED_AVAILABLE`: this does **not** prove they will
  play, start or replace anybody.
- Every injured player missing stable identity/current-team role remains an
  explicit unknown. Older-team trade minutes, stale or future game logs,
  missing official reports and missing roster sources cannot become zero
  impact or fictitious player minutes.
- One fixture's returned `research_rotation_role_asof` is in the existing
  pretip `prospective_official_injury_roster_minutes.jsonl` artifact with
  source hash/clock proof. Numerical injury and margin adjustments stay null.

## Automated ongoing research capture (separate from live chain)

This research workflow runs **once daily at 18:10 UTC (02:10 Beijing time)**
in a standalone GitHub Actions job, **after** the 21:30 official report.
It does not trigger original PushPlus, write `main` or feed a late injury
snapshot back into the original 21:30 forecast. GitHub Cron may be delayed;
the collector rejects an expired or post-tip source rather than backdate it.

After strict CI and SHA validation, a successful scheduled run appends a
snapshot under the *separate* branch
`audit/nba-injury-role-evidence` in
`reports/injury-role-asof/<NBA Eastern date>/<GitHub-run-id>/`:

- `audit.json`: source URLs, source SHA-256, UTC capture clocks, row counts,
  matched/unknown identity counts, verification flags, future fixtures.
- `roles.jsonl.gz`: lossless gzip of the frozen factual per-game injury and
  earlier-minute role evidence. Original JSONL SHA-256 is in `audit.json`.

The research workflow also keeps a 60-day Actions artifact. Unlike the
artifact, the append-only audit branch is intended for long-term reproducible
retention, subject to GitHub storage monitoring and future independent R2
backup. **No upstream raw ESPN/NBA PDF or player-log parquet bytes are added
to Git**; the feature snapshots are factual derived records and source
checksums only.

## Verification and limitations

`python3 analysis/nba_injury_rotation_role_asof.py` provides deterministic
tests for top-ranked role, missingness, stale 45-day roles, future roster
capture, mismatched IDs and missing official team report. The scheduled
research workflow also runs all prior player-ID, official report and snapshot
integrity checks; it may fail closed if a provider is unavailable and must
not be described as a successful snapshot for that day.

**No prospective uplift claimed.** A future numerical injury-adjusted
five-market candidate will need verified same-team role, replacement
responsibilities, genuinely pretip candidate coefficients frozen separately,
and independent same-game same-line scoring against the original and
independent market baseline. Current empirical rotation ranks are NOT
quantified points of injury impact.
