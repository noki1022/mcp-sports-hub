# Independent settlement for genuinely frozen NBA research forecasts

The first actual timestamp-frozen score-only forecast archive comes from GitHub Actions run 41391157150, created 2026-11-02 04:56:24 UTC, and contains 15 upcoming NBA games for Beijing 2026-11-03.

This research-only grader **never reconstructs predictions from current model weights**. It downloads the ORIGINAL pretip artifact, verifies manifest SHA256 and per-game capture-vs-tipoff times, and then independently retrieves completed ESPN NBA scoreboards by original Eastern calendar day. Only exact event ID, team order, UTC tipoff and verified complete final scores can settle a game.

If the game is still underway, missing from official completed scoreboards, conflicting in identity, or within two hours of tipoff, it is explicitly pending/quarantined and cannot be graded as a loss or win.

Once the fixtures have completed, GitHub Actions > NBA score actual frozen pretip shadow vs official finals (research only) > Run workflow, with forecast_run_id=41391157150, creates a new immutable scorecard artifact.

Local offline selftest:

    python3 analysis/nba_frozen_score_only_grade.py --selftest

On-demand live grading:

    python3 analysis/nba_frozen_score_only_grade.py \
      --input /path/to/original/frozen_pregame_score_only.jsonl \
      --manifest /path/to/original/manifest.json \
      --out /tmp/nba-frozen-score-only-grade

The scorecard gives true frozen home-win accuracy/Brier/logloss and mean absolute margin/total error, plus per-game exact scores, source URL and fetch hash. It does not score an unverified historical bookmaker quote, prove 007 value edges, modify production, or auto-promote the candidate.

No new scheduled triggers. PR checks run offline tests only; a manual dispatch is required after game completion. The production 007, Crown ID3, Jingcai, Cloudflare and PushPlus jobs are untouched.
