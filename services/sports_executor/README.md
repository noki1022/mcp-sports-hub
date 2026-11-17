# Independent sports execution candidate

Status: **not deployed, live execution disabled**. Current GitHub/Cloudflare
production operation remains the owner. This directory is not evidence of an
active independent server or of successful mobile delivery.

The runtime consumes the six existing, checked-in production workflow plans.
It supports only checkout/setup adapters, local immutable artifact transfer,
Bash steps, environment/output files and a bounded condition grammar. It
rejects unknown actions or syntax before running a plan. Model/source logic
is not copied into a second sports implementation.

## Deployment package

Build from the repository root:

```sh
docker build -f services/sports_executor/Dockerfile -t sports-executor .
```

The image contains pinned Python dependencies, Git, GitHub CLI, jq and zip.
Use a persistent volume at `/var/lib/sports-executor`. The Compose definition
binds HTTP only to loopback. An authenticated HTTPS ingress is required for
Cloudflare access; neither a public unauthenticated service nor an ephemeral
ChatGPT workspace is an acceptable production execution host.

Configure `GITHUB_TOKEN`, `PUSHPLUS_TOKEN`, and a randomly generated
`SPORTS_EXECUTOR_SECRET` through the host's secret mechanism, never repository
files, command arguments, URLs or chat. The GitHub token needs the existing
repository Contents/Release write capabilities used by the production plans.
`SPORTS_EXECUTOR_WARM_CACHE=1` prepares local Git objects before readiness.
The cache is fetched before each run; every execution records its code SHA.
Private logs and failed source files remain on the persistent volume.

GET `/health` reports dependency/plan readiness and the live/cutover flags.
POST `/jobs` accepts only a signed original-slot message. Its body is
`{"version":1,"route":"nba","scheduled_at_utc":"…Z"}`. HMAC-SHA256 signs
exact request bytes in `X-Sports-Signature`. Supported routes are `nba`,
`football`, `nba-review`, `football-review`, `finalizer`, and `results`.
Time must be canonical and within 120 seconds of receipt. Request bodies
cannot supply commands, environment variables, repository URLs or revisions.

The SQLite request claim is permanent across process restarts. A repeated
request, including one whose first execution failed or timed out, cannot
resend. A busy route is rejected rather than queued past its original slot.
A 202 means accepted by this execution host, never PushPlus or iPhone delivery.
The original per-slot/per-day remote send claims remain in force as well.

Before sending, original source outputs are zipped with file hashes and a
provider manifest, uploaded as immutable GitHub Release assets, downloaded
and hash-verified. Archival failure blocks the send. Final success/failure
is preserved too. Legacy numeric run IDs are explicitly labeled as independent
execution in the source/candidate/send metadata, not presented as Actions runs.
The existing original final selection and scoring rules remain unchanged.

## Cutover gate

Do not enable the external backend until all of these have been reviewed:

1. Provision a durable supported host and HTTPS ingress, verify its account,
   operating costs, secret configuration and external-source connectivity.
2. Build and start with live mode disabled. Verify `/health`, persistence,
   exact workflow compatibility and complete no-send live rehearsals on the
   deployed host, including raw readback and per-market/source coverage.
3. Adapt the production health audit and raw vault catalog to independent
   provider manifests. Their current Actions-run evidence is not an independent
   execution receipt. Validate all six routes and both review rules on the host.
4. Commit a reviewed cutover release: retire the six native schedule and
   workflow-run triggers, set `cutover.json` to the verified deployment and
   backend, and update the schedule validator to the new ownership policy.
   The server refuses activation while any of those native triggers remain.
5. Set the existing Worker `EXECUTION_BACKEND=independent`,
   `SPORTS_EXECUTOR_URL` (HTTPS origin with trailing slash), and matching
   `SPORTS_EXECUTOR_SECRET`, then enable `SPORTS_EXECUTOR_LIVE=1` on the host.
   Complete this outside an active canonical slot and verify the next original
   slots using actual provider receipts and capture timestamps.

There is no automatic fallback to a GitHub Action after external rejection,
no delayed push compensation, and no shadow second sender. A rollback changes
ownership for **future** original slots and retains every existing claim.
Never clear a claim to obtain another delivery attempt.

Current blockers: no independent deployment has been provisioned or verified;
Cloudflare GitHub login failed, and a subsequent password submission received
HTTP 403 in the cloud browser. Successful Safari login does not authenticate
this runtime or supply deployment credentials. No new paid service, access
credential, public endpoint or production ownership switch has been created.
