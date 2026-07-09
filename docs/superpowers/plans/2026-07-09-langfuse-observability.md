# Langfuse Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every WS agent run emits a Langfuse trace (nested per node: planner/agent/tools/summarize) tagged with user_id, session_id, and org_id, without touching the existing cost-budget gate.

**Architecture:** A single new module, `infra/langfuse_client.py`, exposes `build_trace_config(user_id, session_id, org_id) -> dict` — returns `{}` if Langfuse env vars aren't set (safe no-op for local dev), else returns a dict with a `callbacks` list and a `metadata` dict keyed the way the Langfuse SDK expects. `api/routes/ws.py` splats this into the one `config` dict already built per run in `_drive_run`, which LangGraph propagates to every node automatically.

**Tech Stack:** `langfuse` Python SDK v4 (`from langfuse.langchain import CallbackHandler`), LangGraph `config["callbacks"]`/`config["metadata"]`.

## Global Constraints

- Langfuse Cloud only (no self-host) — spec: `docs/superpowers/specs/2026-07-06-langfuse-observability-design.md`
- `llm/cost_tracker.py` and the `cost_usd >= budget_limit_usd` gate in `agent/nodes/agent_node.py` are NOT modified — Langfuse is observational only.
- Handler built fresh per run (not an app-level singleton) so tags are always correct for the caller.
- **Correction from spec:** the spec named `LANGFUSE_HOST` as the env var. The actual current Langfuse SDK (v4, confirmed against live docs) uses `LANGFUSE_BASE_URL`. This plan uses the real name.
- **Correction from spec:** the spec described tagging with `project_id`. `api/routes/ws.py`'s client-proxy flow (the only graph-invocation path this plan touches) has no `project_id` concept — `hello` frames carry only `org_id`/`user_id`/`thread_id`. This plan tags with `org_id` instead; `project_id` tagging is out of scope until a flow that has one is wired up.
- Only `api/routes/ws.py` is touched, per the approved spec — `api/routes/chats.py` and `api/routes/run.py` (the two other `get_compiled_graph()` call sites, both REST) are explicitly out of scope for this plan.

---

### Task 1: `infra/langfuse_client.py` — trace config builder

**Files:**
- Create: `infra/langfuse_client.py`
- Create: `tests/test_langfuse_client.py`
- Modify: `requirements.txt` (add dependency)
- Modify: `pyproject.toml` (add dependency, keep in sync with requirements.txt)
- Modify: `.env.example` (add 3 vars under existing `# Observability` section)

**Interfaces:**
- Produces: `infra.langfuse_client.is_configured() -> bool`
- Produces: `infra.langfuse_client.build_trace_config(user_id: str, session_id: str, org_id: str) -> dict` — `{}` when unconfigured, else `{"callbacks": [CallbackHandler()], "metadata": {"langfuse_user_id": ..., "langfuse_session_id": ..., "org_id": ...}}`

- [ ] **Step 1: Add the dependency**

Add to `requirements.txt`, under a new `# Observability` comment near the existing LLM/API sections (put it right after the `# LLM routing` block):

```
# Observability
langfuse>=4.0.0
```

Add the same line to `pyproject.toml`'s `dependencies` list (after the `litellm` line):

```toml
    # LLM routing (Phase 3)
    "litellm>=1.40.0",

    # Observability
    "langfuse>=4.0.0",

    # API server
```

Install it:

```bash
.venv/bin/pip install langfuse>=4.0.0
```

- [ ] **Step 2: Add env vars to `.env.example`**

Edit the existing `# Observability` section (it currently only has `LANGCHAIN_*` vars) to add:

```
# Observability
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=koda-production
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_langfuse_client.py`:

```python
import os
import pytest


class TestIsConfigured:
    def test_false_when_keys_missing(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        from infra.langfuse_client import is_configured
        assert is_configured() is False

    def test_false_when_only_public_key_set(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        from infra.langfuse_client import is_configured
        assert is_configured() is False

    def test_true_when_both_keys_set(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        from infra.langfuse_client import is_configured
        assert is_configured() is True


class TestBuildTraceConfig:
    def test_empty_dict_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        from infra.langfuse_client import build_trace_config
        assert build_trace_config("u1", "s1", "o1") == {}

    def test_callbacks_and_metadata_when_configured(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        import infra.langfuse_client as lc

        class DummyHandler:
            pass

        monkeypatch.setattr(lc, "CallbackHandler", DummyHandler)

        result = lc.build_trace_config("u1", "s1", "o1")

        assert len(result["callbacks"]) == 1
        assert isinstance(result["callbacks"][0], DummyHandler)
        assert result["metadata"] == {
            "langfuse_user_id": "u1",
            "langfuse_session_id": "s1",
            "org_id": "o1",
        }
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_langfuse_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'infra.langfuse_client'`

- [ ] **Step 5: Implement `infra/langfuse_client.py`**

```python
import os

from langfuse.langchain import CallbackHandler


def is_configured() -> bool:
    """Whether Langfuse credentials are present in the environment."""
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def build_trace_config(user_id: str, session_id: str, org_id: str) -> dict:
    """Callbacks + metadata to splat into a graph invocation config.

    Returns {} when Langfuse isn't configured (e.g. local dev without keys),
    so callers can unconditionally merge this in without guarding.
    """
    if not is_configured():
        return {}

    return {
        "callbacks": [CallbackHandler()],
        "metadata": {
            "langfuse_user_id": user_id,
            "langfuse_session_id": session_id,
            "org_id": org_id,
        },
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_langfuse_client.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pyproject.toml .env.example infra/langfuse_client.py tests/test_langfuse_client.py
git commit -m "feat: add Langfuse trace config builder"
```

---

### Task 2: Wire into `api/routes/ws.py`

**Files:**
- Modify: `api/routes/ws.py:123-125` (the `_drive_run` function's `config` construction)
- Modify: `tests/test_koda.py` (add one test to `TestWsEndToEnd`)

**Interfaces:**
- Consumes: `infra.langfuse_client.build_trace_config(user_id: str, session_id: str, org_id: str) -> dict` (from Task 1)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_koda.py`, inside `class TestWsEndToEnd` (after `test_proxied_tool_round_trip`, same indentation as the other methods in that class):

```python
    def test_trace_config_passed_to_graph_config(self, monkeypatch):
        import agent.nodes.agent_node as an
        import agent.graph as ag
        import api.routes.ws as ws_module
        from agent.graph import build_graph

        scripted = _ScriptedLLM()
        monkeypatch.setattr(an, "get_llm", lambda model=None, enabled_tools=None: scripted)

        async def fake_record_usage(**kwargs):
            return 0.0

        monkeypatch.setattr(an, "record_usage", fake_record_usage)
        monkeypatch.setattr(ag, "compiled_graph", build_graph())

        calls = []
        original = ws_module.build_trace_config

        def spy(user_id, session_id, org_id):
            calls.append((user_id, session_id, org_id))
            return original(user_id, session_id, org_id)

        monkeypatch.setattr(ws_module, "build_trace_config", spy)

        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from api.routes.ws import router as ws_router

        app = FastAPI()
        app.include_router(ws_router, prefix="/api/v1")

        with TestClient(app).websocket_connect("/api/v1/ws/run") as ws:
            ws.send_json({
                "type": "hello",
                "capabilities": ["file_read"],
                "org_id": "org-1",
                "user_id": "user-1",
            })
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            tid = ready["thread_id"]

            ws.send_json({"type": "message", "message": "read a.py"})
            req = ws.receive_json()
            ws.send_json({"type": "tool_result", "call_id": req["call_id"], "result": "X"})
            done = ws.receive_json()
            assert done["type"] == "done"

        assert calls == [("user-1", tid, "org-1")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_koda.py::TestWsEndToEnd::test_trace_config_passed_to_graph_config -v`
Expected: FAIL with `AttributeError: module 'api.routes.ws' has no attribute 'build_trace_config'`

- [ ] **Step 3: Wire it in**

In `api/routes/ws.py`, add the import near the top (with the other local imports):

```python
from agent.graph import get_compiled_graph
from infra.langfuse_client import build_trace_config
from infra.ws_session import WsToolBridge
from tools.backends import ClientProxyBackend
```

Then change the `config` line inside `_drive_run` (currently line 124):

```python
async def _drive_run(frame, backend, capabilities, org_id, user_id, send, bridge, thread_id):
    config = {
        "configurable": {"thread_id": thread_id, "backend": backend},
        **build_trace_config(user_id, thread_id, org_id),
    }
    graph = get_compiled_graph()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_koda.py::TestWsEndToEnd::test_trace_config_passed_to_graph_config -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite (regression check)**

Run: `.venv/bin/pytest tests/ -v`
Expected: all tests pass, including the pre-existing `TestWsEndToEnd` and `TestWsApprovalGate` tests (proves the config change doesn't break the human-approval pause/resume path, which reuses the same `config` dict).

- [ ] **Step 6: Commit**

```bash
git add api/routes/ws.py tests/test_koda.py
git commit -m "feat: attach Langfuse trace config to WS graph runs"
```

---

## Manual smoke check (not a pytest step)

The two tasks above prove the wiring is correct with a stubbed handler. To confirm real traces land in Langfuse Cloud:

1. Put real keys in `.env`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`.
2. Run the server, open a WS connection, send one `message` frame end to end.
3. Check the Langfuse Cloud dashboard — a trace should appear tagged with the `user_id`/`session_id`/`org_id` used, with nested spans for each graph node that ran.
