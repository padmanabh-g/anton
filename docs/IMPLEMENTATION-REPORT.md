# Anton implementation report

Implemented locally; no production calls, Devin sessions, Telegram sends, GitHub pushes or deployments were made by backend implementation. Live rehearsal acceptance remains unverified.

## Implemented

- FastAPI endpoints: authenticated Datadog, Telegram and voice tools; timestamped ElevenLabs webhook HMAC; bearer-authenticated operator inspection/reset/resume/reconciliation/cancellation/call retry. Chat and acting user allowlists; voice approvals bound to exact server-recorded conversation, responder, incident and run.
- SQLite WAL, persistent schema, incident/action state, append-only event triggers, durable event receipts, unique run history and recovered occurrence tombstones. Transactional approval consumption/claims prevents concurrent duplicate remediation; server config owns repository/base/SHAs. Five-minute actor/channel/target-bound proposals; separate team-page approval.
- Concurrent outbox execution persists intent before effects; uncertain API outcomes/expired leases become unknown without blind retry. Provider receipts retained through reset; dispatch receipt-to-incident recovery closes restart gap. Pending notifications and session/check polling recover. Provider calls/session links are real adapters, never production fakes.
- Native ElevenLabs/Twilio outbound endpoint with fixed responder destination and dynamic context; pinned legacy Devin v1 stable idempotent prompt, explicit base/branch, constrained one-line remediation and validation instructions. Ten-minute deadline with post-verification atomic check; late results require operator resume.
- Rollback through a real Devin session running git revert; independent preflight verifies exact deployed/base, isolated non-merge seed and direct known-good parent, ancestry and unchanged regression blob. Same PR gate additionally requires resulting blob matches known-good.
- GitHub gate checks open/non-draft/repository/base/recorded branch, unchanged deployment base, only one approved validation-file line changed, trusted Actions check `checkout-regression` on exact head. Rechecks full PR identity/state and base after collecting evidence. Invalid evidence prevents callback; changed heads invalidate readiness. Ready evidence and notification intents commit atomically. Failed result calls preserve verified PR. Held callbacks do not redial before successful re-verification.
- Strategy cancellation requires reconciliation, known provider session terminal, no open PR on recorded branch, invalidates approvals and pending/held work, and generates fresh remediation branch. Poll mutations are fenced to run/branch/session so earlier async results cannot mark a newer attempt ready.
- Dockerfile, Railway one-replica/health configuration, complete environment example, integration/runbook documentation and authenticated CLI operator tools.

## Verification

Critical tests cover concurrent duplicate alerts/approvals, actor mismatch, expiration/reset isolation, recovery-before-delayed-alert, unique run IDs, audit immutability, unknown lease preservation, voice binding, API authorization/allowlists, wrong-target/draft/wrong branch/untrusted exact-head checks, PR state race, rollback safeguards, restart polling and one callback, timeout/resume and verification crossing deadline, unknown dispatch/no retry, reset during dispatch receipt retention, restart after persisted receipt, cancellation fencing, failed callback preserving PR, changed-check callback hold, and Telegram proposal replay.

Run `.venv/bin/python -m pytest -q` for current evidence; final handoff records the actual count. Test fakes are under `tests/` only. No integration test result implies provider credentials, latency, or production setup are valid. The runtime dependency constraints are pinned in requirements.lock. Installed FastAPI/Starlette emits two test-client deprecation warnings with httpx; application tests pass. Python 3.14 was tested locally; Python 3.12 container execution remains unverified.

## Remaining live setup and limitations

- Fill local secret file / Railway variables; verify account scopes and legacy Devin v1 entitlement. Local CLI login does not supply Railway runtime keys.
- Publish repositories/branches/workflow, deploy demo and Anton, mount durable Railway volume, configure stable endpoint, agent model/tools/Twilio number, webhook secrets and Telegram allowlist. Set actual deployed/seed/known-good SHAs.
- Validate Datadog RUM one-minute monitor requirement against real API. RUM-specific docs’ five-minute minimum conflicts with the requested one-minute window; no monitor is claimed configured or accepted.
- Telegram sendMessage has no reliable idempotent reconciliation query. Lost responses require channel inspection and an explicit manual outcome record; unknown is retained if unprovable. A reset cannot cancel an HTTP request already in flight; returned effects remain in old-run audit and may require provider-console cleanup.
- GitHub readiness is a point-in-time check; callbacks revalidate immediately before calling. External repository changes can still occur after the final read, as with any non-locking provider API. Anton does not hold repository locks or merge anything.
- GitHub missing/queued/failing checks need CI completion; dispatch workflow manually on recorded branch if token-created PR suppressed Actions. No unverified “passed” status is manufactured.
- Speech clarity depends on correctly configured ElevenLabs server tools and agent prompt. The server enforces explicit proposal/confirmation protocol and system conversation identity; it does not independently transcribe or classify audio.
- Provider read failures retry safely; mutating failures do not. A provider may need manual input or cleanup; cancellation does not silently terminate external work. Unknown outcomes intentionally trade unattended completion for avoiding duplicate real effects.
- Two consecutive real runs, rollback rehearsal, unanswered/failed-call paths, and timing evidence are required before claiming PRD stage acceptance. None has been fabricated.
