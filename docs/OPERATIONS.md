# Operator runbook

## Safe deployment

1. Install Python dependencies, run tests and review `ENVIRONMENT-AUDIT.md` when available.
2. Create a **new** Railway project/service for Anton; do not alter an unrelated project. Mount a persistent `/data` volume and set `ANTON_DB_PATH=/data/anton.db`. One replica. SQLite WAL, transactional claims, and append-only audit are the source of truth; memory is not.
3. Copy `.env.example` keys to Railway variables and fill secrets. Grant provider/repository permissions required for reads, branch creation and PRs, not merging/deployment. Set stable HTTPS domain; configure Datadog/Telegram/ElevenLabs webhooks only after health and authentication checks pass.
4. Configure exact SHAs, repository, base branch, regression path and unique run. `deployed_sha` must be the actually deployed `demo/buggy` SHA; `seed_regression_sha` the isolated regression commit; `known_good_sha` its **direct parent**, not necessarily latest main. Record the tagged buggy baseline separately.
5. Configure browser RUM keys and matching active run in the demo. Validate the real monitor query and latency. Do not use synthetic webhook events as live acceptance evidence.

Secrets are never returned by the operator API. Set `ANTON_OPERATOR_SECRET` as bearer authorization for every `/operator` endpoint. `scripts/operator.py` reads the secret from environment or `--env-file`; it never embeds it in arguments or prints it.

## Read state and approve nothing implicitly

```sh
python scripts/operator.py --env-file ../.env --url https://ANTON_HOST incidents
python scripts/operator.py --env-file ../.env --url https://ANTON_HOST incident INCIDENT_ID
```

The timeline records observation, proposal, actor/channel/targets, approval, action receipt, PR evidence, timeout, recovery and reset. `detected` is an event followed by `awaiting_approval`. Hotfix proceeds through investigating/verifying_pr/pr_ready; revert through preparing_revert/verifying_pr/pr_ready. `pr_ready` means a reviewable PR. Notification actions have their own outcomes and cannot erase the PR.

Only the configured responder number can be dialed. The initial pager alert and call are automatic; dispatch, revert and additional paging require explicit five-minute proposals and approval. No initial answer means Telegram remains available. Use an explicit retry-call only when the responder/operator requests it; it creates a separate audited action.

## Unknown outcomes and process restarts

Provider effects are persisted as intentions before the HTTP call. Leases expired by a crash become `unknown`, never automatically retried. Successful dispatch receipts recover incident/session links after a restart; session/check GET polling resumes. Ready state, evidence and callback/Telegram intentions are one transaction. Pending work resumes from SQLite. Telegram/API transport errors deliberately omit response bodies and credentials.

If a call/session request may have succeeded but its response was lost:

1. Inspect the provider console using run/incident/session title or timestamps. Do not create another session/call to “test”.
2. Use `reconcile` with the existing provider ID and a human-readable observation. Anton fetches the session/conversation and verifies incident metadata before recording it.
3. Unknown Telegram sends cannot be automatically found by Bot API. Inspect the configured channel and record the manual outcome using the operator tooling’s `record-outcome` command. It is evidence-based reconciliation, never resend. If the outcome cannot be established, leave unknown. A later *explicit* approved page/call is a new action, not a blind retry.
4. Provider work that completed while the run was reset is retained as an orphan receipt on the archived incident. Do not attach it to the new run; stop/close it in provider UI as appropriate.

```sh
python scripts/operator.py --env-file ../.env --url https://ANTON_HOST reconcile ACTION_ID PROVIDER_ID 'Confirmed matching incident tag in provider console'
python scripts/operator.py --env-file ../.env --url https://ANTON_HOST resume INCIDENT_ID
python scripts/operator.py --env-file ../.env --url https://ANTON_HOST retry-call INCIDENT_ID initial
```

At ten minutes without verified readiness, Anton times out and posts the live session URL. The deadline is rechecked atomically after verification; requests that crossed it cannot generate a success callback. Late results need explicit `resume`, which starts a new ten-minute window and audit event. Blocked/expired sessions are posted for human input; adjust the external session, then resume. Missing or bad PR/checks are incomplete, not success. A changed head invalidates evidence and holds a not-yet-sent callback until fresh checks pass. A failed callback preserves the verified PR and Telegram timeline.

## Changing strategy

Never switch from hotfix to revert while earlier autonomous work is active. Stop the Devin session and close any earlier PR. Reconcile all unknown/running effects. `cancel-strategy` verifies known sessions terminal and known PRs closed, invalidates old approvals, cancels pending effects, records cancellation evidence, and creates a fresh remediation branch. Then request and approve the new strategy normally. Anton does not terminate provider work or close PRs silently.

## Rehearsal reset

Reset does not reset the application or Git repository. Close superseded PRs; if a fix was actually merged/deployed, restore the buggy behavior and deploy it before a new run. Verify the flag+URL gate, tagged seed, deployed/base SHA, and recorded known-good parent. Refresh configuration when these change, restarting Anton before webhook enablement.

```sh
python scripts/operator.py --env-file ../.env --url https://ANTON_HOST reset rehearsal-002
```

Reset archives the prior run, invalidates pending approvals/effects, marks in-flight requests unknown, and changes the durable active run. Run IDs are never reused, including runs with no incident. Update Datadog payload/query and demo RUM run tag to exactly the new ID. Old delayed alerts remain audit-only. An already in-flight external request cannot be recalled by a database reset; its eventual receipt stays with the old incident and generates no new-run notification.

## Acceptance record

Two consecutive **real** complete rehearsals are still required. For each, record browser burst timestamp, webhook receive T0, call initiation/answer/brief end, explicit approval Ta, Devin receipt, exact PR head/check URLs, ready time, callback request/answer, and actual provider latency. Targets: brief <30s after answer, session <15s after approval, verified PR <5m (hard cutoff10m), callback request <30s after verification. Never claim these targets from local tests.

Also rehearse invalid secrets/allowlists, duplicate webhook/update and simultaneous voice/Telegram approvals, lost responses/restart during investigation, wrong target/missing PR/failed checks/head mutation, rollback stale SHA rejection, unanswered first call, blocked session, deadline crossing, failed callback, and delayed old-run events. Tests cover the state/controller equivalents, not provider behavior or live performance.
