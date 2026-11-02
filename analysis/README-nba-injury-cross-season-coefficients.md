# Actual NBA injury-role minutes coefficient comparison, cross-season

## Purpose
The existing original production injury shadow is blocked on zero authentic frozen *paired* injury-adjusted home-win probabilities. PRs #217–#221 have already improved evidence identity coverage. This independent **historical research study** reuses the existing 2022–2026 injury and player-game paired builder to quantify if earlier same-team role minutes and status+previous points add **incremental** information beyond prior team form.

The result is *not* the production candidate: older official injury report `report_datetime` is only an archived claimed version timestamp, not independently authenticated HTTP availability at tip. The target future production capture feature schema and original model probability conditioning differ. No historical genuine 007/ID3 bookmaker quotes or verified injury player causal impact.

## Design
- Reuse the original upstream source loader and reciprocal NBA game score reconstruction, paired predate team form, injury status and earlier same-team player minutes; do not infer zero impact when player history is missing.
- Fixed candidate feature sets: (A) two prior team form features; (B) A + home/away injury previous-minute gap; (C) B + status-weighted previous scoring and historical bench replacement-depth proxy.
- Early seasons through 2023–24 for ridge training, 2024–25 for challenger selection, 2025–26 for **previously explored** later evaluation.
- Candidate selected on prior validation moneyline Brier improvement of at least 0.001 and no greater than +0.20 home margin MAE regression. Otherwise retain team form only.
- Report independent home-win Brier/log loss/accuracy, margin MAE/RMSE and calendar-game-date bootstrap paired difference. This evaluation season is not a new untouched holdout, and a significant-looking result still cannot release coefficients to the user or production.
- If original data source doesn't yield enough disjoint game pairs, report precise segment counts and fail closed rather than silently reuse current-season labels.

## Run
```sh
python3 analysis/nba_injury_cross_season_effect_coefficients.py --selftest
python3 analysis/nba_injury_cross_season_effect_coefficients.py --out /tmp/nba-historical-injury-cross-season.json
```

CI on PR/manual only, retains source SHA provenance and machine-readable analysis for 60 days. **No** write to active injury adapter, original scheduled 21:30/06:30, 007/Crown/JC odds feeds, Cloudflare, PushPlus, prospective archived shadow probability or `config/nba_player_impact_validated.json`.

## Promotion requirements
Independent true pretip freeze and source-ready player IDs for both teams, original report clock before tip, separately trained/cross-season prior score prediction, confidence intervals on genuinely new prospective paired original-versus-injury probability Brier and proper scores, and market-line-specific five-play results. Research-only coefficients here can only identify study directions, not approved player value.

## Critical ablation: 24 shuffled-injury training controls

Even when the real candidate improves on previously examined later games, more
regression dimensions can accidentally exploit unrelated data structure. The
research now repeats candidate fitting 24 times, preserving historical team
form and final outcomes but independently shuffling the injury proxy columns
**within the prior training partition only**. The original later evaluation
is unchanged. Compare actual candidate Brier with the distribution of sham
model Brier (5th/95th percentiles). This is an additional falsification
check, not prospective confirmation, and historical report publication times
remain unverified. No variant is selected based on those later scores.
