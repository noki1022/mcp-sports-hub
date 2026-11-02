# 21:30 main-chain delivery idempotence (2026-11-02)

Verified from real failed run [41310772662](https://github.com/noki1022/mcp-sports-hub/actions/runs/41310772662): the normal original model actually produced valid data and PushPlus API accepted its 21:21 output twice; a later rerun of artifact upload failed HTTP 409 Conflict. Three later 21:30 priority recovery runs (41313906204 / 41314784868 / 41315401864) correctly rejected stale after-21:58 pushes but STILL had the same artifact name collision and were marked failed.

This P0 maintenance fix preserves the 21:30 original NBA five-market model, injury gate, PushPlus layout and scheduled time; it changes ONLY the final original push/dedup and artifact publishing:

- Recheck the canonical original accepted marker on remote `main` immediately before actual push and check the local PushPlus accepted status; any accepted result sets `skip=true`, so the next send and archive stages are not run.
- An existing corrupt/unverifiable remote accepted marker aborts instead of resending.
- No empty Git commit when the original 21:30 official answer was already archived.
- Unique artifact per workflow run/attempt, with GitHub `overwrite: true`, preventing the observed 409 conflicts on a retried upload.
- Original push remains entirely the **original** model and no shadow result is read.

**This alone does not establish the user-requested two independent models or the definitive two-model 21:30 postgame examination.** That is implemented separately with strict time-locked independent original and shadow forecasts. Avoid prematurely grading 18:00 or score-only historical model as a 21:30 shadow answer.
