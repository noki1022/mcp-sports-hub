# NBA complete current-season score bridge / independent recent score monitoring

## Actual missing data

The 23,574-game historical score+odds benchmark currently ends January 7, 2026. Fitting and monitoring it alone omits the remainder of 2025–26 and current 2026–27 games. The existing repository already has a paired-home/away BoxScore Lab team-game parser; use it instead of inventing records.

## Source admission

1. Fetch 2025–26 and 2026–27 paired team-game season logs using the existing robots-aware bounded public reader. Preserve source checksum.
2. Require each game to have a unique reciprocal home+away record with exactly matching scoring, winners, ET game date and franchise identity; quarantine malformed/unpaired games.
3. Reconcile 2025–26 against the pinned historical 23,574-game archive using date + canonical home/away + final score; reject mismatches rather than favoring either source.
4. Retrieve completed official-style ESPN game scoreboards for bounded 2026–27 ET dates, crosscheck final score with independently paired BoxScore Lab rows. If ESPN unconfirmed, exclude the game from outcome monitoring and state updates. ESPN final scores are postgame labels only.
5. Freeze training at season boundary July 1, 2026. Online rating features use only completed games dated before each prediction day. Never refit parameters on 2026–27 outcomes when evaluating that season.
6. Save audit and frozen prospective research parameters to Actions artifacts; no update to active model weights, 007 fixtures/odds, Cloudflare, PushPlus or published forecasts.

## Audit contents

Counts of previously missing late 2025–26 games, exact overlapping independent results, quarantined score conflicts, ESPN-verified 2026–27 games, feature train counts, and baseline-vs-opponent MAE/Brier/accuracy on genuinely newer game dates. This remains a retrospective monitor unless model forecasts were actually frozen before games; its coefficients must not be promoted on a retrospective score comparison.

## Reproduce

    python3 analysis/nba_current_season_score_bridge.py --selftest
    python3 analysis/nba_current_season_score_bridge.py --out /tmp/nba-current-season-score-bridge

This research is intentionally independent from production scheduling. It can be run on demand to refresh an evidence artifact without adding another background workflow.
