import asyncio
import hashlib
import json
import logging
import time

from .providers import NotReady, ProviderFailure, UnknownOutcome
from .store import Conflict


class Worker:
    def __init__(self, store, providers):
        self.db = store
        self.p = providers

    async def run(self):
        work = set()

        async def poll_loop():
            while True:
                try:
                    for incident in self.db.polling():
                        await self.poll(incident)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logging.error("Polling interrupted (%s)", type(error).__name__)
                await asyncio.sleep(2)

        polling = asyncio.create_task(poll_loop())
        try:
            while True:
                self.db.recover()
                work = {task for task in work if not task.done()}
                while len(work) < 4:
                    a = self.db.claim()
                    if not a:
                        break
                    work.add(asyncio.create_task(self.execute(a)))
                await asyncio.sleep(1)
        finally:
            polling.cancel()
            for task in work:
                task.cancel()
            await asyncio.gather(polling, *work, return_exceptions=True)

    async def execute(self, a):
        i = self.db.incident(a["incident_id"])
        payload = json.loads(a["payload"])
        try:
            if not self.db.can_execute(a["id"]):
                return
            if a["kind"] == "telegram":
                buttons = None
                if payload.get("type") == "initial":
                    text = f"P1: checkout validation errors observed. Incident {i['id']} / run {i['run_id']}. Cause unconfirmed. Choose an action to review and explicitly approve."
                    buttons = [
                        [
                            {
                                "text": label,
                                "callback_data": "p:" + i["id"] + ":" + action,
                            }
                        ]
                        for label, action in [
                            ("Investigate fix", "dispatch_fix"),
                            ("Propose revert", "rollback"),
                            ("Page team", "page_team"),
                        ]
                    ]
                else:
                    text = payload.get("text", "Anton incident update")
                result = await self.p.telegram(text, payload.get("buttons", buttons))
            elif a["kind"] == "page_team":
                result = await self.p.telegram(
                    f"Approved team page: incident {i['id']} / run {i['run_id']}. Checkout validation errors need attention. PR completion will not imply recovery."
                )
            elif a["kind"] == "call":
                if payload["purpose"] == "result":
                    evidence = await self.p.verify_pr(i, i["pr_number"])
                    if evidence["head"] != i["pr_head"]:
                        raise NotReady(
                            "PR changed since readiness; callback held for re-verification"
                        )
                if not self.db.can_execute(a["id"]):
                    return
                result = await self.p.call(i, payload["purpose"])
                self.db.bind_call(
                    i["id"],
                    result["conversation_id"],
                    result["call_sid"],
                    payload["purpose"],
                )
            elif a["kind"] in ("dispatch_fix", "rollback"):
                self.db.update_incident(
                    i["id"],
                    state="preparing_revert"
                    if a["kind"] == "rollback"
                    else "investigating",
                    deadline=time.time() + 600,
                )
                result = await self.p.dispatch(
                    i,
                    a["kind"] == "rollback",
                    can_execute=lambda: self.db.can_execute(a["id"]),
                )
                # Save provider receipt before any subsequent action, including reset races.
                self.db.complete(a["id"], result)
                try:
                    self.db.update_incident(
                        i["id"],
                        session_id=result["session_id"],
                        session_url=result["session_url"],
                    )
                except Conflict:
                    return
                self.db.enqueue(
                    i["id"],
                    "telegram",
                    "session_started",
                    {
                        "text": "Devin investigation started: "
                        + result["session_url"]
                        + " . No deployment has occurred."
                    },
                )
                return
            else:
                raise ProviderFailure("Unsupported action kind")
            self.db.complete(a["id"], result)
        except NotReady as e:
            if a["kind"] == "call" and payload.get("purpose") == "result":
                self.db.defer_callback(a["id"], str(e))
                self.incomplete(i, str(e))
            else:
                self.db.complete(a["id"], {"reason": str(e)}, "failed")
        except UnknownOutcome as e:
            self.db.complete(a["id"], {"reason": str(e)}, "unknown")
            self.notify_failure(i, a, str(e))
        except (ProviderFailure, Conflict) as e:
            self.db.complete(a["id"], {"reason": str(e)}, "failed")
            if a["kind"] in ("dispatch_fix", "rollback"):
                try:
                    self.db.outcome(i["id"], "blocked", str(e))
                except Conflict:
                    pass
            else:
                self.notify_failure(i, a, str(e))
        except Exception:
            self.db.complete(
                a["id"],
                {
                    "reason": "Unexpected processing failure; provider outcome requires reconciliation"
                },
                "unknown",
            )

    def notify_failure(self, i, a, reason):
        if a["kind"] == "telegram":
            return
        try:
            self.db.enqueue(
                i["id"],
                "telegram",
                "failure:" + a["id"],
                {
                    "text": f"{a['kind']}: {reason}. Existing verified PR, if any, is preserved. No automatic retry."
                },
            )
        except Conflict:
            pass

    async def poll(self, i):
        try:
            if (
                i["state"] != "pr_ready"
                and i["deadline"]
                and time.time() > i["deadline"]
            ):
                self.db.outcome(
                    i["id"],
                    "timed_out",
                    "Ten-minute deadline expired. Operator resume required for late results. "
                    + (i["session_url"] or ""),
                    expected=i,
                )
                return
            session = await self.p.session(i["session_id"])
            status = session.get("status_enum", session.get("status", ""))
            if i["state"] != "pr_ready" and status in ("blocked", "expired", "failed"):
                self.db.outcome(
                    i["id"],
                    "blocked" if status == "blocked" else "failed",
                    "Devin "
                    + status
                    + ". Review the session for required input: "
                    + i["session_url"],
                    expected=i,
                )
                return
            url = (session.get("pull_request") or {}).get("url")
            if not url:
                if status == "finished":
                    self.incomplete(
                        i,
                        "Devin finished without a PR; review session "
                        + i["session_url"],
                    )
                return
            number = self.p.pr_number(url)
            evidence = await self.p.verify_pr(i, number)
            if i["state"] == "pr_ready" and i["pr_head"] == evidence["head"]:
                return
            self.db.mark_ready(i["id"], evidence, expected=i)
        except NotReady as e:
            self.incomplete(i, str(e))
        except ProviderFailure:
            # GETs are safe to poll again. Deadline is enforced independently of provider availability.
            pass
        except Conflict:
            pass

    def incomplete(self, i, reason):
        try:
            self.db.update_incident(
                i["id"], expected=i, state="verifying_pr", pr_head=None, evidence=None
            )
            self.db.enqueue(
                i["id"],
                "telegram",
                "incomplete:" + hashlib.sha256(reason.encode()).hexdigest()[:20],
                {"text": reason + ". No success callback."},
            )
        except Conflict:
            pass
