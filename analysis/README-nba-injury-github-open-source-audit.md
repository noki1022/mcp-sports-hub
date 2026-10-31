# P0 NBA injury GitHub open-source skill evaluation (2026-10-31)

Purpose: accelerate **production acceptance** of NBA injury-adjusted moneyline and margin, not merely add alerts. The current frozen research model/PR is NOT production-approved.

## Verified shortlist

| Repo | Capability actually examined | License / dependency | Adoption |
|---|---|---|---|
| [mxufc29/nbainjuries](https://github.com/mxufc29/nbainjuries) | Timestamp-addressable official NBA PDF archive retrieval, 2021–22 onward (claimed), sync and async report retrieval, availability probing | MIT; Java/tabula-py and official PDF availability can fail | **P0 high**: sample historical earlier seasons to enrich FIT period. Verify real HTTP access, download permission, report identity, actual tipoff, original availability; do not assume guessed publication clocks |
| [harjot-jaswal-dev/nba-injury-impact](https://github.com/harjot-jaswal-dev/nba-injury-impact) | Explicit baseline + teammate replacement/ripple delta model; 17 engineered role/absence features; historical player-game evaluation | No repository-level license surfaced by GitHub metadata; models reflect different task | **P0 design reference**, no direct copying or unvalidated coefficient imports. Model replacement minutes and teammate usage from past-only logs |
| [cire694/courtcast](https://github.com/cire694/courtcast) | Sequential Bayesian component RAPM, lineup interactions, injury hazard, rolling-origin backtest | No repo-level license surfaced; Slurm/GPU intensive, some synthetic roster/schedule fallback | **P1 research architecture**, prohibit synthetic roster fallback and avoid direct deployment |
| [buildkit-ai/injury-report-monitor](https://github.com/buildkit-ai/injury-report-monitor) | Actual Claude Code Skill at `skills/injury-report-monitor/SKILL.md`, multi-source status changes and alerting | MIT; game schedule API key; hardcoded 25/50/75% doubtful/questionable/probable proportions not independently calibrated | **Monitoring backup only**. Existing official PDF source remains primary; no probability import |
| [galcesana/nba-predict](https://github.com/galcesana/nba-predict) | Injury feature engineering and ablation test files: performance/context test loss 0.618834 vs +injury 0.622510 | No repo-level license surfaced; reported injury proxy experiment had 0% real injury report coverage | **P0 evaluation lesson**: mandatory same-fixture comparison + calibration placebo, missing=unknown not healthy |
| [mkeenan195/nba-injury-report](https://github.com/mkeenan195/nba-injury-report) | Python JSON/CSV official report parser and tests, source history since 2021–22 | AGPL-3.0-or-later, pydantic/httpx/PyMuPDF | Independent parser benchmark only; legal review before code reuse |

## Source code findings

- Explicit `SKILL.md` in buildkit-ai contains fixed status-percentage examples; these are NOT qualified training-derived NBA participation probabilities.
- `nbainjuries` has `get_reportdata(timestamp)`, `check_reportvalid(timestamp)`, plus async batch mode. This is the strongest avenue for recovering 2022–24 historical snapshot **availability**, subject to real network checks.
- `harjot...` models teammate redistribution (minutes/usage) rather than incorrectly treating every absent starter as un-replaced lost team points; use as architecture inspiration.
- `courtcast` is 3GB/Slurm-oriented and explicitly documents fallback roster/synthetic schedule. Our model must fail closed rather than adopt synthetic substitutions.
- `galcesana...` publicly records **worse** logloss with injury proxy: 0.618833884 vs 0.622509745 and 0% true coverage in the corresponding study; never conflate feature inclusion with validation.

## Immediate P0 acceptance implementation order

1. **Backfill** a small, authorized, timestamp-addressed official 2022–24 injury sample with `nbainjuries` API/reference, independent of existing archives. Audit coverage, matchups and report time versus actual tipoff. Never treat inaccessible archives as missing=healthy.
2. **Replacement-aware design**: stable NBA player IDs, team-at-date and rolling prior minutes; learn role redistribution and calibrated game-margin delta only from earlier FIT games. Keep total-points injury adjustment DISABLED since it harmed holdout in PR135.
3. **Prevent calibration placebo**: replay identical frozen production model baseline and calibrated-only control. Preserve exact matchups, line perspectives, 007 institutions separately. Register and seal each pretip shadow output before final score.
4. **True prospective scoring**: >300 independent post-freeze finalized games, paired Brier and LogLoss improvement, confidence interval high <0, per-market integrity. Historical 2025–26 data already inspected, so it cannot be a new untouched test.
5. No production catalog `config/nba_player_impact_validated.json` until independently approved. Never manufacture `WALK_FORWARD_PASS` from repo marketing or research heuristics.

License info and documentation recorded for provenance; no external code imported or copied. All GitHub claims reflect repository files observed on 2026-10-31; external model metrics are claims/benchmarks not our validation.
