# Integration configuration

Use `.env.example` as the complete configuration list. Railway variables are the production source; local Uvicorn `--env-file ../.env` loads the workspace secrets file. Keep the database and secrets private. Do not enable request/body or HTTP client debug logging: Telegram bot tokens are embedded in its API URL.

## Datadog

POST `/webhooks/datadog` with `X-Anton-Secret: <ANTON_DATADOG_SECRET>`. Body:

```json
{
  "event_id": "provider-event-id",
  "run_id": "rehearsal-001",
  "monitor_id": "monitor-id",
  "group": "env:demo,service:midnight-bento",
  "occurrence": "alert-cycle-key",
  "status": "alert",
  "deployed_sha": "40-character-deployed-commit-sha",
  "error_count": null
}
```

`event_id` maps to `$ID`, monitor to `$ALERT_ID`, group to `$ALERT_SCOPE`, occurrence to `$ALERT_CYCLE_KEY`. Use immutable active run/deployment values in each webhook integration payload. Set status to native `$ALERT_TRANSITION`; Anton accepts Triggered/Re-Triggered/Renotify as alert and Recovered as recovered. Normalized `alert` and `recovered` values also work. Configure monitor notifications for alert and recovery. Do not invent counts: omit `error_count` unless measured. Five is the threshold, not necessarily the observed count.

The monitor query must scope `service:midnight-bento`, `env:demo`, active `run_id`, and `CheckoutValidationError` / `error_code:checkout_minimum`. PRD asks >=5 errors within one minute. RUM-specific monitor docs currently describe a minimum five-minute window, unlike generic monitor docs. Validate the actual one-minute query through the Datadog API; this is an unresolved acceptance constraint until validated. Do not silently substitute a five-minute monitor or claim one-minute latency. Record deployed query, provider acceptance, and measured burst-to-alert latency.

A new occurrence may create a new incident; a recovery closes that occurrence without claiming an undeployed PR caused recovery. Delayed recovery or alert events retain old run IDs and cannot create new-run work.

## Telegram

Create the bot with BotFather and add it to the configured pager group. Set `ANTON_TELEGRAM_CHAT_ID`, comma-separated exact numeric `ANTON_TELEGRAM_USER_IDS`, token, and a random webhook secret. Configure Bot API `setWebhook` to `https://HOST/webhooks/telegram` with `secret_token`, `allowed_updates:["callback_query"]`. This changes external configuration and should be performed only when the public service is ready.

Initial alert buttons request an actor-bound proposal. Anton sends the action/target readback and a second explicit approval button, expiring in five minutes. Only the same allowlisted user may consume it. Additional team paging is a separately approved action; the configured initial pager alert does not require approval. Telegram has no API to recover a lost sendMessage response by idempotency key; those actions remain `unknown` for operator review rather than being resent.

## ElevenLabs and Twilio

Import the Twilio number into ElevenLabs; select the Gemini conversational model and configure the agent/phone number IDs. `ANTON_RESPONDER_NUMBER` is the sole outbound destination. Native endpoint: `POST https://api.elevenlabs.io/v1/convai/twilio/outbound-call`, `xi-api-key`; request includes agent/phone IDs, destination and dynamic variables. Provider response `conversation_id` and `callSid` establish server-side call bindings. There is no alternative TwiML bridge or simulated call.

Agent system prompt:

> You are Anton, the incident commander. On an initial call, prepare dispatch_fix and page_team proposals before asking for approval; preparing does not execute either action. Brief the responder in under 30 seconds using incident_summary. Observations are not a root cause. Read a combined plain-language proposal: investigate the checkout issue and open a PR for human review without deployment, and separately page the configured team in Telegram. Ask which named actions the responder approves. A single clear utterance such as “Dispatch a fix and page the team” approves both already-read actions: consume each separate token with approve_action, without another spoken confirmation. If only one action is named, consume only its token. Ambiguous speech means clarify before consuming any token. If a token expires, prepare and read back a fresh proposal before requesting fresh approval. Rollback is an alternative requested separately: prepare its proposal on request, read the revert action, seed SHA and base SHA, then require explicit confirmation of that readback. Never pair rollback with fix dispatch. Never claim a PR is deployed or that the service recovered. On result calls explain that the verified PR is ready for human review, has not been deployed, and is in Telegram. Never ask for or expose integration credentials.

Configure server tools:

1. `dispatch_fix`, `rollback`, `page_team` map to POST `/voice/propose`, with corresponding constant `action`; inject `conversation_id` from provider **system** `system__conversation_id`, `run_id` from initiation data. The LLM must not choose these identity values. Secret `X-Anton-Secret` is a server tool header, never an LLM prompt/dynamic variable.
2. `approve_action` POST `/voice/approve`, same system conversation/run binding, returned `token`, `confirmed:true` only after an explicit spoken confirmation of the readback. The initial two proposals have independent tokens: a single utterance explicitly naming both permits two tool calls, while naming just one permits only its token. Proposal creation alone never dispatches or pages. It consumes the approval; retries return its existing action.
3. Do not expose operator endpoints as voice tools. New calls cannot consume another conversation’s token, even for the same responder.

Configure signed post-call webhooks at `/webhooks/elevenlabs`; set `ANTON_ELEVENLABS_WEBHOOK_SECRET`. HMAC `ElevenLabs-Signature` timestamp (five-minute skew limit) and v0 digest are checked before recording any event. Failed/unanswered calls do not dispatch and are never automatically retried. Verify native call-failure payload on a real rehearsal: some failures do not allocate a conversation and must be reconciled in the provider console.

Official reference: https://elevenlabs.io/docs/api-reference/integrations/twilio/outbound-call

## Devin and GitHub

Pinned to legacy **Devin API v1**: POST `/v1/sessions`, GET `/v1/sessions/{session_id}`. Confirm the account has v1 entitlement before rehearsal. Stable incident prompt with `idempotent:true`, incident/run tags, explicit repository/base/branch, and a ten-ACU ceiling. This idempotency hint is not a reason to blindly retry a lost response. `session_id` and URL are persisted, and polling uses `status_enum` and `pull_request.url`.

Devin v1 officially accepts `structured_output_schema` in session creation and exposes `structured_output` in session retrieval. The actual request schema is [config/devin-structured-output.schema.json](../config/devin-structured-output.schema.json): an object with required bounded string fields `input_needed`, `failure_reason`, `change_summary`, and `validation_summary` (empty when unknown). The prompt asks Devin to maintain factual progress and specific blockers without credentials or logs. Anton records/displays only these fields after bounds, credential redaction and URL/private-key removal. Blocked/expired outcomes include the specific supplied input/reason and progress in the audit and Telegram; omitted details are identified as not supplied with the live session link. Readiness still depends exclusively on the independent GitHub gate, never a provider claim of passing checks. See [create-session schema](https://docs.devin.ai/api-reference/v1/sessions/create-a-new-devin-session) and [session output](https://docs.devin.ai/api-reference/v1/sessions/retrieve-details-about-an-existing-session).

Both fix and rollback use Devin. Rollback is independently guarded: deployed SHA equals remote base; seed has exactly one parent equal to known-good SHA; one changed validation line only; seed is in base history; current validation blob equals seeded blob and differs from known-good. Devin must run `git revert` and open the PR. The PR gate then checks its blob equals the known-good blob. Any conflict or changed base blocks.

GitHub gate requires open/non-draft PR, configured repository and base, the recorded remediation branch, unchanged deployment base, only one validation line changed, and GitHub Actions app ID `15368` check `checkout-regression` successful on the **exact head SHA**. Head/state/target/base are read again after evidence collection. CI/tests/RUM edits cannot pass the gate. The configured regression path is `src/lib/checkout.ts`.

The demo workflow must execute `pnpm test:checkout`. If a PR created with GitHub’s workflow token suppresses Actions, explicitly dispatch its workflow on the remediation branch. Never attach passing checks from another SHA. Keep Devin’s repository integration restricted to the demo repository and branch/PR creation permissions; no merge/deploy permissions.

Official pinned API reference: https://docs.devin.ai/api-reference/v1/sessions/create-a-new-devin-session
