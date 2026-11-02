# 007 JC numbering failure RCA — 2026-11-02

## Incident and source evidence

The 007 NBA fixture join and the 007 JC fixture-number data BOTH included the game ID. The failures were **false-negative team nickname checks**, not missing 007 lottery issue numbers, swapped teams or a missing API response.

- 2026-11-01 21:30 original report for Beijing 2026-11-01: 6 of 7 verified, game `728884`, Houston Rockets home vs Oklahoma City Thunder away, failed `HOME_AWAY_MISMATCH`. Historical 007 JC raw response for that date was **not archived**, so precise old JC source aliases cannot be truthfully certified.
- Beijing 2026-11-03, snapshots 12:00, 14:00, 15:00, 18:00, 21:00: precisely 14/15 verified EVERY time, except `728298`, Cavaliers home, Thunder away, same `HOME_AWAY_MISMATCH`. The repeated team and same unchanged predicate make the same root cause strongly supported for the first incident.
- Verified on public 007 JC `https://jc.titan007.com/xml/bf_jc_lq.txt` during real GitHub Action [41451231342](https://github.com/noki1022/mcp-sports-hub/actions/runs/41451231342):
  `728298` source label `周一302`; home aliases `["骑士","騎士","骑士"]`; away aliases `["雷霆","雷霆","雷霆"]`. Source team order is **correct** (home Cavaliers and away Thunder); exact 007 game ID is present.
- Before fix, `scripts/verify_007_jc_fixture_identity.py:comparable` required `len(canonical)-len(alias)<=5` for suffixes. `俄克拉荷马城雷霆` has **8** Hanzi; `雷霆` has **2**, difference **6**. As a result, the Thunder away side incorrectly failed despite its correct nickname. `克里夫兰骑士` (6 Hanzi) vs `骑士` (2) passed difference 4.

## Permanent precise repair

- Add **one narrowly source-evidenced exact canonical full-name/nickname mapping** `俄克拉荷马城雷霆 -> 雷霆`. Do **not** raise the global suffix limit: that would weaken the entire fixture identity security boundary for unrelated names.
- Maintain exact 007 game ID, correct home-vs-away side, sale-label syntax, Beijing tipoff clock tolerance, and duplicate-code rejection. Explicitly test the opposite team order is **not** accepted, and unrelated long nickname ending in `雷霆` is not accepted.
- When any future ID fails, the frozen JC snapshot now retains source raw home/away aliases, independent home/away checks, reversed source side check, source fixture number not verified, and side mismatch reason. The capture script writes explicit unresolved-ID diagnostics to GitHub job logs. This removes the prior hidden opaque `HOME_AWAY_MISMATCH`.
- User-confirmed `周一302` remains recorded as display-only fallback for provenance, but **is not needed for this current 15-game board** and never upgrades a team orientation or price.
- Actual **source-only** independent CI [41451834471](https://github.com/noki1022/mcp-sports-hub/actions/runs/41451834471) fetched the live 007 JC fixture XML, called `verify(board,raw,overrides=[])` with MANUAL overrides DISABLED, and recorded `verified_from_007=15, user_confirmed=0, total=15`; Thunder 728298 auto-verified `周一302`. No live odds or model predictions were mutated; no PushPlus was sent.

## Scope limitation

This verification proves a correct fixture-number join for the Nov 3 15-game as-of snapshot, and explains a repeatable code bug. It does not assert that Nov 1's unavailable historical raw feed was downloaded later, nor that unrelated future source alias changes cannot occur. Those changes now retain full diagnostics instead of silently losing identity evidence.
