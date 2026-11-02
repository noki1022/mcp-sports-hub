# Cloudflare secondary NBA scheduler (independent GitHub trigger)

GitHub Actions remains the production model and PushPlus executor. The
Cloudflare Worker only checks accepted-report markers and GitHub run state,
then triggers the existing GitHub Action when necessary. A Cloudflare 204
dispatch proves **queued**, not that the model ran or PushPlus reached a phone.

**A committed Worker is not an active deployment.** The 2026-11-01 GitHub
deployment log explicitly said `CLOUDFLARE_DEPLOY_PENDING` because credentials
were absent; the deploy steps were skipped. A manual Cloudflare installation,
if any, must be verified separately in that Cloudflare account.

## Safe activation

1. Create a fine-grained GitHub token scoped only to
   `noki1022/mcp-sports-hub` with Actions: Read and Write and Contents: Read.
2. In **GitHub repository Settings > Secrets and variables > Actions**, add
   `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and
   `CLOUDFLARE_SCHEDULER_GITHUB_TOKEN`. The first token needs Cloudflare
   Workers Scripts write permission. Never paste any token into a chat,
   commit, action input, or repository file.
3. On the repository Actions page, choose
   **Deploy Cloudflare secondary NBA scheduler (manual, verified)**,
   then **Run workflow**. A missing secret causes an explicit failed run,
   never a green "deployment succeeded" without deploying.
4. The workflow runs local Worker regression tests, deploys Wrangler Cron
   triggers, stores the fine-grained GitHub token as the Worker `GITHUB_TOKEN`
   secret, then compares the live Cloudflare API's Cron set against
   `scheduler/wrangler.toml`. A match is verified configuration, not yet
   evidence of a real scheduled invocation.
5. Check Cloudflare Worker Cron invocation logs and GitHub workflow_dispatch
   events for one full 00:30 and 03:30 Beijing cycle. Check matching
   `reports/pushplus-sent/YYYY-MM-DD/0030.json` and `0330.json` API-accepted
   markers, and ensure that there are no duplicate accepted sends.

The only **overnight analysis** Cloudflare attempts are Beijing 00:30 and
03:30, each with 00/10/20-minute backup checks from its slot.
The old 22:30–05:30 **hourly odds monitoring** remains disabled.
Daytime slots 12:00/14:00/15:00/18:00/21:00, priority
21:20/21:30/21:40 and 06:20/06:30/06:40, and 22:00
official-Final review retain their existing scheduling.

The Worker does **not** recalculate odds or injury probabilities, alter
home/away mappings, or send a second PushPlus directly. If GitHub is already
running, or its accepted marker exists, it does not dispatch. If a GitHub
workflow is green but no accepted marker exists, it does not blindly retry;
the separate GitHub health/recovery logic verifies whether sending was
actually skipped.

Cloudflare Cron and GitHub Actions workflow_dispatch are both best-effort,
not a guarantee of an exactly timed phone notification. When Worker code or
Cron configuration changes, manually rerun the deployment workflow; passing
repository CI does **not** update the deployed Cloudflare account.
