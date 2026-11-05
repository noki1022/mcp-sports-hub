# Basketball and football multi-snapshot analysis

Snapshots describe a trajectory, not independent matches. Duplicate timestamps
are collapsed, conflicting same-time evidence is excluded, and only the same
identified fixture before kickoff can contribute. Every interval matches common
book IDs (minimum three); changing the set of institutions cannot create a move.

The shared engine records the first-to-current matched-book change, last change,
change/hour, fraction of books moving together, cross-book MAD, reversals, gaps,
coverage churn and how many intervals actually changed. Repeated identical quotes
never increase confidence. Invalid/missing history keeps the first-capture path.

## Basketball integration

`nba_five_markets.py` reads retained `reports/daily/<target date>/**/nba_market_consensus.json`.
It uses the already verified 007 company quotes, outlier exclusions and user-confirmed
first-home/over orientation. Each quote is translated at the **current model sigma**
onto a common scale: `mean = raw line + sigma * normal_inverse(devig first-side p)`.
For spread, the positive source line means HOME GIVES, so this mean is home-minus-away.
For total, it is total points. Therefore line and water changes are considered together;
raw prices at different handicap lines are never compared as equal outcomes.
All historical quotes are reinterpreted at the same current sigma.

Each of the five exact JC/Crown markets stores `dynamic_market_path`; the game
stores joint market-implied home/away points and injury adjustment status. Market
implied points are model-dependent interpretations, never actual scores or proof
of an injury. The independent NBA probabilities are **not reweighted by this change**:
no independently validated temporal coefficient exists yet. Existing injury adjustment,
exact market lines, probabilities, selections and grading remain intact.

## Football integration

The existing raw-release vault is read before forecast generation. The last three
Beijing archive days cover the adapter's 48-hour evidence window. Only the exact
snapshot JSON member is read from each ZIP; no archive paths are extracted. Remote
assets are never modified or deleted. Restore errors/timeouts are optional history
gaps, not collection/prediction failures; partial restored history remains usable.

Old verified Asian prices are inverted using the **current independent baseline
and total-goal expectation**. Thus a changed baseline does not masquerade as a
market move. Current fixture identity, pre-kickoff capture, quote freshness and
main-line provenance checks still apply. Only the existing selected book evidence
is used; absent/suspended quotes are not fabricated.

The existing bounded market correction is multiplied by an explicit conservative
risk factor: 0.5 for a detected reversal, 0.5 for inadequate matched-book overlap,
0.5 for a nonzero latest move supported by fewer than 60% of matched books, and
0.5 for a gap exceeding three hours. Factors multiply; all are <=1. These are
**untrained attenuation heuristics**, not proven accuracy gains. First capture or
consistent movement retains the previous correction strength, never amplifies it.
HAD and official HHAD are recomputed from one score grid; the goal-total expectation
is unchanged because Asian handicap does not identify total goals. Every invocation
starts from the independent baseline, so corrections do not compound.

## Verification and limits

Offline tests cover first capture, repetition, clock conflicts, duplicate institutions,
future data, identity mismatch, coverage churn, water-only movement, reversal,
long gaps, safe archive parsing and a numeric football probability change.
No hit-rate improvement has been measured by these tests. The new fields are retained
with existing forecast archives for future time-ordered evaluation. No LLM/API call,
new push schedule or independent shadow-model workflow is introduced.
