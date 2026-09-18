import asyncio
import json
import time

from test_core import alert

from anton.providers import NotReady, UnknownOutcome
from anton.worker import Worker


class Fake:
    def __init__(self):
        self.calls = []
        self.sessions = []
        self.messages = []
        self.ready = False

    async def call(self, i, purpose):
        self.calls.append(purpose)
        return {"conversation_id": "c", "call_sid": "sid", "purpose": purpose}

    async def telegram(self, text, buttons=None):
        self.messages.append(text)
        return {"message_id": 1}

    async def dispatch(self, i, rollback=False, can_execute=None):
        self.sessions.append(i["id"])
        return {"session_id": "s", "session_url": "https://app.devin.ai/s"}

    async def session(self, id):
        return {
            "status_enum": "finished",
            "pull_request": {
                "url": "https://github.com/padmanabh-g/anton-demo-product/pull/1"
            },
        }

    def pr_number(self, url):
        return 1

    async def verify_pr(self, i, number):
        if not self.ready:
            raise NotReady("Checks pending")
        return {
            "head": "c" * 40,
            "url": "https://github.com/padmanabh-g/anton-demo-product/pull/1",
            "number": 1,
            "checks": [],
        }


async def drain(w):
    while a := w.db.claim():
        await w.execute(a)


def dispatch(db):
    i = alert(db)
    p = db.propose(i["id"], "dispatch_fix", "42", "telegram")
    db.approve(p["token"], "42", "telegram")
    return i


def test_restart_polling_and_exactly_one_callback(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))
    assert len(p.sessions) == 1
    asyncio.run(Worker(db, p).poll(db.incident(i["id"])))
    assert db.incident(i["id"])["state"] == "verifying_pr"
    assert p.calls == ["initial"]
    p.ready = True
    asyncio.run(w.poll(db.incident(i["id"])))
    asyncio.run(w.poll(db.incident(i["id"])))
    asyncio.run(drain(w))
    assert db.incident(i["id"])["state"] == "pr_ready"
    assert p.calls == ["initial", "result"]


def test_timeout_prevents_late_success_until_operator_resume(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))
    db.update_incident(i["id"], deadline=time.time() - 1)
    asyncio.run(w.poll(db.incident(i["id"])))
    assert db.incident(i["id"])["state"] == "timed_out"
    p.ready = True
    assert db.polling() == []
    db.resume(i["id"], "operator")
    asyncio.run(w.poll(db.incident(i["id"])))
    assert db.incident(i["id"])["state"] == "pr_ready"


def test_unknown_dispatch_does_not_repeat(db):
    i = dispatch(db)
    p = Fake()

    async def lose_response(i, rollback=False, can_execute=None):
        raise UnknownOutcome("Response lost")

    p.dispatch = lose_response
    w = Worker(db, p)
    asyncio.run(drain(w))
    asyncio.run(drain(w))
    assert (
        next(a for a in db.actions(i["id"]) if a["kind"] == "dispatch_fix")["status"]
        == "unknown"
    )


def test_reset_during_dispatch_preserves_receipt_without_callback(db):
    i = dispatch(db)
    p = Fake()

    async def reset_inflight(i, rollback=False, can_execute=None):
        db.reset("next", "operator")
        return {"session_id": "orphan", "session_url": "https://app.devin.ai/orphan"}

    p.dispatch = reset_inflight
    asyncio.run(drain(Worker(db, p)))
    a = next(a for a in db.actions(i["id"]) if a["kind"] == "dispatch_fix")
    assert json.loads(a["result"])["session_id"] == "orphan"
    assert db.incident(i["id"])["state"] == "cancelled"
    assert db.claim() is None


def test_completed_dispatch_receipt_recovers_after_crash_before_incident_update(db):
    i = dispatch(db)
    with db.tx() as c:
        c.execute(
            "UPDATE actions SET status='succeeded',result=? WHERE incident_id=? AND kind='dispatch_fix'",
            (
                json.dumps(
                    {
                        "session_id": "durable",
                        "session_url": "https://app.devin.ai/durable",
                    }
                ),
                i["id"],
            ),
        )
    db.recover()
    assert db.incident(i["id"])["session_id"] == "durable"
    assert db.incident(i["id"])["state"] == "investigating"


def test_failed_result_call_keeps_verified_pr(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))
    p.ready = True
    asyncio.run(w.poll(db.incident(i["id"])))
    from anton.providers import ProviderFailure

    async def fail_call(i, purpose):
        raise ProviderFailure("Call rejected")

    p.call = fail_call
    asyncio.run(drain(w))
    assert db.incident(i["id"])["state"] == "pr_ready"
    assert db.incident(i["id"])["pr_url"]
    assert any("Call rejected" in x for x in p.messages)


def test_changed_checks_hold_callback_until_fresh_verification(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))
    p.ready = True
    asyncio.run(w.poll(db.incident(i["id"])))
    p.ready = False
    asyncio.run(drain(w))
    assert p.calls == ["initial"]
    p.ready = True
    asyncio.run(w.poll(db.incident(i["id"])))
    asyncio.run(drain(w))
    assert p.calls == ["initial", "result"]


def test_verification_crossing_deadline_cannot_mark_ready(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))
    p.ready = True
    verify = p.verify_pr

    async def late(i, number):
        result = await verify(i, number)
        db.update_incident(i["id"], deadline=time.time() - 1)
        return result

    p.verify_pr = late
    asyncio.run(w.poll(db.incident(i["id"])))
    asyncio.run(drain(w))
    assert db.incident(i["id"])["state"] == "timed_out"
    assert p.calls == ["initial"]


def test_cancelled_attempt_cannot_mark_new_strategy_ready(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))
    p.ready = True
    verify = p.verify_pr

    async def cancelled(i, number):
        result = await verify(i, number)
        db.cancel_strategy(i["id"], "operator", "Confirmed provider session finished")
        return result

    p.verify_pr = cancelled
    asyncio.run(w.poll(db.incident(i["id"])))
    assert db.incident(i["id"])["state"] == "awaiting_approval"
    assert db.incident(i["id"])["pr_head"] is None


def test_blocked_session_reports_specific_required_input_and_progress(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))

    async def blocked(id):
        return {
            "status_enum": "blocked",
            "structured_output": {
                "input_needed": "Grant repository access to the Devin integration.",
                "failure_reason": "",
                "change_summary": "No changes made.",
                "validation_summary": "Checkout tests could not run because clone failed.",
            },
        }

    p.session = blocked
    asyncio.run(w.poll(db.incident(i["id"])))
    asyncio.run(drain(w))
    assert db.incident(i["id"])["state"] == "blocked"
    assert any(
        "Grant repository access" in message and "clone failed" in message
        for message in p.messages
    )
    assert any(
        "Grant repository access" in event["data"] for event in db.timeline(i["id"])
    )


def test_expired_session_reports_provider_failure_reason(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))

    async def expired(id):
        return {
            "status_enum": "expired",
            "structured_output": {
                "failure_reason": "Session compute limit reached before regression validation."
            },
        }

    p.session = expired
    asyncio.run(w.poll(db.incident(i["id"])))
    asyncio.run(drain(w))
    assert db.incident(i["id"])["state"] == "failed"
    assert any("compute limit reached" in message for message in p.messages)


def test_blocked_without_structured_reason_reports_omission_honestly(db):
    i = dispatch(db)
    p = Fake()
    w = Worker(db, p)
    asyncio.run(drain(w))

    async def blocked(id):
        return {"status_enum": "blocked", "structured_output": None}

    p.session = blocked
    asyncio.run(w.poll(db.incident(i["id"])))
    asyncio.run(drain(w))
    assert any(
        "did not supply the required input" in message
        and "https://app.devin.ai/s" in message
        for message in p.messages
    )
