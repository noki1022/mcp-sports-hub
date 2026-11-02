# Settle only immutable future NBA injury-minute research pairs

PR #223 has created a new pretip feature-transfer research artifact containing a baseline trained on historical NBA scores and a separate same-trained injury-prior-minute challenger. It deliberately **does not** pretend the study baseline is the full production moneyline probability. Its initial 29 future NBA fixtures yielded **zero eligible pairs**: 23 did not have both teams' injury report published and six had unmatched unique person IDs / prior same-team minutes. That is valid fail-closed behavior and must remain visible.

This independent result grader reads the ORIGINAL immutable artifact from a specific past GitHub Actions run, checks its SHA256 and captures, and matches any actually sealed same-fixture paired probabilities to independently completed ESPN NBA finals by exact ESPN game ID, home/away team code and tipoff UTC (within 3 hours). It does not reconstruct a missing injury probability, use the current model to rewrite an earlier prediction, or silently grade a game still in progress.

## Scoring

For genuinely frozen pairs ONLY: separate independent baseline-versus-injury correct directions, Brier, LogLoss, and matched differences, with original home/away score proof, ESPN source SHA and collection clock. Incomplete / mismatched finals and fixtures stay pending or quarantined. An archive containing 0 actual paired forecasts yields 0 gradeable pairs and null metrics. No win rate, lift, or profit claim is made for that run.

## Commands

Selftest from PR checks:

    python3 analysis/nba_injury_minutes_pair_scorecard.py --selftest

After actual games finish, go to **GitHub Actions → Independently settle actual frozen NBA injury-minutes research pairs (research) → Run workflow**, provide the **original** before-tip forecast run ID. Initial source 41412031386 has zero eligible pairs and will truthfully grade zero. New future runs with real eligible pairs can be scored the same way.

This scorecard is research-only and still does **not** compare against the original deployed production model or as-of 007/ID3 Crown odds. No new scheduled trigger, no active model, no PushPlus message and no Cloudflare change. Model acceptance still requires hundreds of new independent prospective same-fixture pairs, real 007 as-of market lines, and a compatible production residual calibration.
