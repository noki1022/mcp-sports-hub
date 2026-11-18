# Cloudflare-only readiness candidate

This package adapts the independent executor to the user's existing Cloudflare
account. It is **not deployed** and not ready for production ownership. The
current scheduler's configuration and the GitHub cutover gate stay unchanged.

## Prepared staging deployment

- Separate Worker: `noki-sports-independent-executor`.
- Maximum one `basic` container (1/4 vCPU, 1 GiB memory, 4 GB ephemeral disk).
- Durable Object `SportsExecutor` with SQLite-backed storage.
- No cron triggers on this new service. `SPORTS_EXECUTOR_LIVE=0`.
- Authenticated GET `/health` only. The deployment workflow generates a
  probe-only key inside Actions and sets it through Wrangler stdin. It is not
  printed or returned, and is not a business execution credential.
- No PushPlus token or GitHub write token is passed in this staging workflow.
- The staging container sleeps after two minutes of inactivity.

The manual workflow `Cloudflare executor readiness-only deployment (paid
resources)` is restricted to `main` and requires the explicit paid-resource
acknowledgment. It also requires `CLOUDFLARE_API_TOKEN` in GitHub repository
secrets. Set that through the service's secret UI, never paste the token into
chat or repository files. It needs the selected account's deployment access
for the Worker, container and Durable Object resources. No global API key or
other account's credential is required.

A successful run must save the actual provider-returned deployment URL and a
health result proving `ready=true`, `live_enabled=false`,
`cutover_ready=false`, `claim_owner=cloudflare_durable_object`, and no pending
jobs. A successful CLI exit alone is insufficient. Deployment provisioning may
precede runtime readiness, so the bounded verifier repeats health reads only.
It never calls POST `/jobs`, collects odds or sends a notification.

## Permanent execution ownership

The Durable Object reserves the original route/time before forwarding once.
The reservation survives a container or Durable Object process restart.
Unknown outcomes remain claimed. Alarm handlers only read execution state;
they never re-post a job or start a stopped container. Production configuration
would keep the one container warm across the existing 25/50-minute ticks;
staging has no such scheduled work. The Python SQLite ledger is secondary in
this deployment, not evidence of persistent container disk.

The scheduler bridge supports a private Service Binding named
`SPORTS_EXECUTOR`. The existing scheduler's binding must only be configured
after the target service exists and the production cutover is approved. No
binding to a nonexistent service has been added to the current scheduler.

## Remaining production gates

1. Paid-resource authorization and usable scoped deployment credential.
2. Real Cloudflare readiness and source-connectivity rehearsal evidence.
3. Durable raw-source/failure-spool protection for ephemeral-container loss;
   before-send and final readback-verified GitHub archives alone do not protect
   a process that dies before its archival hook. No production switch before
   this is addressed and tested.
4. Independent-provider health/vault catalog support and bounded disk cleanup.
5. Approved removal of original GitHub execution triggers in the same cutover
   release, plus verified live credentials and next-slot acceptance evidence.

Cloudflare Containers require Workers Paid. The published plan includes a
USD 5/month Workers base charge with additional resource usage as applicable.
The account's existing plan is unverified. This candidate creates no paid
subscription, billing commitment or running resource merely by being merged.

Official references checked 2026-11-18:
- https://developers.cloudflare.com/containers/platform/pricing/
- https://developers.cloudflare.com/containers/platform/limits/
- https://developers.cloudflare.com/containers/faq/
- https://developers.cloudflare.com/containers/api/durable-object-container/
