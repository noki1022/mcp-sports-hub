# P0: Three play directions from multi-company 007 lines — no arbitrage

## Correct purpose

The goal is to improve **NBA moneyline direction, handicap cover direction and full-game total direction**, not bookmaker arbitrage, selecting better prices, maximizing profit or bet ROI. Jingcai's three markets remain the primary focus, Crown ID3's handicap and total are additional separate target judgments. Do not generate additional pseudo-models.

## What real 007 archives we can actually compare

- Existing persisted `reports/daily/<Beijing-game-date>/1200/nba_market_consensus.json` and later `.../1800/nba_market_consensus.json`: real company IDs and actual 007 quote captures, same 007 game/ESPN ID, same home/away/tip and complete pretip timestamps.
- Existing later `nba_dynamic_five_market_shadow.json`: five independent model predictions and corresponding JC/Crown *actual current* handicap and total lines. Never overwrite or mutate these probabilities.
- The only time-ordered signal is the identical bookmaker's line movement from first to later snapshot. Require >=3 *same-company paired* observations and >=60% of all paired companies in one direction, at least 3 movers, plus a consistent movement of the actual cross-company median. Changing the composition of captured companies is NOT a line change.
- Correct 007 convention: source spread line is **HOME GIVES**, so moving +7.5 to +9.5 means the bookmaker expects a stronger home team. A movement from -7.5 to -9.5 in the conventional **signed HOME handicap** convention is equivalent, but its numeric difference has the opposite sign; do not mix these conventions.
- An increase in full-game line (e.g. 220.5 -> 224.5) signals the market's expected points increasing, not guaranteed `OVER 224.5`. The live model still evaluates Over/Under at each **exact current JC or Crown threshold**.

## Five distinct decisions and their evidence

1. `JINGCAI_WIN`: if verified company/consensus home-spread favor shifts toward HOME and the frozen independent model predicts HOME_WIN, flag as `CORROBORATES_MONEYLINE_SIDE`; opposite => `CONTRADICTS_MONEYLINE_SIDE`, no movement => unknown. This **may support directional confidence** but does not justify increasing probability without validated asof outcome history.
2. `JINGCAI_HANDICAP`: record market's relative home/away strength trend but always label `DIRECTIONAL_CONTEXT_ONLY_NOT_COVER_SIGNAL`. A larger favorite spread often **raises the number of points needed for a HOME cover**. Do not convert home-favored line movement to automatic HOME_COVER.
3. `JINGCAI_TOTAL`: rising/falling total line is contextual evidence for higher/lower scoring environment. Check independent model's Over/Under at the target line separately; cross-validation is not itself a calibrated cover probability.
4. `CROWN_HANDICAP`: identical principle applied to ID3 direct threshold with source ID3 retained, never replaced by another bookmaker or a consensus line.
5. `CROWN_TOTAL`: identical principle applied to ID3 direct total threshold.

Output is a structured per-game five-market directional evidence artifact with the frozen original model direction and probability, market-paired company counts, every actual company line change and strict source/time digest. It is intentionally NOT a new PushPlus UI report; default scheduled production automation is preserved.

## Current research promotion rule

- Input: real same-game earlier and later 007 consensus captures; at least three unique same-company quotes and matched exact team/tip identities; model/source capture before tip.
- Truthful missing result: missing, stale, insufficient, ambiguous or mixed lines means NO VERIFIED TREND, never substitute company vote or forecast using another game. Original five model outputs still persist.
- No additional model probability yet; `confidence_adjustment_pp: 0.0` for all five markets. Keep previous model and injury-gate intact until chronological independently graded prospective validation shows a benefit.
- Do not count total-line change as a direct win-probability move; do not confuse the original bookmaker price-side water slot with validated betting direction.
- No EV, no ROI, no bookmaker price-gap selection, no arbitrage, no production code or PushPlus changes, no new cron. The PR/manual research workflow is an audit only.

## Run

    python3 analysis/nba_three_play_direction_shadow.py --selftest
    python3 analysis/nba_three_play_direction_shadow.py --target-date 2026-11-03 --earlier-slot 1200 --later-slot 1800 --out /tmp/nba-three-play-direction.json

CI uses genuine saved November 3 Beijing-tip-off research archives and checks independent model evidence, ID3, and exact per-company timestamps, returning a frozen JSON artifact. These have no results yet; they must be prospectively graded against official completed games before numeric model uplift can be certified.
