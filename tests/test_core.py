import concurrent.futures
import sqlite3

import pytest

from anton.store import Conflict


def alert(db, **kw):
    data = dict(
        event_id="e1",
        run_id="run-1",
        monitor_id="m1",
        group="demo",
        occurrence="o1",
        status="alert",
        deployed_sha="a" * 40,
        error_count=5,
    )
    return db.ingest(data | kw)


def test_duplicate_alert_concurrency(db):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        rows = list(pool.map(lambda _: alert(db), range(12)))
    assert len({x["id"] for x in rows}) == 1
    assert len(db.actions(rows[0]["id"])) == 2


def test_approvals_bind_actor_targets_and_one_strategy(db):
    i = alert(db)
    p = db.propose(i["id"], "dispatch_fix", "42", "telegram")
    with pytest.raises(Conflict):
        db.approve(p["token"], "99", "telegram")
    with concurrent.futures.ThreadPoolExecutor() as pool:
        results = list(
            pool.map(lambda _: db.approve(p["token"], "42", "telegram"), range(8))
        )
    assert len({r["id"] for r in results}) == 1
    with pytest.raises(Conflict):
        db.propose(i["id"], "rollback", "42", "telegram")


def test_expired_approval_reset_and_late_alert(db):
    i = alert(db)
    p = db.propose(i["id"], "page_team", "42", "telegram")
    with db.tx() as c:
        c.execute("UPDATE approvals SET expires=0")
    with pytest.raises(Conflict):
        db.approve(p["token"], "42", "telegram")
    p = db.propose(i["id"], "dispatch_fix", "42", "telegram")
    db.reset("run-2", "operator")
    with pytest.raises(Conflict):
        db.approve(p["token"], "42", "telegram")
    assert alert(db, event_id="late", occurrence="o2") is None
    assert db.incident(i["id"])["state"] == "cancelled"


def test_recovery_new_occurrence_and_append_only(db):
    i = alert(db)
    alert(db, event_id="recovery", status="recovered")
    j = alert(db, event_id="new", occurrence="o2")
    assert i["id"] != j["id"]
    with pytest.raises(sqlite3.DatabaseError):
        with db.tx() as c:
            c.execute("DELETE FROM events")


def test_expired_lease_becomes_unknown_never_requeued(db):
    alert(db)
    a = db.claim()
    with db.tx() as c:
        c.execute("UPDATE actions SET lease_until=0 WHERE id=?", (a["id"],))
    db.recover()
    assert db.action(a["id"])["status"] == "unknown"
    assert db.claim()["id"] != a["id"]


def test_voice_requires_server_conversation_binding(db):
    i = alert(db)
    with pytest.raises(Conflict):
        db.voice_context("invented", "run-1")
    db.bind_call(i["id"], "conversation", "call", "initial")
    assert db.voice_context("conversation", "run-1")["id"] == i["id"]
    db.reset("run-2", "operator")
    with pytest.raises(Conflict):
        db.voice_context("conversation", "run-1")


def test_run_reuse_without_incidents_is_rejected(db):
    db.reset("run-2", "operator")
    with pytest.raises(Conflict):
        db.reset("run-1", "operator")


def test_recovery_before_delayed_alert_prevents_new_work(db):
    assert alert(db, event_id="recover-first", status="recovered") is None
    assert alert(db, event_id="delayed") is None


def test_strategy_switch_requires_reconciled_actions_and_new_approval(db):
    i = alert(db)
    p = db.propose(i["id"], "dispatch_fix", "42", "telegram")
    a = db.approve(p["token"], "42", "telegram")
    with db.tx() as c:
        c.execute("UPDATE actions SET status='unknown' WHERE id=?", (a["id"],))
    with pytest.raises(Conflict):
        db.cancel_strategy(i["id"], "operator", "External session confirmed stopped")
    db.complete(a["id"], {"session_id": "s"}, "failed")
    db.cancel_strategy(i["id"], "operator", "External session confirmed stopped")
    p = db.propose(i["id"], "rollback", "42", "telegram")
    a = db.approve(p["token"], "42", "telegram")
    assert a["kind"] == "rollback"


def test_telegram_proposal_update_is_durable_and_idempotent(db):
    i = alert(db)
    first = db.propose(i["id"], "dispatch_fix", "42", "telegram", event_id="update-1")
    second = db.propose(i["id"], "dispatch_fix", "42", "telegram", event_id="update-1")
    assert first == second
    with pytest.raises(Conflict):
        db.propose(i["id"], "page_team", "42", "telegram", event_id="update-1")


def test_voice_approval_cannot_be_consumed_from_another_conversation(db):
    i = alert(db)
    first = db.propose(i["id"], "dispatch_fix", "oncall", "voice:conversation-one")
    with pytest.raises(Conflict):
        db.approve(first["token"], "oncall", "voice:conversation-two")
    assert (
        db.approve(first["token"], "oncall", "voice:conversation-one")["kind"]
        == "dispatch_fix"
    )


def test_prepared_voice_choices_execute_only_explicitly_approved_tokens(db):
    i = alert(db)
    fix = db.propose(i["id"], "dispatch_fix", "oncall", "voice:conversation")
    page = db.propose(i["id"], "page_team", "oncall", "voice:conversation")
    assert not any(
        a["kind"] in ("dispatch_fix", "page_team") for a in db.actions(i["id"])
    )
    db.approve(fix["token"], "oncall", "voice:conversation")
    assert not any(a["kind"] == "page_team" for a in db.actions(i["id"]))
    # One utterance may name both; only then consume the second token as well.
    db.approve(page["token"], "oncall", "voice:conversation")
    assert (
        len(
            [
                a
                for a in db.actions(i["id"])
                if a["kind"] in ("dispatch_fix", "page_team")
            ]
        )
        == 2
    )
