# Shadow Model Integration Contract — NBA 3 play directions, 5 execution thresholds

## Purpose
Prepare a safe, directly compatible, *read-only sidecar* between the current 007 multi-institution line-trend research and the actual existing NBA five-market forecaster. This is deliberately not an arbitrage, price difference, ROI, or bet EV project.

### Existing sources reused (without fetching new odds)
1. Real archived 007 multi-company noon and 18:00 same-game snapshots: `nba_market_consensus.json`, each capturing real provider IDs, raw lines and source timestamps.
2. Existing 18:00 independent model `nba_dynamic_five_market_shadow.json`, including five model first-side probabilities and explicit signed-home Jingcai/Crown direct lines.
3. Original immutable 18:00 five-market decisions in `nba_five_market_forecast.json`, including Jingcai game numbers and ID3 Crown.
4. Existing independently confirmed official final score file `reports/five-market-settled/<Beijing-date>/settlement.json`, only if available. NEVER create a fake result for a future game.

### New outputs for seamless future integration
Under `/tmp/nba-shadow-model-bridge/`, the research-only job writes:
- `nba_shadow_model_bridge.json`: stable per-game five-market model-interface object: unique fixture IDs and team/clock, original signed handicap and totals thresholds, original model win/cover/over probabilities, per-company market moves, movement co-direction checks and per-market data/availability blockers. JC markets 70% attention, ID3 Crown markets 30% attention; do not turn this into a blended probability.
- `nba_five_market_shadow_preintegration.json`: deep-copy of original direct five-market model with only a separately namespaced market-direction context added. All original directions, odds lines, signed handicaps and probability numbers remain unchanged and are hash-attributed to their original source.
- `nba_shadow_direction_scorecard.json`: prospective scoring of original five directions vs official completed final where strictly available. Unfinished games remain PENDING with 0 graded. No post-tip recomputation, repeated snapshots or pseudo outcomes.

### Safety before production wiring
- The new module is only a *model-sidecar interface*, not executed by existing CRON or PushPlus and does not change the actual model. A separate PR, objective historical testing and explicit promotion are prerequisites to numerical adjustment.
- Source time guard: earlier quote capture < later quote capture <= original five-market freeze < actual NBA tip; source team/ESPN/game ID and time must match, and repeated *same-company* movement uses at least three matched institutions. After-independent-model company evidence must be reported as available only for a subsequent model invocation; never retroactively pretend the earlier independent model saw it.
- Only compare original JC threshold to JC and Crown ID3 to ID3; preserve **plus/minus** signed home handicap, source ID3, no swapped home/away. No generated default quote and no invented moneyline from spread.
- Spread trend is directional support for HOME_WIN or AWAY_WIN, **not proof of covering the new handicap**; totals line trend is expected-score environment, **not proof of over at the new total**. Market disagreement is important information and never forced into a signal.
- In original snapshot, if a specific market has missing or invalid source/identity/first-side probability, mark numeric adjustment blocked without preventing other valid markets from being audited.
- Brier and direction accuracy are paired by immutable same game and market with final score from an independent settlement; no label / no paired cohort => no accuracy claim.
- No production modification, no extra schedule, no GitHub action cost in standard user flows, no collection, no changed iPhone or PushPlus output.

## Actual no-op test on saved 2026-11-03 12:00 to 18:00 previews

    python3 analysis/nba_shadow_model_integration.py --selftest
    python3 analysis/nba_shadow_model_integration.py --date 2026-11-03 --earlier-slot 1200 --later-slot 1800 --out /tmp/nba-shadow-model-bridge

Workflow validates all real 15 NBA games in the stored 007 board, exact five per-game targets, original five market source files and immutable hashes, unchanged original price thresholds/probabilities and independent score PENDING status. No outcomes are inferred or output as historical hit rate for games that haven't finished.

## Future graduated promotion criteria

1. First attain full all-five archived same-game coverage (JC three, Crown ID3 two), source identity, direction, injury and data quality, with 0 false labels or signed handicap errors.
2. True *before model prediction* feature capture: either freeze a new independent prediction after new company source capture, or use only market features acquired before original model generation; never leak late market knowledge into a frozen old prediction.
3. Evaluate original model and candidate improved model for identical games and identical JC/Crown exact lines across at least 100 independent settled fixtures and at least 24 Beijing dates **per target play**, plus separate completely untouched prospective holdout. Require paired Brier/logloss and five-market direction hit rates. Higher confidence only when a credible measured improvement remains after checking injury data validity.
4. Use a feature flag with default OFF, rollback on source ID/time mismatches, prevent double updates and duplicate push notifications. Only after prospective sample support may production probabilities be amended; no arbitrary boosts from multi-institution movement.
