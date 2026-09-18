import asyncio

import pytest

from anton.config import Settings
from anton.providers import NotReady, Providers


class GitHub(Providers):
    def __init__(self):
        super().__init__(Settings(deployed_sha="a" * 40))
        self.pr = {
            "number": 1,
            "state": "open",
            "draft": False,
            "html_url": "https://github.com/padmanabh-g/anton-demo-product/pull/1",
            "base": {
                "ref": "demo/buggy",
                "sha": "a" * 40,
                "repo": {"full_name": self.s.repository},
            },
            "head": {
                "ref": "anton/run/id",
                "sha": "c" * 40,
                "repo": {"full_name": self.s.repository},
            },
        }
        self.check = {
            "name": "checkout-regression",
            "head_sha": "c" * 40,
            "status": "completed",
            "conclusion": "success",
            "app": {"id": 15368},
            "html_url": "https://github.com/check/1",
        }

    async def gh(self, path):
        if "/check-runs" in path:
            return {"check_runs": [self.check]}
        if "/files" in path:
            return [
                {
                    "filename": self.s.regression_path,
                    "status": "modified",
                    "changes": 2,
                    "patch": "@@ -1 +1 @@\n-return total > MINIMUM;\n+return total >= MINIMUM;",
                }
            ]
        if "/branches/" in path:
            return {"commit": {"sha": "a" * 40}}
        return self.pr


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.pr.update(draft=True),
        lambda p: p.pr["base"].update(ref="main"),
        lambda p: p.pr["head"].update(ref="wrong"),
        lambda p: p.check.update(head_sha="d" * 40),
        lambda p: p.check.update(conclusion="failure"),
        lambda p: p.check["app"].update(id=1),
    ],
)
def test_gate_rejects_untrusted_or_wrong_head(mutation):
    p = GitHub()
    mutation(p)
    with pytest.raises(NotReady):
        asyncio.run(
            p.verify_pr(
                {
                    "branch": "anton/run/id",
                    "deployed_sha": "a" * 40,
                    "strategy": "dispatch_fix",
                },
                1,
            )
        )


def test_gate_records_exact_sha_and_checks():
    evidence = asyncio.run(
        GitHub().verify_pr(
            {
                "branch": "anton/run/id",
                "deployed_sha": "a" * 40,
                "strategy": "dispatch_fix",
            },
            1,
        )
    )
    assert evidence["head"] == "c" * 40
    assert evidence["checks"][0]["name"] == "checkout-regression"


def test_gate_rechecks_closed_or_retargeted_pr_after_checks():
    p = GitHub()
    original = p.gh
    reads = 0

    async def race(path):
        nonlocal reads
        result = await original(path)
        if path == "/pulls/1":
            reads += 1
            if reads == 2:
                return result | {"state": "closed"}
        return result

    p.gh = race
    with pytest.raises(NotReady):
        asyncio.run(
            p.verify_pr(
                {
                    "branch": "anton/run/id",
                    "deployed_sha": "a" * 40,
                    "strategy": "dispatch_fix",
                },
                1,
            )
        )


class RollbackGitHub(GitHub):
    def __init__(self):
        super().__init__()
        self.current = "seedblob"
        self.parents = [{"sha": "b" * 40}]
        self.ancestry = "identical"

    async def gh(self, path):
        if path == "/commits/" + "a" * 40:
            return {
                "parents": self.parents,
                "files": [
                    {
                        "filename": self.s.regression_path,
                        "status": "modified",
                        "changes": 2,
                    }
                ],
            }
        if path.startswith("/compare/"):
            return {"status": self.ancestry}
        if path.startswith("/contents/"):
            return {"sha": "goodblob" if path.endswith("b" * 40) else self.current}
        return await super().gh(path)


def test_rollback_guard_rejects_merge_commit_and_missing_ancestry():
    i = {"deployed_sha": "a" * 40, "seed_sha": "a" * 40, "known_good_sha": "b" * 40}
    p = RollbackGitHub()
    assert asyncio.run(p.rollback_guard(i))["good_blob"] == "goodblob"
    p.parents.append({"sha": "e" * 40})
    from anton.providers import ProviderFailure

    with pytest.raises(ProviderFailure):
        asyncio.run(p.rollback_guard(i))
    p.parents = p.parents[:1]
    p.ancestry = "diverged"
    with pytest.raises(ProviderFailure):
        asyncio.run(p.rollback_guard(i))
    p.ancestry = "identical"
    p.current = "goodblob"
    with pytest.raises(ProviderFailure):
        asyncio.run(p.rollback_guard(i))


def test_dispatch_rechecks_authorization_after_preflight():
    from dataclasses import replace

    from anton.providers import ProviderFailure

    p = GitHub()
    p.s = replace(p.s, devin_api_key="test-only")
    active = True
    posted = []

    async def reset_during_base(i):
        nonlocal active
        active = False

    async def request(*args, **kwargs):
        posted.append(args)
        return {"session_id": "must-not-create"}

    p.base = reset_during_base
    p.request = request
    i = {"id": "id", "run_id": "r", "branch": "anton/r/id", "deployed_sha": "a" * 40}
    with pytest.raises(ProviderFailure):
        asyncio.run(p.dispatch(i, can_execute=lambda: active))
    assert posted == []


def test_dispatch_requests_bounded_structured_output_schema():
    from dataclasses import replace

    p = GitHub()
    p.s = replace(p.s, devin_api_key="test-only")
    payloads = []

    async def request(method, url, headers=None, data=None):
        payloads.append(data)
        return {"session_id": "s", "url": "https://app.devin.ai/s"}

    p.request = request
    asyncio.run(
        p.dispatch(
            {
                "id": "id",
                "run_id": "r",
                "branch": "anton/r/id",
                "deployed_sha": "a" * 40,
            }
        )
    )
    schema = payloads[0]["structured_output_schema"]
    assert schema["type"] == "object"
    assert set(schema["required"]) == {
        "input_needed",
        "failure_reason",
        "change_summary",
        "validation_summary",
    }
    assert all(
        field["type"] == "string" and field["maxLength"] <= 1000
        for field in schema["properties"].values()
    )
