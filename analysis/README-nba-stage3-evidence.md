# NBA Stage 3: Evidence-first research gates (no production changes)

## Findings from repository inspection (Beijing dates 2026-10-31 / 2026-11-01)

- There are two accessible settled date archives: 10 games on 2026-10-31 and seven on 2026-11-01 (17 distinct fixtures). These are not sufficient for an independent full model-uplift validation.
- Recomputed 84 graded on-sale market outcomes from final score, explicit signed-home handicaps, lines and forecast directions: no disagreement in that inspected subset. One additional JC moneyline record was explicitly `EXCLUDED_NOT_ON_SALE`; it is not a loss.
- In the inspected 2026-11-02 20:02:21 UTC top-ten-source snapshot, all 80 raw quote rows say `side_orientation: UNVERIFIED_RAW_SLOTS`. This is **not** evidence that the user's confirmed 007 home-left/over-left display convention is wrong; it means the raw quote-slot direction is not *independently* attested by the source data. A research probability-vs-score comparison must disclose that assumption and cannot certify the source slot mapping from its label alone.
- Fetch timestamps are not independent evidence of an individual bookmaker's *own* most recent price update time. Do not mislabel page fetch as an actual bookmaker tick.
- Previous PR #188 provides research-only same-line consensus and five-market calibration; PR #133 audits injury history but cannot validate a genuine five-market causal uplift without paired, genuinely pre-tip player-impact data; PR #181 found insufficient performance improvements for a fatigue/H2H feature promotion.

## Implemented source audit

`analysis/nba_stage3_evidence_audit.py` reads existing 007 snapshots, locked frozen forecasts and settled five-market reports. It makes **no network requests** and modifies **no production artifacts**. For each market, it:

1. Recomputes settled results using actual final scores, the *signed home handicap* for handicap markets, and actual O/U line; keeps unsold markets excluded and flags duplicate game-market identities.
2. Counts unique games and Beijing dates rather than treating repeated intraday captures as independent historical games.
3. Separates raw 007 odds completeness from **verified orientation**. It never translates unverified raw slots into an empirically certified home/away/over/under forecast.
4. Checks quote source IDs, valid HK water prices and page-capture intervals. Keeps Crown fixed to 007 ID 3.
5. Audits quote locking and forecast-generation timestamp evidence; missing actual generation time is explicitly reported as requiring a conservative Git commit-time attestation instead of silently assuming the board capture equals the prediction freeze.

CI runs a synthetic self-test and the real committed-archive audit, saving a JSON artifact. The audit can **block** evidentiary review but can never enable production fusion or calibration. Errors in archived settlement directions must be resolved before interpreting calibration uplift.

## How to complete a credible model validation

**A. 007 multi-company odds.** Obtain an independently confirmed mapping of source water slots to each side; use only genuine exact same-line quotes, with a traceable pre-tip source fetch and a forecast that was frozen afterward. Compare independently frozen model probability vs median company no-vig probability on the same market, direction and line. Do not infer moneyline from spread prices.

**B. Injury impact.** Verify player identifiers and their team **as of the historical match date**, actual official injury-report publication times, and whether new availability information preceded the model freeze. For the same games, independently score no-injury versus injury-aware frozen predictions. Avoid double-counting injury information already embedded in later market prices.

**C. Five-market proper scores.** Use untouched chronological partitions with an embargo, evaluate Brier, log loss, calibration and directional accuracy per market; cluster confidence intervals by Beijing game date. Separately validate the quoted odds for ROI: accuracy alone cannot show a profit edge. Do not optimize thresholds or weights on the reported holdout.

**D. Advance gate.** At least 200 distinct settled games spanning 24 Beijing dates (source data precheck only), validated direction, no mismatched settlement, comparable pre-tip frozen forecasts, and a separate genuinely untouched future evaluation. These are necessary, not sufficient; the audit deliberately never returns `production_promotion_allowed=true`.

## External research consulted

- *Player absence and betting lines in the NBA*, Finance Research Letters (2015), DOI 10.1016/j.frl.2015.02.004. Meaningful player absences distort opening lines, with biases largely absorbed by game time; an injury flag by itself is not a value edge.
- *Learning, price formation and the early season bias in the NBA*, Finance Research Letters (2007), DOI 10.1016/j.frl.2007.04.002. Early-season totals and open-to-close information merit segmented prospective testing, **not** a blindly copied historical betting strategy.
- *Inefficient Forecasts at the Sportsbook: An Analysis of Real-Time Betting Line Movement*, Management Science (2024), DOI 10.1287/mnsc.2022.00456. Detailed within-day line histories can reveal non-monotone informativeness, but that paper studied MLB; treat transfer to NBA as a hypothesis.

No synthetic holdout, fabricated probabilities, live picks, or automatic strategy changes.
