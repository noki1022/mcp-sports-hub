# Actually frozen NBA injury prior-minute research pairs (not production)

## Narrowed missing link

The existing 21:30/06:30 NBA official injury shadow has archived original production probabilities, but no certified matching injury-modified candidate. Historical PR #222 demonstrated retrospective value of the injury status + prior-role feature set (2,769 independent fixtures; 1,379 train, 675 validation, 715 explored later evaluation) **without certifying those effect coefficients or actual report release timestamps**. The 2026-27 pretip injury source work (#220/#221) gathers exact source capture timestamps, matched current team player identities and prior same-team minutes, with 26/44 strict matches. Do not treat the 8 extra old-team minutes as equivalent current-team usage.

## This PR

Use only the exact historically tested *minutes-only* injury feature:

`(sum_home ((0.90 - status_probability) * earlier_same_team_minutes) - sum_away (...)) / 40`

Original status weights are from the existing archive research; they are fixed proxies, **not independently calibrated NBA availability or causal player impacts**. Never treat unknown/incomplete players as zero. Earlier team form is reconstructed from genuine date-prior completed NBA score results; no same-day results, unknown player log or current-game boxscore enters predictions. Compare two models trained on the **same old fixtures and same baseline team-form features**, using the same chronological fit and a precommitted validation gate: baseline team form and team form + prior-minute injury signal.

For real future fixtures, require both teams' official reports published, every injury-listed player uniquely matched to a current ESPN roster and actual earlier same-team minutes, exact game/side and source identity, and actual PDF/roster fetch clocks before kickoff. Any failure is recorded as an explicit block with no probabilities.

If the previous-season validation gate passes and actual future evidence is complete, freeze both research probabilities, exact tipoff, raw source hashes, candidate training parameters, original athlete IDs and status-weighted prior minutes into an immutable SHA256 manifest. No existing production model output is changed, and **the paired research baseline is not misidentified as the actual production base probability**.

The original historical archive is not an independently verified original official publication-time tape, and 2025-26 was previously examined. A genuinely before-tip future research forecast with new realized results is the only later source of prospective performance. Existing moneyline / Jingcai spread and Crown ID3 market probabilities are not silently recalibrated.

## Reproduce

```sh
python3 analysis/nba_injury_minutes_prospective_pair.py --selftest
python3 analysis/nba_injury_live_roster_feature_freeze.py --out /tmp/live-before-tip-injuries
python3 analysis/nba_injury_minutes_prospective_pair.py \
  --features /tmp/live-before-tip-injuries/prospective_official_injury_roster_minutes.jsonl \
  --audit /tmp/live-before-tip-injuries/audit.json \
  --out /tmp/nba-frozen-injury-research-pair
```

An isolated PR/manual CI uploads a 60-day artifact. No scheduled workflow is added or edited. The live chain, official injury prerequisites, 007/ID3 Crown/Jingcai, existing PushPlus messages and Cloudflare schedule are unchanged. At zero eligible fixtures, report zero pairs and exact block reasons **rather than pretend to produce an injury probability**.

## Follow-up

Only when enough new, independently sealed *same exact-game* outcomes are gathered should the existing prospective scorecard compare this true research pair. A separate true production-baseline-plus-injury experiment requires training a residual effect conditioned on the deployed production margin model; independent historical team-form coefficients cannot simply be added to production margin predictions.

## Partial coverage sensitivity extension

The first actual future run (#223) inspected 29 games and produced no complete
research pairs: 23 lacked published two-team official report, and 6 had
verified reports but incomplete same-team player IDs/minutes. To retain useful
signal without inventing a precise forecast, blocked cases **with both team
reports published** can now produce an additional **hypothetical missingness
sensitivity** record. This does not change the production model or the strict
all-player-verified paired gate.

- Fix only players whose stable NBA player ID, current team and previous
  same-team minutes are already verified.
- For each other officially listed player with a verified name/status/side
  but no trusted prior minutes, examine a deliberately labeled hypothetical
  0–48-minute range. This range is **not statistically estimated and not a
  guaranteed bound**: overtime can exceed 48 minutes.
- Calculate the corresponding scenario interval in exactly the original
  historical prior-minutes feature, and (only when the historical validation
  gate passes and team form is available) the *conditional model sensitivity
  range*. It is not a confidence interval, no unique injury probability is
  supplied, and no change in the match's actual probability is claimed.
- Any bad clock, missing team report, inconsistent player side/status, source
  SHA mismatch or fabricated numeric minutes without ID blocks even the
  scenario output.
- All partials remain marked BLOCKED in the original immutable model-pair
  file and cannot enter the actual paired injury scorecard. Exact counts and
  scenarios are written to the existing 60-day research artifact.

To increase verified complete paired cases, the next source-side task is to
improve official name reconciliation and genuine player ID/prior same-team
minutes, never to promote interval midpoint as a measured forecast.
