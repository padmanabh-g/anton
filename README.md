# Anton

Autonomous Night-Time Operations Navigator. A standalone FastAPI incident commander that receives authenticated Datadog alerts, calls the configured responder through ElevenLabs’ native Twilio integration, records explicit voice/Telegram approval, dispatches Devin, and verifies a real remediation PR before calling back.

**The endpoint is a verified PR for human review. Anton never merges, deploys, or claims service recovery.** The target repository and branch are configuration, defaulting to `padmanabh-g/anton-demo-product` / `demo/buggy`.

## Run

```sh
python3 -m venv .venv
.venv/bin/pip install --constraint requirements.lock -e '.[dev]'
cp .env.example ../.env
# Fill ../.env; local DB path should be ./data/anton.db
.venv/bin/uvicorn anton.main:app --env-file ../.env --port 8000 --no-access-log
```

There is no production mock mode. Missing provider configuration fails closed; tests use injected fakes solely within `tests/`. To inspect API locally without starting the outbox worker, set `ANTON_WORKER_ENABLED=false`. `/docs` contains the OpenAPI surface; operator endpoints require a bearer secret.

```sh
.venv/bin/python -m pytest -q
```

Deployment: Dockerfile + `railway.toml`. Create a Railway service for this repository, attach a persistent volume at `/data`, set all required environment variables, one replica and stable HTTPS hostname. Do not run local and deployed workers against separate databases for the same monitor. `/health` checks process availability, not provider credentials or production readiness. Deployment has not been performed by this implementation.

See [integration configuration](docs/INTEGRATIONS.md), [operator runbook](docs/OPERATIONS.md), [implementation report](docs/IMPLEMENTATION-REPORT.md), and [PRD](PRD.md).
