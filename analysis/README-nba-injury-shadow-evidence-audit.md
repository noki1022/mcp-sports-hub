# Existing prospective injury shadow × same-capture 007 market evidence

The repository already has a **real injury shadow system**. The objective of this PR is **not** to recreate it or imply a made-up player impact. The production schedule has been saving `nba_injury_prospective_2130.json` in `reports/daily/<date>/2130/`; its original model probability is frozen before tipoff, with official injury PDF quality and source timestamps. The prospective injury-modified probability is absent when no frozen player replacement candidate has been validated.

## Research-only audit

Read only the existing archived injury shadow, `nba_priority_model.json`, `titan007_priority_joined.json`, and `titan007_priority_movement.json` from **the same date and slot**. Join on explicit 007 game ID and independently verified ESPN NBA event ID, full home/away names, and precise tipoff UTC. Reject cases where market snapshot, official injury report, or prediction was not captured before tipoff. Also require the existing model's injury context to match the source report clock and quality from the frozen injury shadow.

Audit six features without inferring unavailable values: actual source report status, published Out/Doubtful/Questionable counts on both teams, available actual player identity/verified prior-minutes vectors, official source age, and genuine same-capture spread/total line moves from the raw 007 market. Crown bookmaker ID3 and original raw price side are preserved and **never** reinterpreted or assumed certified.

Separately fetch ESPN *completed game* final scores and use them as postgame labels only. Compute Brier/accuracy for the original frozen model, and a paired injury-versus-original Brier only when an authentic **previously frozen injury model candidate** and valid paired forecast exist. If paired_count is zero, injury uplift is reported as **null**, not zero and not an improvement.

## Important limitation

Existing historical injury studies reported encouraging average margin-error changes, but their Brier confidence intervals crossed zero and are retrospective research. Original player report version clocks are not independently proven publication times. Neither those studies nor this audit can claim player-specific causal impact, 007 historical EV/ROI, or a live ready replacement model. We must first obtain a training-compatible person-ID join, player prior minutes/role and a frozen calibrated replacement candidate, then collect hundreds of same-fixture actual prospective paired forecasts under one model version.

## Run

    python3 analysis/nba_injury_shadow_evidence_audit.py --selftest
    python3 analysis/nba_injury_shadow_evidence_audit.py --root . --out /tmp/nba-existing-injury-shadow-evidence

Produces `audit.json` and `existing_frozen_injury_market_evidence.jsonl` as a separate 60-day GitHub Actions artifact. Research-only PR/manual workflow, **no edits** to live priority 21:30/06:30 scheduling, original injury capture, model decisions, injury prerequisites, 007 feeds, Cloudflare or PushPlus.
