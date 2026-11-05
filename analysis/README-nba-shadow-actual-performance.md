# Independent shadow: actual frozen performance (2026-11-05)

## Current production and scoring contract

Original model remains the only PushPlus forecast. The independent market shadow runs after each accepted capture, without original model predictions or final scores mounted in its inference sandbox. Both models' actual 21:30 answers are sealed before tip in audit/dual-model-slot-evidence. Only these immutable final exams are scored. The old 18:00-specific shadow and grading entry points were removed; earlier documentation describing them is superseded.

## Actual prospective results

Source: [real frozen ledger scoring run](https://github.com/noki1022/mcp-sports-hub/actions/runs/42010763862), job 127188899191. Graded Beijing dates: 2026-11-03 and 2026-11-05; **29 independent fixtures, 2 dates**. No historical model inference or training was performed to create these scores. Same-game and same-line original/shadow direction pairs exclude neutral shadow forecasts; probability scores include neutral 50% predictions. Missing original direct markets are not fabricated.

| Market | Original correct / directional pairs | Shadow correct / same pairs | Probability pairs | Neutral shadow | Original Brier | Shadow Brier |
|---|---:|---:|---:|---:|---:|---:|
| JINGCAI_WIN | 16/27 | 18/27 | 27 | 0 | 0.228817 | 0.218301 |
| JINGCAI_HANDICAP | 13/27 | 16/27 | 29 | 2 | 0.246959 | 0.242080 |
| JINGCAI_TOTAL | 16/27 | 18/27 | 29 | 2 | 0.247254 | 0.235393 |
| CROWN_HANDICAP | 4/7 | 4/7 | 29 | 22 | 0.253292 | 0.248961 |
| CROWN_TOTAL | 4/12 | 5/12 | 29 | 17 | 0.249256 | 0.250446 |

Lower Brier is better. Crown total is worse on this cohort; Crown direction coverage is low. Two dates do not establish stable improvement or an 80% hit rate.

## Existing robust multibook candidate

The separately precommitted ROBUST_MULTIBOOK candidate has only **14 frozen fixtures from one date** available in these archives. Its mean Brier differences versus the independent median baseline are -0.000375 (JC win), -0.000515 (JC handicap), +0.000188 (JC total), -0.000446 (Crown handicap), -0.000390 (Crown total). JC total worsened; all apparent differences are small. It must not be promoted based on this result. Neutral candidate forecasts are now included in proper scores, with directional denominators and coverage shown separately.

Cumulative evaluation keeps candidate versions separate, rejects duplicated dates/fixtures and reports Brier/log loss against both the original and independent baseline on the exact same cohort. Date-cluster bootstrap intervals are deliberately null until at least five independent dates; even a later descriptive interval does not authorize model promotion. The new feature v2 has **no newly settled prospective results yet**. Existing v1 results are not relabeled as v2 gains.

## November 5 improvements

- Compute market movement from matched-company deltas. Two changing group medians previously allowed company mix to suppress/reverse a genuine trend. Duplicate company IDs are quarantined. Preserve the unpaired group change only as a diagnostic.
- Retain a verified team's official injury players when the other team is unpublished or malformed. Mark the other side UNKNOWN and both-team readiness false. Future, wrong-date and ambiguous source guards remain; no missing report is interpreted as healthy.
- Preserve one original and one independent model. No new pseudo-models, arbitrary probability boosts, scheduler change or duplicate push.

Injury features remain observational: core-role impact and adjusted probability are null until valid independent numerical evidence exists. Historical studies and role/minute evidence are not a calibrated live injury effect. Current source parsing does not preserve game-date columns from multi-day official injury PDFs, so a prior-report-date allowance cannot safely be enabled by merely relaxing date checks; that remains a separately testable source-provenance gap.

## Historical evidence boundary

The earlier 1,312-game 2024–25 study used source-defined opening/closing consensus without independently verified bookmaker quote-update timestamps. Its 380-game later evaluation was previously examined, not an untouched prospective holdout. On 374 paired directional moneyline games, opening market hit 264/374 and historical shadow hit 263/374. Those numbers must not be mixed with the actual 2026 frozen 21:30 cohort above.

Production promotion remains disabled. Existing requirements include at least 100 independent completed fixtures per target market, at least 24 dates, credible paired probability and direction improvement, verified injury inputs and untouched prospective evaluation. Raw archived answers are never rewritten.
