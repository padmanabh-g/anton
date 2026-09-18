from fastapi.testclient import TestClient

from anton.api import create_app
from anton.config import Settings


def client(tmp_path):
    return TestClient(
        create_app(
            Settings(
                db_path=str(tmp_path / "api.db"),
                run_id="r",
                deployed_sha="a" * 40,
                datadog_secret="dd",
                voice_secret="voice",
                telegram_secret="tg",
                telegram_chat_id="1",
                telegram_user_ids="2",
                operator_secret="op",
                worker_enabled="false",
            )
        )
    )


def test_unauthorized_creates_nothing(tmp_path):
    with client(tmp_path) as c:
        assert c.post("/webhooks/datadog", json={}).status_code == 401
        assert (
            c.post(
                "/webhooks/telegram",
                json={},
                headers={"X-Telegram-Bot-Api-Secret-Token": "bad"},
            ).status_code
            == 401
        )
        assert (
            c.get("/operator/incidents", headers={"Authorization": "Bearer op"}).json()
            == []
        )


def test_voice_spoofing_rejected(tmp_path):
    with client(tmp_path) as c:
        r = c.post(
            "/voice/propose",
            headers={"X-Anton-Secret": "voice"},
            json={
                "conversation_id": "made-up",
                "run_id": "r",
                "action": "dispatch_fix",
            },
        )
        assert r.status_code == 409


def test_telegram_actor_chat_allowlist(tmp_path):
    with client(tmp_path) as c:
        body = {
            "update_id": 1,
            "callback_query": {
                "id": "x",
                "from": {"id": 9},
                "message": {"chat": {"id": 1}},
                "data": "p:x:dispatch_fix",
            },
        }
        assert (
            c.post(
                "/webhooks/telegram",
                headers={"X-Telegram-Bot-Api-Secret-Token": "tg"},
                json=body,
            ).status_code
            == 403
        )


def test_cancellation_discovers_open_unverified_pr_by_branch(tmp_path):
    with client(tmp_path) as c:
        db = c.app.state.db
        i = db.ingest(
            {
                "event_id": "e",
                "run_id": "r",
                "monitor_id": "m",
                "group": "g",
                "occurrence": "o",
                "status": "Triggered",
                "deployed_sha": "a" * 40,
            }
        )
        proposal = db.propose(i["id"], "dispatch_fix", "2", "telegram")
        action = db.approve(proposal["token"], "2", "telegram")
        db.complete(action["id"], {"session_id": "s"})
        db.update_incident(i["id"], session_id="s", state="verifying_pr")

        async def session(id):
            return {"status_enum": "finished"}

        async def github(path):
            assert "/pulls?state=open&head=" in path
            return [{"number": 1, "state": "open"}]

        c.app.state.providers.session = session
        c.app.state.providers.gh = github
        response = c.post(
            "/operator/incidents/" + i["id"] + "/cancel-strategy",
            headers={"Authorization": "Bearer op"},
            json={"evidence": "Provider session is terminal but checks are queued"},
        )
        assert response.status_code == 409
        assert db.incident(i["id"])["strategy"] == "dispatch_fix"


def test_manual_unknown_outcome_is_audited_and_does_not_retry(tmp_path):
    with client(tmp_path) as c:
        db = c.app.state.db
        i = db.ingest(
            {
                "event_id": "e",
                "run_id": "r",
                "monitor_id": "m",
                "group": "g",
                "occurrence": "o",
                "status": "alert",
                "deployed_sha": "a" * 40,
            }
        )
        action = db.claim()
        db.complete(action["id"], {"reason": "response lost"}, "unknown")
        response = c.post(
            "/operator/actions/" + action["id"] + "/record-outcome",
            headers={"Authorization": "Bearer op"},
            json={
                "status": "succeeded",
                "evidence": "Confirmed message visible in configured group at incident time",
            },
        )
        assert response.status_code == 200
        assert db.action(action["id"])["status"] == "succeeded"
        assert db.timeline(i["id"])[-1]["kind"] == "manual_reconciliation"
