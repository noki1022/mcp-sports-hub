# NBA recent completed games — injury-shadow pretip audit (2026-10-31 to 2026-11-03)

**Source:** Genuine repo-archived 007 fixtures, 21:30 original baseline predictions,
same-slot official NBA injury context and previously frozen injury research records,
matched to separately settled final scores. The real GitHub Actions job passed its
frozen-input, source SHA256 and independent outcome-match checks on 2026-11-04
Beijing time. CI Actions result: [PR #254](https://github.com/noki1022/mcp-sports-hub/pull/254).

**Read first:** This is **not** an injury-adjusted probability model backtest.
No certified injury-adjusted probability was frozen in these historical artifacts.
The only honest injury-vs-original improvement score is **null**, not zero and
not a positive claim. Newly observing a recent score cannot retroactively
create a valid pregame injury prediction.

## Verified counts

| Item | Observed |
| --- | ---: |
| Completed independent NBA fixtures in the four Beijing cohorts | **36** |
| Missing pretip archived injury shadow — quarantined | **10** |
| Genuine prior frozen original home-win probabilities with settled finals | **26** |
| Actual 21:30 Beijing time sealed cohort (Nov 3) | **15** |
| Older 21:20/21:25 pretip forecasts, for reference only | **11** |
| Both teams' official NBA injury reports verified within the 26 | **11** |
| Incomplete / unsubmitted / unknown official report within the 26 | **15** |
| Frozen, eligible numerical injury-corrected candidate vs baseline pairs | **0** |

## Original model (moneyline) — *not* injury-adjusted

| Cohort | Correct | Hit rate | Brier (lower is better) |
| --- | ---: | ---: | ---: |
| All 26 genuine earlier frozen originals | 16/26 | 61.54% | 0.20993031 |
| **Strict 21:30 only, 15 games** | **9/15** | **60.00%** | **0.21877059** |
| Both teams' official injury report verified | 7/11 | 63.64% | 0.19219910 |
| Official report incomplete / unknown | 9/15 | 60.00% | 0.22293319 |

**WARNING:** The 63.64% vs 60.00% cohort difference has very few games and
different opponents/market strength. It **does not** measure the incremental
effect of the injury feature and is not a valid randomized or matched paired
injury-model comparison. The 11 older 21:20/21:25 games must not be renamed
as certified 21:30 forecasts. Ten Oct 31 fixtures with no compatible frozen
injury research file are explicitly blocked, not counted as a zero-injury
cohort.

## Original five-market forecasts (only pretip-signed forecasts)

Seven older Nov 1 matches lacked saved five-market forecast generation-clock
proof; the evaluator therefore does not invent that clock or count their
five-market probabilities. It scores 19 timestamp-verifiable Nov 2–3 games,
excluding absent offer/direction and push outcomes per market.

| Market | Original hits | Accuracy | Brier |
| --- | ---: | ---: | ---: |
| Jingcai win/loss | 10/17 | 58.82% | 0.24706756 |
| Jingcai handicap | 9/19 | 47.37% | 0.24539229 |
| Jingcai totals | 9/19 | 47.37% | 0.26644579 |
| Crown ID3 handicap | 9/19 | 47.37% | 0.25779635 |
| Crown ID3 totals | 8/19 | 42.11% | 0.26994118 |

The evaluator always uses the *original pretip line* and signed **home**
handicap. A later settlement's market line is NEVER substituted. Only
non-push outcomes count. Missing or not-listed team injury reports do not
mean the team is healthy; medical absence/uncertainty is distinguished
from G League assignment and nonmedical statuses.

## Real evidence and instructions to reproduce

```sh
python3 analysis/nba_recent_injury_settled_backtest.py --selftest
python3 analysis/nba_recent_injury_settled_backtest.py \
  --repo . --start 2026-10-31 --end 2026-11-03 \
  --out /tmp/actual-recent-injury-backtest.json
```

CI archives the full per-game JSON including each game's actual score,
original model Brier, official pretip report metadata, five-play outcomes,
game/team ID checks and **per-file SHA-256 fingerprints**, for 90 days as
`nba-recent-actual-settled-injury-pretip-backtest`. Unlike the compact
summary above, that JSON is auditable per game.

## What is still needed to test actual injury model value

1. Before tip, verify official injury PDF and BOTH teams, current-roster
   stable identities, prior same-team minute roles and defensible depth
   replacements. Keep uncertain statuses and unproven players unknown.
2. Train/freeze injury coefficients only on chronologically earlier games,
   separately from the original and independent market forecasters.
3. Seal the actual **injury model's numerical five-market probabilities**
   and unchanged exact Jingcai/Crown ID3 lines BEFORE the outcome; record
   coefficients, code versions, source timestamps and SHA256.
4. Grade same-game same-line hit/Brier/LogLoss vs both the frozen original
   and market-only shadow, with independent dates and no lookahead.
5. Do not claim lift on a sample with zero genuine injury-candidate pairs.

**Scope:** research CI only; does not alter collectors, production weights,
PushPlus, original official injury prerequisite, Cloudflare or overnight schedule.
