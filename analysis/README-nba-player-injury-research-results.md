# NBA player injury probability P0 — actual chronological paired research (2026-10-31)

## Verified execution
- GitHub Actions: https://github.com/noki1022/mcp-sports-hub/actions/runs/41182263492
- Source records: **27,999** actual player-game rows, **107,337** official-injury-report-derived designation rows, **3,011** attendance labels (separate preliminary study).
- Unique scored, matched fixtures: **775**; feature-eligible fixed study: train **205**, embargo **57**, out-of-time research test **110**.
- Exclusions: **353** games missing the selected both-team published snapshot; **28** without three prior completed team games; **1,083** injury name occurrences lacked 3 prior matching player appearances. Counts are not additive games.

## Identical holdout, fixed ridge, only historical features

| Target | Baseline MAE | With status×prior player minutes MAE | Δ (enhanced minus baseline) |
|---|---:|---:|---:|
| Final margin | 11.617 | 10.692 | -0.925 |
| Total points | 13.528 | 13.877 | **+0.349 (worse)** |

Calibration uses a **separate 57-game embargo-era calibration set**, not the 110-game test. The additional fixed-threshold probability scores are:

| Research target | Baseline Brier | Injury-proxy Brier | Change |
|---|---:|---:|---:|
| Home win | 0.227349 | 0.199892 | -0.027457 |
| Total >225.5 (not bookmaker line) | 0.258011 | 0.262397 | +0.004386 (worse) |

Home-win LogLoss improved from 0.645690 to 0.581156; fixed-total LogLoss worsened from 0.709431 to 0.719324.

This is a **research-only within-2024-25 chronological comparison**, *not* an untouched independent production-certified test. No test-season roster-availability impact estimates, five-market betting odds, moneyline recalibration, confidence intervals or calibrated player effects were proven. Proxy: prior minutes times a frozen status availability weight. NOT a causal player value measure.

## Reasons production remains blocked
1. Archived filenames give **nominal** ET snapshot slots; original official release timestamps are not independently proven for every report.
2. Team/game/roster reconciliation is incomplete, particularly the 1,083 unmatched or insufficient-history player injury-name occurrences.
3. Most recent held-out NBA base-model season is **2025-26**, for which this source has no complete paired official historical snapshot archive; the 2024-25 outcomes were already explored when developing this study.
4. Margin improves, **total degrades**. No paired Brier or log-loss evidence for moneyline, let alone the five actual lottery/crown line prices.
5. Source-capture and training dates are not independently sufficient to certify a `WALK_FORWARD_PASS` catalog.

**Decision:** Do not create `config/nba_player_impact_validated.json`; do not enable `PLAYER_IMPACT_APPLIED_EXPERIMENTAL` as a standard production signal. Keep actual player status, source freshness and uncertainty available to the report. The base model and all five analyses continue unchanged unless a valid new independent study passes.

## Next unblocking evidence
- Add identity crosswalk (NBA stable player ID, canonical teams, transfers) and missing-game/roster minutes history, with per-match validation.
- Verify exact report availability at or before desired historical decision time, plus official UTC tipoff for every matched fixture.
- Train regularized player-level impact on separate earlier seasons, calibrate independently, then evaluate on a **truly untouched later season**, including all five markets at archived genuine point-in-time 007 prices. Publish paired uncertainty metrics and harm/benefit by status, team, and market.
