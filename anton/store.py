import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .summaries import summary_lines


class Conflict(Exception):
    pass


def uid():
    return uuid.uuid4().hex


def js(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path, settings):
        self.path = path
        self.settings = settings
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,monitor_id TEXT NOT NULL,grp TEXT NOT NULL,occurrence TEXT NOT NULL,state TEXT NOT NULL,strategy TEXT,repository TEXT NOT NULL,base_branch TEXT NOT NULL,deployed_sha TEXT NOT NULL,seed_sha TEXT NOT NULL,known_good_sha TEXT NOT NULL,branch TEXT,session_id TEXT,session_url TEXT,pr_number INTEGER,pr_url TEXT,pr_head TEXT,evidence TEXT,deadline REAL,recovered INTEGER DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(run_id,monitor_id,grp,occurrence));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS closed_occurrences(run_id TEXT,monitor_id TEXT,grp TEXT,occurrence TEXT,PRIMARY KEY(run_id,monitor_id,grp,occurrence));
            CREATE TABLE IF NOT EXISTS receipts(provider TEXT,event_id TEXT,run_id TEXT,incident_id TEXT,created REAL NOT NULL,PRIMARY KEY(provider,event_id));
            CREATE TABLE IF NOT EXISTS approvals(token_hash TEXT PRIMARY KEY,token TEXT NOT NULL,incident_id TEXT NOT NULL,action TEXT NOT NULL,actor TEXT NOT NULL,channel TEXT NOT NULL,target_sha TEXT NOT NULL,base_sha TEXT NOT NULL,expires REAL NOT NULL,consumed REAL,action_id TEXT,invalid INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,kind TEXT NOT NULL,dedupe TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,result TEXT,lease_until REAL,created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(incident_id,dedupe));
            CREATE TABLE IF NOT EXISTS calls(conversation_id TEXT PRIMARY KEY,call_sid TEXT,incident_id TEXT NOT NULL,run_id TEXT NOT NULL,responder TEXT NOT NULL,purpose TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'initiated');
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,incident_id TEXT,run_id TEXT,kind TEXT NOT NULL,data TEXT NOT NULL,created REAL NOT NULL);
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
            """)
            c.execute(
                "INSERT OR IGNORE INTO meta VALUES(?,?)", ("run_id", settings.run_id)
            )
            c.execute(
                "INSERT OR IGNORE INTO runs VALUES(?,?)", (settings.run_id, time.time())
            )

    @contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def _event(self, c, i, kind, data):
        run = (
            c.execute("SELECT run_id FROM incidents WHERE id=?", (i,)).fetchone()
            if i
            else None
        )
        c.execute(
            "INSERT INTO events(incident_id,run_id,kind,data,created) VALUES(?,?,?,?,?)",
            (i, run[0] if run else None, kind, js(data), time.time()),
        )

    def _enqueue(self, c, i, kind, dedupe, payload=None):
        now = time.time()
        aid = uid()
        c.execute(
            "INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (aid, i, kind, dedupe, "pending", js(payload or {}), None, None, now, now),
        )
        return dict(
            c.execute(
                "SELECT * FROM actions WHERE incident_id=? AND dedupe=?", (i, dedupe)
            ).fetchone()
        )

    def _active(self, c, i, expected=None):
        row = c.execute("SELECT * FROM incidents WHERE id=?", (i,)).fetchone()
        if (
            not row
            or row["run_id"]
            != c.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[0]
            or row["state"] in ("cancelled", "failed", "timed_out", "blocked")
        ):
            raise Conflict("Incident is inactive; operator resumption required")
        if expected and any(
            row[key] != expected.get(key) for key in ("branch", "session_id", "run_id")
        ):
            raise Conflict("Remediation attempt changed; stale work rejected")
        return dict(row)

    def ingest(self, data):
        data = dict(data)
        data["status"] = {
            "Triggered": "alert",
            "Re-Triggered": "alert",
            "Renotify": "alert",
            "Recovered": "recovered",
        }.get(data["status"], data["status"])
        with self.tx() as c:
            old = c.execute(
                "SELECT incident_id FROM receipts WHERE provider=? AND event_id=?",
                ("datadog", data["event_id"]),
            ).fetchone()
            if old:
                return self._row(c, old[0]) if old[0] else None
            active = c.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[
                0
            ]
            found = c.execute(
                "SELECT * FROM incidents WHERE run_id=? AND monitor_id=? AND grp=? AND occurrence=?",
                (data["run_id"], data["monitor_id"], data["group"], data["occurrence"]),
            ).fetchone()
            i = found["id"] if found else None
            closed = c.execute(
                "SELECT 1 FROM closed_occurrences WHERE run_id=? AND monitor_id=? AND grp=? AND occurrence=?",
                (data["run_id"], data["monitor_id"], data["group"], data["occurrence"]),
            ).fetchone()
            if data["status"] == "recovered":
                c.execute(
                    "INSERT OR IGNORE INTO closed_occurrences VALUES(?,?,?,?)",
                    (
                        data["run_id"],
                        data["monitor_id"],
                        data["group"],
                        data["occurrence"],
                    ),
                )
            if (
                data["run_id"] == active
                and not found
                and not closed
                and data["status"] == "alert"
            ):
                if data["deployed_sha"] != self.settings.deployed_sha:
                    raise Conflict("Deployed SHA does not match configured target")
                i = uid()
                now = time.time()
                c.execute(
                    "INSERT INTO incidents(id,run_id,monitor_id,grp,occurrence,state,repository,base_branch,deployed_sha,seed_sha,known_good_sha,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        i,
                        active,
                        data["monitor_id"],
                        data["group"],
                        data["occurrence"],
                        "awaiting_approval",
                        self.settings.repository,
                        self.settings.base_branch,
                        data["deployed_sha"],
                        self.settings.seed_regression_sha,
                        self.settings.known_good_sha,
                        now,
                        now,
                    ),
                )
                self._event(
                    c,
                    i,
                    "detected",
                    {
                        "error_count": data.get("error_count"),
                        "deployed_sha": data["deployed_sha"],
                    },
                )
                self._enqueue(c, i, "telegram", "initial_alert", {"type": "initial"})
                self._enqueue(c, i, "call", "initial_call", {"purpose": "initial"})
            if i and data["status"] == "recovered":
                c.execute(
                    "UPDATE incidents SET recovered=1,updated=? WHERE id=?",
                    (time.time(), i),
                )
                self._event(
                    c,
                    i,
                    "monitor_recovered",
                    {"attribution": "not attributed to undeployed remediation"},
                )
            c.execute(
                "INSERT INTO receipts VALUES(?,?,?,?,?)",
                ("datadog", data["event_id"], data["run_id"], i, time.time()),
            )
            self._event(
                c,
                i,
                "datadog_receipt",
                {
                    "event_id": data["event_id"],
                    "run_id": data["run_id"],
                    "status": data["status"],
                    "active": data["run_id"] == active,
                },
            )
            return self._row(c, i) if i else None

    def _row(self, c, i):
        r = c.execute("SELECT * FROM incidents WHERE id=?", (i,)).fetchone()
        return dict(r) if r else None

    def incident(self, i):
        with self.tx() as c:
            return self._row(c, i)

    def list_incidents(self):
        with self.tx() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM incidents ORDER BY created DESC LIMIT 100"
                )
            ]

    def actions(self, i):
        with self.tx() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM actions WHERE incident_id=? ORDER BY created", (i,)
                )
            ]

    def action(self, a):
        with self.tx() as c:
            r = c.execute("SELECT * FROM actions WHERE id=?", (a,)).fetchone()
            return dict(r) if r else None

    def timeline(self, i):
        with self.tx() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM events WHERE incident_id=? ORDER BY seq", (i,)
                )
            ]

    def propose(self, i, action, actor, channel, base_sha=None, event_id=None):
        if action not in ("dispatch_fix", "rollback", "page_team"):
            raise Conflict("Unknown action")
        with self.tx() as c:
            row = self._active(c, i)
            receipt_key = "telegram-proposal:" + str(event_id)
            if event_id:
                old = c.execute(
                    "SELECT value FROM meta WHERE key=?", (receipt_key,)
                ).fetchone()
                if old:
                    saved = json.loads(old[0])
                    if (
                        saved["actor"] != actor
                        or saved["incident_id"] != i
                        or saved["result"]["action"] != action
                    ):
                        raise Conflict("Telegram update binding changed")
                    return saved["result"]
            if (
                action in ("dispatch_fix", "rollback")
                and row["strategy"]
                and row["strategy"] != action
            ):
                raise Conflict(
                    "An active remediation exists; cancel and reconcile before switching"
                )
            target = row["seed_sha"] if action == "rollback" else row["deployed_sha"]
            base = base_sha or row["deployed_sha"]
            if base != row["deployed_sha"]:
                raise Conflict(
                    "Base changed; refresh deployment configuration and reset the run"
                )
            token = secrets.token_urlsafe(24)
            expiry = time.time() + 300
            c.execute(
                "INSERT INTO approvals(token_hash,token,incident_id,action,actor,channel,target_sha,base_sha,expires) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    token,
                    i,
                    action,
                    actor,
                    channel,
                    target,
                    base,
                    expiry,
                ),
            )
            self._event(
                c,
                i,
                "approval_proposed",
                {
                    "action": action,
                    "actor": actor,
                    "channel": channel,
                    "target_sha": target,
                    "base_sha": base,
                    "expires": expiry,
                },
            )
            result = {
                "token": token,
                "action": action,
                "target_sha": target,
                "base_sha": base,
                "expires": expiry,
                "readback": f"Approve {action} in {row['repository']} against {row['base_branch']} at {base}; target {target}. {'This pages the configured team in Telegram.' if action == 'page_team' else 'This opens a PR only; no merge or deployment.'}",
            }
            if event_id:
                c.execute(
                    "INSERT INTO meta VALUES(?,?)",
                    (
                        receipt_key,
                        js({"actor": actor, "incident_id": i, "result": result}),
                    ),
                )
                c.execute(
                    "INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?)",
                    ("telegram", str(event_id), row["run_id"], i, time.time()),
                )
            return result

    def approve(self, token, actor, channel, event_id=None):
        with self.tx() as c:
            p = c.execute(
                "SELECT * FROM approvals WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
            if not p or p["actor"] != actor or p["channel"] != channel or p["invalid"]:
                raise Conflict("Approval binding is invalid")
            row = self._active(c, p["incident_id"])
            if event_id:
                c.execute(
                    "INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?)",
                    ("telegram", str(event_id), row["run_id"], row["id"], time.time()),
                )
            if p["consumed"]:
                return dict(
                    c.execute(
                        "SELECT * FROM actions WHERE id=?", (p["action_id"],)
                    ).fetchone()
                )
            if p["expires"] < time.time():
                raise Conflict("Approval expired; request a new proposal")
            if p["base_sha"] != row["deployed_sha"]:
                raise Conflict("Approval target is stale")
            kind = p["action"]
            if kind in ("dispatch_fix", "rollback"):
                if row["strategy"] and row["strategy"] != kind:
                    raise Conflict("Conflicting remediation strategy")
                c.execute(
                    "UPDATE incidents SET strategy=?,branch=COALESCE(branch,?),updated=? WHERE id=?",
                    (
                        kind,
                        "anton/" + row["run_id"] + "/" + row["id"][:12],
                        time.time(),
                        row["id"],
                    ),
                )
            branch = c.execute(
                "SELECT branch FROM incidents WHERE id=?", (row["id"],)
            ).fetchone()[0]
            a = self._enqueue(
                c,
                row["id"],
                kind,
                kind + (":" + branch if kind != "page_team" else ""),
                {
                    "target_sha": p["target_sha"],
                    "base_sha": p["base_sha"],
                    "branch": branch,
                },
            )
            c.execute(
                "UPDATE approvals SET consumed=?,action_id=? WHERE token_hash=?",
                (time.time(), a["id"], p["token_hash"]),
            )
            self._event(
                c,
                row["id"],
                "approved",
                {
                    "actor": actor,
                    "channel": channel,
                    "action": kind,
                    "target_sha": p["target_sha"],
                    "base_sha": p["base_sha"],
                    "action_id": a["id"],
                },
            )
            return a

    def claim(self):
        with self.tx() as c:
            r = c.execute(
                "SELECT a.* FROM actions a JOIN incidents i ON i.id=a.incident_id JOIN meta m ON m.key='run_id' AND m.value=i.run_id WHERE a.status='pending' AND i.state!='cancelled' AND (i.state NOT IN ('blocked','failed','timed_out') OR a.kind='telegram') ORDER BY a.created LIMIT 1"
            ).fetchone()
            if not r:
                return None
            c.execute(
                "UPDATE actions SET status='running',lease_until=?,updated=? WHERE id=?",
                (time.time() + 120, time.time(), r["id"]),
            )
            return dict(r) | {"status": "running"}

    def complete(self, a, result, status="succeeded"):
        with self.tx() as c:
            row = c.execute("SELECT * FROM actions WHERE id=?", (a,)).fetchone()
            if not row:
                return
            c.execute(
                "UPDATE actions SET status=?,result=?,lease_until=NULL,updated=? WHERE id=?",
                (status, js(result), time.time(), a),
            )
            self._event(
                c,
                row["incident_id"],
                "action_" + status,
                {"action_id": a, "kind": row["kind"], "result": result},
            )

    def recover(self):
        with self.tx() as c:
            for action in c.execute(
                "SELECT a.* FROM actions a JOIN incidents i ON i.id=a.incident_id JOIN meta m ON m.key='run_id' AND m.value=i.run_id WHERE a.status='succeeded' AND a.kind=i.strategy AND i.session_id IS NULL AND i.state IN ('awaiting_approval','investigating','preparing_revert')"
            ).fetchall():
                result = json.loads(action["result"] or "{}")
                payload = json.loads(action["payload"])
                incident = self._row(c, action["incident_id"])
                if (
                    result.get("session_id")
                    and payload.get("branch") == incident["branch"]
                ):
                    c.execute(
                        "UPDATE incidents SET session_id=?,session_url=?,state='investigating',deadline=COALESCE(deadline,?),updated=? WHERE id=?",
                        (
                            result["session_id"],
                            result.get("session_url", ""),
                            action["created"] + 600,
                            time.time(),
                            incident["id"],
                        ),
                    )
                    self._event(
                        c,
                        incident["id"],
                        "dispatch_receipt_recovered",
                        {"action_id": action["id"], "session_id": result["session_id"]},
                    )
                    self._enqueue(
                        c,
                        incident["id"],
                        "telegram",
                        "session_started",
                        {
                            "text": "Devin investigation: "
                            + result.get("session_url", "")
                        },
                    )
            for row in c.execute(
                "SELECT * FROM actions WHERE status='running' AND lease_until<?",
                (time.time(),),
            ).fetchall():
                c.execute(
                    "UPDATE actions SET status='unknown',lease_until=NULL,updated=? WHERE id=?",
                    (time.time(), row["id"]),
                )
                self._event(
                    c,
                    row["incident_id"],
                    "action_unknown",
                    {
                        "action_id": row["id"],
                        "reason": "worker lease expired; provider reconciliation required",
                    },
                )

    def bind_call(self, i, conversation, sid, purpose):
        with self.tx() as c:
            r = self._row(c, i)
            c.execute(
                "INSERT OR IGNORE INTO calls(conversation_id,call_sid,incident_id,run_id,responder,purpose) VALUES(?,?,?,?,?,?)",
                (
                    conversation,
                    sid,
                    i,
                    r["run_id"],
                    self.settings.responder_id,
                    purpose,
                ),
            )

    def voice_context(self, conversation, run):
        with self.tx() as c:
            call = c.execute(
                "SELECT * FROM calls WHERE conversation_id=?", (conversation,)
            ).fetchone()
            if (
                not call
                or call["run_id"] != run
                or call["responder"] != self.settings.responder_id
            ):
                raise Conflict("Unknown or stale conversation binding")
            return self._active(c, call["incident_id"])

    def reset(self, run, actor):
        if not run or run == "unconfigured":
            raise Conflict("A unique run identifier is required")
        with self.tx() as c:
            old = c.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[0]
            if (
                run == old
                or c.execute("SELECT 1 FROM runs WHERE id=?", (run,)).fetchone()
            ):
                raise Conflict("Run identifiers cannot be reused")
            for row in c.execute(
                "SELECT id FROM incidents WHERE run_id=?", (old,)
            ).fetchall():
                self._event(c, row["id"], "reset", {"actor": actor, "next_run": run})
                c.execute(
                    "UPDATE incidents SET state='cancelled',updated=? WHERE id=?",
                    (time.time(), row["id"]),
                )
                c.execute(
                    "UPDATE approvals SET invalid=1 WHERE incident_id=?", (row["id"],)
                )
                c.execute(
                    "UPDATE actions SET status=CASE WHEN status='running' THEN 'unknown' ELSE 'cancelled' END,updated=? WHERE incident_id=? AND status IN ('pending','running','held')",
                    (time.time(), row["id"]),
                )
            c.execute("UPDATE meta SET value=? WHERE key='run_id'", (run,))
            c.execute("INSERT INTO runs VALUES(?,?)", (run, time.time()))
            return {"old_run": old, "run_id": run}

    def update_incident(self, i, expected=None, **values):
        allowed = {
            "state",
            "session_id",
            "session_url",
            "pr_number",
            "pr_url",
            "pr_head",
            "evidence",
            "deadline",
        }
        if not set(values) <= allowed:
            raise ValueError("Invalid update")
        with self.tx() as c:
            self._active(c, i, expected)
            c.execute(
                "UPDATE incidents SET "
                + ",".join(k + "=?" for k in values)
                + ",updated=? WHERE id=?",
                (*values.values(), time.time(), i),
            )
            self._event(c, i, "incident_updated", values)

    def enqueue(self, i, kind, dedupe, payload, expected=None):
        with self.tx() as c:
            self._active(c, i, expected)
            return self._enqueue(c, i, kind, dedupe, payload)

    def polling(self):
        with self.tx() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT i.* FROM incidents i JOIN meta m ON m.key='run_id' AND m.value=i.run_id WHERE i.state IN ('investigating','preparing_revert','verifying_pr','pr_ready') AND i.session_id IS NOT NULL"
                )
            ]

    def outcome(self, i, state, reason, expected=None):
        with self.tx() as c:
            self._active(c, i, expected)
            c.execute(
                "UPDATE incidents SET state=?,updated=? WHERE id=?",
                (state, time.time(), i),
            )
            self._event(c, i, state, {"reason": reason})
            self._enqueue(c, i, "telegram", state, {"text": reason})

    def resume(self, i, actor):
        with self.tx() as c:
            r = self._row(c, i)
            if (
                not r
                or r["run_id"]
                != c.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[0]
                or r["state"] not in ("blocked", "timed_out", "failed")
            ):
                raise Conflict(
                    "Only active-run blocked/failed/timed-out incidents can resume"
                )
            if not r["session_id"]:
                raise Conflict("Reconcile dispatch action first")
            c.execute(
                "UPDATE incidents SET state='investigating',deadline=?,updated=? WHERE id=?",
                (time.time() + 600, time.time(), i),
            )
            self._event(c, i, "operator_resumed", {"actor": actor})
            return self._row(c, i)

    def can_execute(self, a):
        with self.tx() as c:
            row = c.execute("SELECT * FROM actions WHERE id=?", (a,)).fetchone()
            if not row or row["status"] != "running":
                return False
            i = self._row(c, row["incident_id"])
            run = c.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[0]
            return (
                i["run_id"] == run
                and i["state"] != "cancelled"
                and (
                    i["state"] not in ("blocked", "failed", "timed_out")
                    or row["kind"] == "telegram"
                )
            )

    def call_status(self, conversation, status, event_id):
        with self.tx() as c:
            old = c.execute(
                "SELECT 1 FROM receipts WHERE provider='elevenlabs' AND event_id=?",
                (event_id,),
            ).fetchone()
            if old:
                return
            call = c.execute(
                "SELECT * FROM calls WHERE conversation_id=?", (conversation,)
            ).fetchone()
            if not call:
                raise Conflict("Unknown conversation")
            c.execute(
                "UPDATE calls SET status=? WHERE conversation_id=?",
                (status, conversation),
            )
            c.execute(
                "INSERT INTO receipts VALUES(?,?,?,?,?)",
                (
                    "elevenlabs",
                    event_id,
                    call["run_id"],
                    call["incident_id"],
                    time.time(),
                ),
            )
            self._event(
                c,
                call["incident_id"],
                "call_status",
                {"conversation_id": conversation, "status": status},
            )
            if status in ("failed", "no-answer", "busy"):
                self._enqueue(
                    c,
                    call["incident_id"],
                    "telegram",
                    "call-status:" + event_id,
                    {
                        "text": "Call "
                        + status
                        + ". Telegram approvals remain available; no automatic redial."
                    },
                )

    def reconcile(self, a, result, actor):
        with self.tx() as c:
            row = c.execute("SELECT * FROM actions WHERE id=?", (a,)).fetchone()
            if not row or row["status"] != "unknown":
                raise Conflict("Only unknown actions may be reconciled")
            self._event(
                c,
                row["incident_id"],
                "operator_reconciliation",
                {"actor": actor, "action_id": a, "evidence": result},
            )
        self.complete(a, result)

    def retry_call(self, i, actor, purpose):
        with self.tx() as c:
            row = self._active(c, i)
            if purpose == "result" and row["state"] != "pr_ready":
                raise Conflict("Result call requires current verified PR")
            key = "explicit-call:" + uid()
            self._event(
                c, i, "call_retry_requested", {"actor": actor, "purpose": purpose}
            )
            return self._enqueue(c, i, "call", key, {"purpose": purpose})

    def cancel_strategy(self, i, actor, evidence):
        with self.tx() as c:
            r = self._row(c, i)
            if not r or r["state"] == "cancelled":
                raise Conflict("Incident is inactive")
            if c.execute(
                "SELECT 1 FROM actions WHERE incident_id=? AND status IN ('unknown','running') AND kind IN ('dispatch_fix','rollback','call')",
                (i,),
            ).fetchone():
                raise Conflict(
                    "Reconcile all in-flight external effects before cancelling"
                )
            c.execute("UPDATE approvals SET invalid=1 WHERE incident_id=?", (i,))
            c.execute(
                "UPDATE actions SET status='cancelled',updated=? WHERE incident_id=? AND status IN ('pending','held')",
                (time.time(), i),
            )
            c.execute(
                "UPDATE incidents SET strategy=NULL,branch=?,session_id=NULL,session_url=NULL,pr_number=NULL,pr_url=NULL,pr_head=NULL,evidence=NULL,deadline=NULL,state='awaiting_approval',updated=? WHERE id=?",
                ("anton/" + r["run_id"] + "/" + uid()[:12], time.time(), i),
            )
            self._event(
                c,
                i,
                "strategy_cancelled",
                {
                    "actor": actor,
                    "prior_strategy": r["strategy"],
                    "session_id": r["session_id"],
                    "evidence": evidence,
                },
            )
            return self._row(c, i)

    def defer_callback(self, a, reason):
        with self.tx() as c:
            row = c.execute("SELECT * FROM actions WHERE id=?", (a,)).fetchone()
            if not row or row["status"] != "running":
                return
            c.execute(
                "UPDATE actions SET status='held',lease_until=NULL,updated=? WHERE id=?",
                (time.time(), a),
            )
            self._event(c, row["incident_id"], "callback_held", {"reason": reason})

    def release_callback(self, i):
        with self.tx() as c:
            self._active(c, i)
            c.execute(
                "UPDATE actions SET status='pending',updated=? WHERE incident_id=? AND kind='call' AND status='held'",
                (time.time(), i),
            )

    def mark_ready(self, i, evidence, expected=None):
        with self.tx() as c:
            row = self._active(c, i, expected)
            if (
                row["state"] != "pr_ready"
                and row["deadline"]
                and time.time() > row["deadline"]
            ):
                c.execute(
                    "UPDATE incidents SET state='timed_out',updated=? WHERE id=?",
                    (time.time(), i),
                )
                self._event(
                    c,
                    i,
                    "timed_out",
                    {
                        "reason": "Verification crossed the ten-minute deadline; explicit resume required"
                    },
                )
                self._enqueue(
                    c,
                    i,
                    "telegram",
                    "timed_out",
                    {
                        "text": "Ten-minute deadline expired during verification. No callback. Operator resume required. "
                        + (row["session_url"] or "")
                    },
                )
                return False
            c.execute(
                "UPDATE incidents SET state='pr_ready',pr_number=?,pr_url=?,pr_head=?,evidence=?,updated=? WHERE id=?",
                (
                    evidence["number"],
                    evidence["url"],
                    evidence["head"],
                    js(evidence),
                    time.time(),
                    i,
                ),
            )
            self._event(c, i, "pr_verified", evidence)
            self._enqueue(
                c,
                i,
                "telegram",
                "pr_ready:" + evidence["head"],
                {
                    "text": "Verified remediation PR ready for review, not deployed: "
                    + evidence["url"]
                    + "\nExact head: "
                    + evidence["head"]
                    + "\nRegression checks passed: 1000 accepted, 999 rejected, normal checkout and RUM preserved. "
                    + js(evidence["checks"])
                    + "\n"
                    + summary_lines(evidence.get("provider_summary", {}))
                },
            )
            self._enqueue(
                c, i, "call", "result_call:" + row["branch"], {"purpose": "result"}
            )
            c.execute(
                "UPDATE actions SET status='pending',updated=? WHERE incident_id=? AND kind='call' AND status='held'",
                (time.time(), i),
            )

    def manual_outcome(self, a, status, evidence, actor):
        with self.tx() as c:
            row = c.execute("SELECT * FROM actions WHERE id=?", (a,)).fetchone()
            if not row or row["status"] != "unknown":
                raise Conflict("Action is not unknown")
            c.execute(
                "UPDATE actions SET status=?,result=?,updated=? WHERE id=?",
                (status, js({"operator_evidence": evidence}), time.time(), a),
            )
            self._event(
                c,
                row["incident_id"],
                "manual_reconciliation",
                {
                    "action_id": a,
                    "actor": actor,
                    "status": status,
                    "evidence": evidence,
                },
            )
