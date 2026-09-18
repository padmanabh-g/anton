# Anton — Product Requirements Document

**A.N.T.O.N. — Autonomous Night-Time Operations Navigator**
*"Anton takes the 3 AM call."*

|  |  |
| --- | --- |
| Status | Hackathon MVP — AI Founders' Mindset Hackathon #001 |
| Date | September 18, 2026 |
| Venue | Datadog Japan, Tokyo |
| Stack | ElevenLabs · Twilio · Devin · Telegram · Datadog · Gemini · FastAPI on Railway |

---

## 1. Problem

Production incidents don't happen during standup. They happen at 3 AM, to one
on-call engineer, alone, staring at a phone.

The current incident-response flow is a relay race of context-switching:

1. Pager goes off → engineer wakes up, opens a laptop
2. Reads dashboards in Datadog to understand *what* broke
3. Decides *who* needs to know and pages them manually
4. Investigates the codebase, writes a fix, opens a PR — half asleep
5. Coordinates rollback/deploy over chat

Every minute of that loop is downtime, and every handoff loses context.
Observability tools tell you something is broken. Paging tools wake someone up.
**Nothing actually starts fixing the problem until a human is fully awake and
at a keyboard.** Alert fatigue means even that first step is eroding.

## 2. Solution

Anton is a **voice-first incident commander**: an AI agent that detects an
incident, *calls* the on-call engineer like a colleague would, briefs them in
plain language in under 30 seconds, and executes their spoken decisions —
including dispatching an autonomous engineer (Devin) to investigate the repo
and open a hotfix PR — before the engineer's laptop is even open.

Anton doesn't replace the human. Anton compresses the dead time between
"alert fired" and "human made one good decision" to a single phone call.

**Anton picks up the phone. Devin fixes the code.**

## 3. How it works

```javascript
Midnight Bento — anton-demo-product (demo/buggy deployment)
        │ deliberately introduced bug produces real RUM errors
        ▼
Datadog monitor fires (real RUM error spike)
        │ webhook received by standalone Anton on Railway
        │
        ├─► Telegram on-call channel: P1 alert + action buttons
        │
        └─► Anton calls the on-call engineer (ElevenLabs × Twilio PSTN)
                "Midnight Bento is rejecting valid checkout attempts.
                 Datadog detected a validation-error spike.
                 Dispatch an investigation or page the team?"
                        │
            engineer: "Dispatch a fix and page the team."
                        │
                ├─► Devin API session: investigate anton-demo-product
                │       → hotfix branch → PR against demo/buggy (live)
                └─► Telegram: team paged, Devin's live session URL posted
                        │
            Anton verifies the PR target and regression checks
                        │
            Anton calls back:
                "The checkout validation fix is ready for review.
                 The regression checks passed. The PR is in Telegram.
                 It has not been deployed."
```

The golden path ends with a verified hotfix PR and a callback. It requires
one spoken dispatch approval and two calls; review and deployment happen
after the demo. PR creation is never described as service recovery.

**Separate rollback option:** the responder may instead approve a revert PR
for the identified seeded regression commit. Anton reads back the action and
commit before accepting approval. This is an alternative to the hotfix path,
not an automatic follow-up; the revert PR also targets `demo/buggy`.

## 4. Users

| Role | Need Anton solves |
| --- | --- |
| **On-call engineer** (user) | Decide from bed; no 20-minute wake-up-to-context ramp |
| **SRE / platform team** (champion) | Faster MTTA/MTTR; alert → action in one loop |
| **VP Eng / Head of Reliability** (buyer) | Fewer sleepless engineers, fewer prolonged outages, audit trail of every incident decision |

## 5. MVP scope (tonight)

**In scope**

- Real Datadog RUM monitor on a real product, firing a webhook on a real
(harmless, feature-flagged) error burst
- Outbound PSTN call via ElevenLabs Conversational AI (Gemini brain) through
the native Twilio integration, with incident context injected as dynamic
variables
- Voice tool-calling: `dispatch_fix`, `rollback`, `page_team`
- Telegram as the pager: alert message, inline action buttons, live timeline,
Devin session URL posted for live viewing
- Live Devin session against `anton-demo-product`, starting from `demo/buggy`
and opening a hotfix PR against that branch — the hotfix PR is real code that
really fixes the bug; success callback fires only after PR verification passes
- Spoken rollback approval → real revert PR for the identified seeded
regression commit, as a separate remediation option
- Authenticated integrations, responder allowlists, durable incident/action
state, and duplicate-action prevention
- Repeatable rehearsals using a tagged buggy baseline and a separate Anton
incident reset

**Real-only policy (team rule)**
Everything shown is live: a real RUM monitor on a real product, a real
outbound PSTN call, a real Devin session fixing the real repo in real time,
real Telegram paging. The seeded bug is deliberately small (a one-line fix)
so Devin's session completes inside the demo window.

**Out of scope**

- On-call rotations/schedules, user accounts/login UI, multi-incident triage,
and escalation policies
- Automated PR merging, deployment, and recovery verification; the MVP ends
at a verified remediation PR

## 6. Architecture

| Layer | Component | Role |
| --- | --- | --- |
| Detection | Datadog RUM client SDK + RUM error-count monitor → webhook | The trigger |
| Voice | ElevenLabs Conversational AI (Gemini LLM), native Twilio import | The interface |
| Telephony | Twilio PSTN (US number, outbound) | The call |
| Workforce | Devin API (autonomous repo investigation → PR) | The hands |
| Pager | Telegram Bot API (alert + inline approval buttons) | The paper trail |
| Glue | FastAPI on Railway (persistent process, stable HTTPS URL) | Incident state machine |

### Repository responsibilities

| Repository | Responsibility |
| --- | --- |
| [`anton`](https://github.com/padmanabh-g/anton) | Standalone incident-response product: Datadog webhook ingestion, incident state, voice calls and approvals, Devin dispatch, and Telegram updates. |
| [`anton-demo-product`](https://github.com/padmanabh-g/anton-demo-product) | Midnight Bento, a demo food-ordering webapp with Datadog instrumentation and a deliberately introduced checkout bug. Its errors trigger Datadog → Anton; Devin investigates and opens remediation PRs in this repository. |

Anton receives the target repository and remediation base branch through
service configuration. `anton-demo-product` is its first connected
application, rather than a hardcoded dependency.

### Demo product: Midnight Bento

**Midnight Bento** is a late-night food-ordering webapp set in Tokyo. Its
customer-facing checkout failure gives the audience an immediately visible
reason for Anton's 3 AM call. It is the demonstration application; Anton
remains the standalone incident-response product.

Build three polished screens:

| Screen | MVP behavior |
| --- | --- |
| Menu | Six dishes with food photography, yen prices, and an “Open late” identity. Include a ¥1,000 meal for the reproducible checkout scenario. |
| Cart and checkout | Editable quantities, an order total, a clearly stated ¥1,000 minimum, and order submission with visible validation feedback. |
| Order confirmation | A persisted demo order number and order summary after a successful submission. |

The ordering flow is functional and orders are clearly labeled as demo
orders. No real payment or fulfillment occurs. Payment integration, accounts,
delivery tracking, restaurant administration, and additional seeded bugs
are outside this demo product's initial scope.

**Stage scenario:** add the ¥1,000 meal to the cart. On `demo/buggy` with the
regression enabled, checkout incorrectly displays “Minimum order is ¥1,000”
despite the cart meeting that minimum. Repeated real checkout attempts emit
RUM errors and trigger Datadog → Anton. The responder approves investigation;
Devin opens a fix PR, and checks prove that ¥1,000 succeeds while ¥999 remains
rejected. Anton reports the verified PR. The stage demo does not claim that
the deployed checkout has recovered.

### Anton deployment

- Deploy `anton` to **Railway**, either through the Railway CLI or a
GitHub-connected Railway service with autodeploy. The deployment method is
still to be selected.
- Use a stable HTTPS endpoint for integrations, Railway environment
variables for secrets, and persistent storage for incident state.
- Deployment of `anton-demo-product` is separate; its hosting provider is
still to be selected. The demo deployment tracks `demo/buggy`.

### Local development tooling

- ElevenLabs, Twilio, and Devin CLIs are already installed locally, as
confirmed by the project owner. Installed versions and authentication status
have not yet been verified.
- Use these CLIs for provider setup, configuration, and integration checks
where supported. Verify versions and authentication before relying on them.
- Anton's deployed Railway service uses provider APIs with credentials
configured in Railway; it does not depend on the developer's local CLI
installations or login sessions.

### Demo branches and rehearsal reset

- `main` in `anton-demo-product` holds the working demo app.
- `demo/buggy` contains a known, deliberately small regression and powers
the demo deployment. Tag the original buggy commit as the repeatable baseline.
- Devin creates a new fix branch from `demo/buggy` for each run and opens
its PR **against `demo/buggy`**, leaving `main` unaffected.
- If a run ends with an open PR, the deployed regression remains available
for the next rehearsal. Close superseded rehearsal PRs before starting again.
- If the fix is merged and deployed, revert the fix merge and redeploy
`demo/buggy` to restore the regression. Verify it matches the tagged baseline's
intended faulty behavior.
- Reset Anton's incident state separately for each rehearsal. Invalidate old
approvals and pending callbacks, and scope duplicate-alert tracking to the
new run so delayed events from earlier runs cannot affect it.
- Before the next run, verify the deployed branch, reproduce the bug, and
confirm Datadog monitoring is ready to generate a fresh alert transition.

Opening a hotfix or revert PR does not itself deploy a change or establish
service recovery. The stage demo ends at a verified PR; merging, deployment,
and recovery verification are outside the MVP.

### Seeded incident and rollback target

- Seed a checkout-validation regression: a cart at the ¥1,000 minimum total
is incorrectly rejected because an inclusive boundary comparison was changed
to an exclusive comparison. Keep the regression in one isolated, non-merge
commit with no unrelated changes; the intended fix is one line.
- Gate the regression to the isolated demo environment and `?demo=broken`.
Emit a real RUM error on failed checkout, tagged with service, environment,
application version, and rehearsal run ID.
- Configure a RUM error-count monitor scoped to this validation error, demo
environment, and active run: at least five errors within one minute. Record
the deployed query and measured alert latency in the rehearsal runbook.
Report an error count, not an invented payment error rate.
- Give Devin the observed error, reproduction steps, repository, deployed
SHA, base branch, and validation command. Voice briefs report observations;
root-cause claims require investigation evidence.
- Record `seed_regression_sha`, `known_good_sha`, and the deployed SHA in
service configuration alongside the tagged buggy baseline.
- `rollback` opens a PR reverting `seed_regression_sha` on the recorded
`demo/buggy` head. Verify that the deployed SHA matches that head, the target
commit is in its history, and its regression remains present. Reject stale
targets, revert conflicts, or already-reverted changes for manual review.
- Bind approval to the action, target SHA, and base SHA. A changed base
requires a fresh proposal and approval. Refresh these values when a rehearsal
reintroduces the regression. Do not merge or deploy the resulting revert PR.

### Integration authentication and approvals

- Authenticate Datadog webhook and ElevenLabs tool requests using configured
integration secrets; validate provider signatures wherever supported. Validate
Telegram's configured webhook secret and allowlist both chat and acting user
IDs. Reject unauthorized requests before creating work.
- Call only the configured responder number. Bind tool requests to the
server-recorded conversation, responder, incident, and run; an LLM-supplied
incident ID alone never authorizes an action.
- Require explicit approval for `dispatch_fix`, `rollback`, and `page_team`.
Approval covers only the named actions and records actor, channel, timestamp,
targets, and a single-use token expiring after five minutes. Ambiguous speech
requires clarification before execution. The initial configured pager alert
does not require approval; additional team paging does.
- Voice and Telegram use the same action handler. Repeated approvals return
the existing action result. Repository and branch targets come from server
configuration, not arbitrary tool arguments.
- Keep credentials in Railway environment variables, redact them from logs
and agent context, and restrict repository access to branch/PR creation needs.
The operator reset endpoint also requires authentication.

### Durable incident and action lifecycle

- Persist incidents, approvals, event receipts, provider IDs, and pending
work in a database on persistent storage. Record run ID, monitor/group, alert
occurrence, repository/base/deployed SHAs, timestamps, call IDs, Devin session
ID, PR URL/head SHA, check evidence, and an append-only event timeline.
- Hotfix states: `detected → awaiting_approval → investigating → verifying_pr
→ pr_ready`. Rollback states: `awaiting_approval → preparing_revert →
verifying_pr → pr_ready`. `pr_ready` means reviewable remediation, not recovery.
- Record `blocked`, `failed`, `timed_out`, and `cancelled` outcomes explicitly.
Resumption requires an explicit operator action. Record monitor recovery
separately without attributing it to an undeployed PR.
- Track calls, paging, dispatch, PR creation, and result notification as
separate actions with `pending`, `running`, `succeeded`, `failed`, or `unknown`
status. Notification failure does not erase a verified PR result.
- Deduplicate provider event IDs and correlate repeated alerts by run,
monitor/group, and alert occurrence. Recovery closes the alert occurrence;
a later alert may create a new incident. Monitor ID alone is not a dedup key.
- Use transactional action claims and unique incident/action keys to prevent
concurrent voice/Telegram approvals from creating duplicate work. Allow one
active remediation strategy per incident. Switching strategies requires
explicit cancellation and reconciliation of the earlier work.
- Persist intended work before external calls and save provider IDs promptly.
Reuse provider idempotency keys where supported. When an API request might
have succeeded but its response was lost, mark the action `unknown` and
reconcile with the provider. Do not blindly recreate calls, sessions, or PRs;
if reconciliation cannot establish the result, require operator review.
- On restart, reclaim expired work leases, reconcile unfinished actions,
resume session/check polling, and deliver pending notifications. Process
memory and the single-instance setting are not the source of truth.
- Reset archives the prior incident and invalidates its pending approvals
and actions. Delayed events remain associated with the old run for audit
and cannot trigger work in the new run.

### PR verification and failure behavior

- Pin the Devin API version during implementation. Poll session state and
PR metadata; session completion alone does not establish PR readiness.
- Verify through GitHub that the PR is open, non-draft, in the configured
repository (`anton-demo-product` for this demo), targets `demo/buggy`, and
comes from the recorded remediation branch. Record its current head SHA.
- Require passing regression checks on that exact SHA: a ¥1,000 cart
succeeds, a ¥999 cart remains rejected, and the normal checkout path
still works. First demonstrate that the boundary check fails on the buggy
baseline. Reject changes that merely disable checkout or error reporting.
- Attach reproduction, change summary, and check evidence to the PR and
Telegram timeline. A changed head invalidates verification until checks pass
again. Apply this gate to both hotfix and revert PRs.
- Missing PR, wrong target, missing evidence, or failed checks means no
success callback. Post the specific incomplete or failed state to Telegram.
- Report blocked sessions with the input needed and failed sessions with
their reason. Apply a ten-minute dispatch-to-verified-PR deadline for the
demo; on expiry, mark the attempt timed out and post its live link. Late
results require explicit operator resumption before a success notification.
- If the first call is unanswered or fails, keep the authenticated Telegram
actions available; do not dispatch without approval. If the result call fails,
preserve the PR and post its result in Telegram. Retry calls only on an explicit
responder/operator request, recorded as a separate action.

## 7. Success metrics

**Tonight (hackathon)**

- The phone rings live on stage.
- Devin is dispatched only after approval; target approval-to-session creation
is under 15 seconds, measured during rehearsal. The room watches the live session.
- The callback is requested within 30 seconds of PR verification passing.
- Dispatch-to-verified-PR target is under five minutes, with a ten-minute
timeout. These are rehearsal targets, not guaranteed provider latencies.
- All three tool partners + host visibly used in the golden path.

**As a product (post-hackathon)**

- MTTA (acknowledge): minutes → **seconds**
- Time-to-first-action (rollback/fix dispatched): target < 2 min from alert
- % of incidents where first remediation starts before human opens a laptop
- Approval comprehension and responder confidence as trust measures;
false-page rate as a health metric
- Track alert-to-approval, approval-to-dispatch, dispatch-to-verified-PR, and
verification-to-callback separately. MTTR requires deployed recovery evidence
and cannot be inferred from this PR-only MVP.

### Stage timeline and rehearsal acceptance

1. Before the pitch, verify credentials, responder handset, Telegram allowlist,
repository access, tagged baseline, rollback SHAs, and deployed monitor query.
Reset the prior run and confirm the monitor is ready for a fresh alert.
2. Generate real demo traffic using the lead time measured in rehearsal.
Define `T0` as Anton receiving the authenticated Datadog alert, not pitch start.
Record bug-to-alert latency separately.
3. At `T0`, persist the incident and initiate Telegram notification and the
call. Deliver the brief within 30 seconds of the responder answering.
4. At `Ta`, record explicit approval. Target confirmed Devin session creation
by `Ta + 15 seconds`; post its live URL. Never pre-dispatch to satisfy timing.
5. Show live investigation. Target verified PR readiness within five minutes
of dispatch, then request the callback within 30 seconds. At ten minutes,
report timeout honestly if verification has not passed.

Rehearsal acceptance requires two consecutive complete live runs. Record
actual timestamps and provider delays; missing a target calls for adjustment
of scope or stage pacing, never a fabricated success result. Also verify:

- Duplicate alerts and simultaneous voice/Telegram approval create one
remediation action; invalid credentials and expired approvals create none.
- Restart during investigation preserves the incident and resumes polling
without a second Devin session or duplicate callback.
- Missing/wrong-target PRs, failed checks, and changed PR heads cannot pass
the verification gate. A valid PR produces the correct callback and timeline.
- The separate rollback path targets the configured regression commit and
rejects stale targets; its PR passes the same verification gate.
- Unanswered calls, blocked/timed-out sessions, and failed result calls produce
the specified Telegram status without unauthorized or duplicate work.
- Rehearsal reset isolates delayed events from earlier runs.

## 8. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Datadog monitor evaluation lag (2–5 min) | Measure ingestion/evaluation lag during rehearsal and schedule the real error burst accordingly; do not assume a precise stage alert time |
| Devin session exceeds the demo window | Seed a small regression; dispatch after approval; show the live session and report timeout honestly if the PR misses the window |
| Twilio trial restrictions | Verified caller ID set up in advance; US number (no JP ID docs needed) |
| Telegram-as-call-channel considered | Rejected: MTProto = userbot, behavioral ban risk, no PSTN. Telegram stays pager-only |
| Demo bug affects real users | Isolated demo deployment from `demo/buggy`, with `?demo=broken` gating the seeded regression; `main` remains the working app. |
| Rehearsals leave stale fixes or incident actions | Tagged buggy baseline, restore the regression after merged fixes, and reset Anton's incident state before each run. |
| Backend availability mid-demo | One Railway instance with persistent incident/action state and restart reconciliation; local consumers off once Railway is live |
