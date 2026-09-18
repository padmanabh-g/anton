# Environment audit — 2026-09-18

No full credentials were printed or saved in this report. Provider login state is distinct from deployment-ready API credentials.

| Tool | Version | Read-only result |
| --- | --- | --- |
| git | 2.50.1 | Both SSH origins accessible; both initially empty |
| GitHub CLI | 2.88.1 | Two local accounts authenticated; neither has Anton API access or demo push permission |
| Node | 22.22.0 | Available |
| pnpm | 10.33.0 | Selected package manager |
| bun | 1.3.14 | Available |
| Python | 3.14.6 | Available; project runtime pinned separately |
| uv | 0.10.7 | Available |
| Railway | 4.26.0 | Account authenticated; no existing Anton-named project found |
| ElevenLabs | 0.4.3 | CLI stored login verified; subsequently supplied local .env API key passed read-only /v1/user |
| Twilio | 6.2.4 | Active profile; read-only accounts API returned valid account data. CLI returned exit 70 despite successful JSON, so exit status alone is unreliable |
| Devin | 3000.10.31 | CLI reports authenticated Max account; subsequently supplied local .env key passed read-only v1 sessions endpoint |
| Wrangler | — | No global binary found; use project pnpm dependency |

Initially no Datadog, ElevenLabs, Twilio, Devin, Telegram, GitHub-token or Cloudflare credential variables were exported to this process. Existing CLI logins are not copied into Railway or sent to agents. The user subsequently populated the local workspace .env with ElevenLabs and Telegram API credentials; both authenticated read-only requests. A subsequently supplied Devin API key also passed the read-only v1 sessions endpoint. ElevenLabs lists no agents or phone numbers yet. The Telegram helper discovered chat/user IDs and generated a webhook secret directly in .env without printing it.

## Setup still needed for live acceptance

- Approved credentials/config source and repository-scoped GitHub API credential.
- Dedicated Railway service with stable HTTPS and persistent volume mounted at the configured database path.
- ElevenLabs agent using Gemini, native imported Twilio number, configured responder E.164 number, authenticated tools with system conversation binding.
- Telegram bot, private on-call chat and allowed acting user IDs; HTTPS webhook with secret.
- Devin API key and repository connection; establish v1 access before relying on the adapter.
- Cloudflare demo deployment tracking `demo/buggy`, public Datadog RUM application/client token, active run ID and deployed SHA.
- Real Datadog RUM count monitor, scoped to active rehearsal, five validation errors in one minute; authenticated normalized webhook.
- Two consecutive real rehearsals and measured timings. No live calls, messages, Devin sessions, monitor firing, or recovery have been claimed by this implementation session.

## Integration documentation verified

- [ElevenLabs native outbound API](https://elevenlabs.io/docs/api-reference/integrations/twilio/outbound-call)
- [ElevenLabs dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables)
- [Devin v1 create](https://docs.devin.ai/api-reference/v1/sessions/create-a-new-devin-session) and [retrieve](https://docs.devin.ai/api-reference/v1/sessions/retrieve-details-about-an-existing-session): intentionally pin legacy v1; CLI authentication does not establish API access.
- [Datadog webhook integration](https://docs.datadoghq.com/integrations/webhooks/) and [RUM monitors](https://docs.datadoghq.com/monitors/types/real_user_monitoring/).
