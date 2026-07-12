# Web Search Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `web_search` tool (Tavily-backed) that works on every execution path — local/REST autonomous runs and WS client-proxy sessions — without the client ever holding the Tavily API key.

**Architecture:** `web_search` is a normally-registered `BaseTool`, always executed on koda's own server. `LocalFsBackend` needs no change (it already runs any registered tool in-process). `ClientProxyBackend` gets a `SERVER_SIDE_TOOLS` set; `dispatch()` special-cases those names to run in-process instead of proxying to the client, and `available_tools()` unions them into what it advertises. `api/routes/ws.py` switches to using `backend.available_tools()` (instead of the raw client-declared `capabilities`) as the source of truth for `enabled_tools`.

**Tech Stack:** `tavily-python` SDK (direct call, no LangChain wrapper), pydantic input models, pytest + pytest-asyncio, `monkeypatch` for mocking `TavilyClient`.

## Global Constraints

- Dependency: `tavily-python>=0.7.0` (latest on PyPI as of 2026-07-12 is 0.7.26).
- Env var: `TAVILY_API_KEY`, read lazily inside `execute()`, never at import time.
- Tool contract: `name="web_search"`, `risk_level="low"`, `requires_approval=False`.
- Input shape: `query: str`, `max_results: int = 5`.
- Output: `title / url / content` per result, blank-line separated, passed through `trim_tool_output(text, max_tokens=2000)` (same helper `file_read`/`grep` use — imported from `tools.base`).
- Errors return strings (`"Error : ..."`), never raise — matches `file_read`'s `"Error : file not found"` style.
- `TavilyClient(...).search(...)` is a blocking `requests`-based call; run it via `asyncio.to_thread` inside the async `execute()` so it doesn't block the event loop.
- Tavily's actual response shape (confirmed via live call): `{"query": ..., "results": [{"title": ..., "url": ..., "content": ..., "score": ..., "raw_content": ...}, ...]}`.

---

### Task 1: `WebSearchTool` + registration

**Files:**
- Create: `tools/web_search_tool.py`
- Modify: `tools/registry.py`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `tests/test_koda.py` (one-line addition to `TestRegistry.test_all_tools_registered`)
- Test: `tests/test_web_search_tool.py`

**Interfaces:**
- Produces: `tools.web_search_tool.WebSearchTool` (class), `tools.web_search_tool.WebSearchInput` (pydantic model with `query: str`, `max_results: int = 5`). Both are imported by `tools/registry.py`. `WebSearchTool().execute(input, state)` returns `str`, matching `BaseTool.execute` from `tools/base.py`.

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml`, inside `dependencies = [...]`, add after the `"pyjwt>=2.8.0",` line:

```toml
    "pyjwt>=2.8.0",

    # Search
    "tavily-python>=0.7.0",
]
```

Edit `requirements.txt`. It currently ends with:

```
# Auth
pyjwt>=2.8.0

# Dev
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

Insert a new `# Search` section right after the `# Auth` block (before `# Dev`):

```
# Auth
pyjwt>=2.8.0

# Search
tavily-python>=0.7.0

# Dev
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

Install it:

```bash
.venv/bin/pip install "tavily-python>=0.7.0"
```

- [ ] **Step 2: Add `TAVILY_API_KEY` to `.env.example`**

Add a new section at the end of `.env.example`:

```
# Search
TAVILY_API_KEY=
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_web_search_tool.py`:

```python
import pytest

from tools.web_search_tool import WebSearchTool, WebSearchInput


class FakeTavilyClient:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query, max_results=None):
        return {
            "results": [
                {"title": "Result One", "url": "https://example.com/1", "content": "First snippet."},
                {"title": "Result Two", "url": "https://example.com/2", "content": "Second snippet."},
            ]
        }


class EmptyTavilyClient:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query, max_results=None):
        return {"results": []}


class ExplodingTavilyClient:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query, max_results=None):
        raise RuntimeError("boom")


class TestWebSearchTool:
    def setup_method(self):
        self.tool = WebSearchTool()

    def test_tool_metadata(self):
        assert self.tool.name == "web_search"
        assert self.tool.risk_level == "low"
        assert self.tool.requires_approval is False

    def test_validate_input_rejects_empty_query(self):
        assert self.tool.validate_input(WebSearchInput(query="   "), "/ws") is False

    def test_validate_input_accepts_query(self):
        assert self.tool.validate_input(WebSearchInput(query="x"), "/ws") is True

    @pytest.mark.asyncio
    async def test_execute_formats_results(self, monkeypatch):
        import tools.web_search_tool as wst
        monkeypatch.setattr(wst, "TavilyClient", FakeTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="langgraph"), {"workspace_path": "/ws"}
        )

        assert "Result One" in result
        assert "https://example.com/1" in result
        assert "First snippet." in result
        assert "Result Two" in result

    @pytest.mark.asyncio
    async def test_execute_no_results(self, monkeypatch):
        import tools.web_search_tool as wst
        monkeypatch.setattr(wst, "TavilyClient", EmptyTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="zzzznomatch"), {"workspace_path": "/ws"}
        )

        assert result == "No results found."

    @pytest.mark.asyncio
    async def test_execute_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        result = await self.tool.execute(
            WebSearchInput(query="langgraph"), {"workspace_path": "/ws"}
        )

        assert result == "Error : TAVILY_API_KEY not configured"

    @pytest.mark.asyncio
    async def test_execute_search_failure(self, monkeypatch):
        import tools.web_search_tool as wst
        monkeypatch.setattr(wst, "TavilyClient", ExplodingTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="langgraph"), {"workspace_path": "/ws"}
        )

        assert result == "Error : search failed - boom"

    @pytest.mark.asyncio
    async def test_execute_empty_query(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="   "), {"workspace_path": "/ws"}
        )

        assert result == "Error : query must not be empty"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_search_tool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.web_search_tool'`

- [ ] **Step 5: Implement `tools/web_search_tool.py`**

```python
import asyncio
import os

from pydantic import BaseModel
from tavily import TavilyClient

from tools.base import BaseTool, trim_tool_output


class WebSearchInput(BaseModel):
    query: str
    max_results: int = 5


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current information. Returns titles, URLs, and snippets."
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: WebSearchInput, workspace_path: str) -> bool:
        return bool(input.query.strip())

    async def execute(self, input: WebSearchInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : query must not be empty"

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return "Error : TAVILY_API_KEY not configured"

        try:
            response = await asyncio.to_thread(
                TavilyClient(api_key=api_key).search,
                input.query,
                max_results=input.max_results,
            )
        except Exception as e:
            return f"Error : search failed - {e}"

        results = response.get("results", [])
        if not results:
            return "No results found."

        formatted = "\n\n".join(
            f"{r['title']}\n{r['url']}\n{r['content']}" for r in results
        )
        return trim_tool_output(formatted, max_tokens=2000)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_search_tool.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Register the tool**

Edit `tools/registry.py`:

```python
from tools.file_read_tool import FileReadTool, FileReadInput
from tools.file_write_tool import FileWriteTool, FileWriteInput
from tools.grep_tool import GrepTool, GrepInput
from tools.glob_tool import GlobTool, GlobInput
from tools.bash_tool import BashTool, BashInput
from tools.web_search_tool import WebSearchTool, WebSearchInput

_REGISTRY: dict = {}


def _register(tool_instance, input_class):
    tool_instance.input_class = input_class
    _REGISTRY[tool_instance.name] = tool_instance


_register(FileReadTool(), FileReadInput)
_register(FileWriteTool(), FileWriteInput)
_register(GrepTool(), GrepInput)
_register(GlobTool(), GlobInput)
_register(BashTool(), BashInput)
_register(WebSearchTool(), WebSearchInput)
```

- [ ] **Step 8: Extend the registry test**

Edit `tests/test_koda.py`, in `TestRegistry.test_all_tools_registered` (around line 137-143), add one line:

```python
    def test_all_tools_registered(self):
        from tools.registry import all_tools
        names = [t.name for t in all_tools()]
        assert "file_read" in names
        assert "grep" in names
        assert "glob" in names
        assert "bash" in names
        assert "web_search" in names
```

- [ ] **Step 9: Run full suite to verify no regressions**

Run: `.venv/bin/python -m pytest tests/test_web_search_tool.py tests/test_koda.py -k "Registry" -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add tools/web_search_tool.py tools/registry.py requirements.txt pyproject.toml .env.example tests/test_web_search_tool.py tests/test_koda.py
git commit -m "feat: add web_search tool backed by Tavily"
```

---

### Task 2: `ClientProxyBackend` server-side tool support

**Files:**
- Modify: `tools/backends/proxy.py`
- Modify: `tests/test_koda.py` (replace one existing test, add two new ones in `TestClientProxyBackend`)

**Interfaces:**
- Consumes: `tools.registry.get_tool(name)` (returns a `BaseTool` instance with `.input_class` and async `.execute(input, state)`, or `None`) — from Task 1 / existing `tools/registry.py`. `WebSearchTool` is registered under `"web_search"`.
- Produces: `tools.backends.proxy.SERVER_SIDE_TOOLS: set[str]` (currently `{"web_search"}`) and the updated `ClientProxyBackend.available_tools()` contract: returns the union of client capabilities and `SERVER_SIDE_TOOLS`, so callers (Task 3) can treat it as the full set of callable tool names for a proxy session.

- [ ] **Step 1: Write the failing tests**

In `tests/test_koda.py`, find `class TestClientProxyBackend` (around line 725-758). Replace the `test_available_tools_is_capabilities` test with:

```python
    def test_available_tools_includes_capabilities_and_server_side_tools(self):
        from tools.backends import ClientProxyBackend
        backend = ClientProxyBackend(None, capabilities=["file_read", "file_write"])
        assert set(backend.available_tools()) == {"file_read", "file_write", "web_search"}
```

Then add two new tests at the end of the same class, after `test_kind`:

```python
    @pytest.mark.asyncio
    async def test_dispatch_server_side_tool_executes_locally(self, monkeypatch):
        from tools.backends import ClientProxyBackend
        import tools.web_search_tool as wst

        class FakeTavilyClient:
            def __init__(self, *args, **kwargs):
                pass

            def search(self, query, max_results=None):
                return {"results": [{"title": "T", "url": "https://x", "content": "C"}]}

        monkeypatch.setattr(wst, "TavilyClient", FakeTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        called = {"proxy": False}

        async def fake_request(tool_name, tool_args):
            called["proxy"] = True
            return "should not be used"

        backend = ClientProxyBackend(fake_request, capabilities=["file_read"])
        result = await backend.dispatch(
            "web_search", {"query": "langgraph"}, {"workspace_path": "/ws"}
        )

        assert "T" in result
        assert called["proxy"] is False

    @pytest.mark.asyncio
    async def test_dispatch_non_server_side_tool_still_proxies(self):
        from tools.backends import ClientProxyBackend

        async def fake_request(tool_name, tool_args):
            return "client-side result"

        backend = ClientProxyBackend(fake_request, capabilities=["file_read"])
        result = await backend.dispatch("file_read", {"path": "x.py"}, {})
        assert result == "client-side result"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_koda.py -k "TestClientProxyBackend" -v`
Expected: `test_available_tools_includes_capabilities_and_server_side_tools` and `test_dispatch_server_side_tool_executes_locally` FAIL (current `available_tools()` returns only capabilities; `dispatch()` has no server-side branch).

- [ ] **Step 3: Implement the change**

Rewrite `tools/backends/proxy.py`:

```python
from typing import Awaitable, Callable

from tools.backends.base import WorkspaceBackend
from tools.registry import get_tool

# A transport: given (tool_name, tool_args) sends the request to the client that
# owns the workspace and resolves with the client's result string. The WS
# handler supplies this; it is the only thing that knows about the socket.
ToolRequestFn = Callable[[str, dict], Awaitable[str]]

# Tools that must always run on koda's own server, regardless of which
# client is connected, because they need server-held secrets (API keys)
# the client never has.
SERVER_SIDE_TOOLS = {"web_search"}


class ClientProxyBackend(WorkspaceBackend):
    """Proxies every tool call to the client that owns the workspace.

    koda holds no files. When the agent calls a tool, the call is serialized
    and sent to the client over a live connection; the client executes it
    against its own environment (terminal -> local disk + shell, browser ->
    in-browser virtual FS) and returns the result.

    Tools in SERVER_SIDE_TOOLS are the exception: they run in-process here
    instead, since they depend on secrets only the server holds.

    Transport is injected as `request_fn` so this class stays independent of
    the WebSocket layer (and unit-testable with a fake). `capabilities` is the
    set of tools the client advertised it can service on connect.
    """

    kind = "proxy"

    def __init__(self, request_fn: ToolRequestFn, capabilities: list[str]):
        self._request_fn = request_fn
        self._capabilities = list(capabilities)

    async def dispatch(self, tool_name: str, tool_args: dict, state: dict) -> str:
        if tool_name in SERVER_SIDE_TOOLS:
            tool = get_tool(tool_name)
            input_model = tool.input_class(**tool_args)
            return await tool.execute(input_model, state)

        if tool_name not in self._capabilities:
            raise ValueError(
                f"Client does not support tool '{tool_name}' "
                f"(advertised: {self._capabilities})"
            )
        return await self._request_fn(tool_name, tool_args)

    def available_tools(self) -> list[str]:
        return list(set(self._capabilities) | SERVER_SIDE_TOOLS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_koda.py -k "TestClientProxyBackend" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -q`
Expected: same pass/fail counts as the Task 1 baseline, plus the new tests passing (no new failures beyond the pre-existing 9 unrelated ones).

- [ ] **Step 6: Commit**

```bash
git add tools/backends/proxy.py tests/test_koda.py
git commit -m "feat: run server-side tools in-process from ClientProxyBackend"
```

---

### Task 3: Wire `ws.py` to use `backend.available_tools()`

**Files:**
- Modify: `api/routes/ws.py`
- Modify: `tests/test_koda.py` (add `_ScriptedWebSearchLLM` helper + one test to `TestWsEndToEnd`)

**Interfaces:**
- Consumes: `ClientProxyBackend.available_tools() -> list[str]` (Task 2) — already unions in `SERVER_SIDE_TOOLS`.
- Produces: no new symbols; `_drive_run`'s initial-state construction now sources `enabled_tools` from `backend.available_tools()` instead of the raw `capabilities` param, for both fresh-thread and (implicitly, via the same code path) any future thread-seeding needs.

- [ ] **Step 1: Write the failing test**

In `tests/test_koda.py`, near `class _ScriptedLLM` (around line 983), add a sibling class right after it:

```python
class _ScriptedWebSearchLLM:
    """First call asks for web_search, second call echoes the tool result."""

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        from langchain_core.messages import AIMessage, ToolMessage
        self.calls += 1
        meta = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "web_search", "args": {"query": "langgraph"}, "id": "call-1"}],
                usage_metadata=meta,
            )
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        echoed = tool_msgs[-1].content if tool_msgs else "<none>"
        return AIMessage(content=f"final: {echoed}", usage_metadata=meta)
```

Then add this test to `class TestWsEndToEnd`, after `test_proxied_tool_round_trip`:

```python
    def test_server_side_tool_runs_without_client_capability(self, monkeypatch):
        import agent.nodes.agent_node as an
        import agent.graph as ag
        import tools.web_search_tool as wst
        from agent.graph import build_graph

        class FakeTavilyClient:
            def __init__(self, *args, **kwargs):
                pass

            def search(self, query, max_results=None):
                return {"results": [{"title": "Answer", "url": "https://x", "content": "C"}]}

        monkeypatch.setattr(wst, "TavilyClient", FakeTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        scripted = _ScriptedWebSearchLLM()
        monkeypatch.setattr(an, "get_llm", lambda model=None, enabled_tools=None: scripted)

        async def fake_record_usage(**kwargs):
            return 0.0

        monkeypatch.setattr(an, "record_usage", fake_record_usage)
        monkeypatch.setattr(ag, "compiled_graph", build_graph())

        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from api.routes.ws import router as ws_router

        app = FastAPI()
        app.include_router(ws_router, prefix="/api/v1")

        with TestClient(app).websocket_connect("/api/v1/ws/run") as ws:
            # client declares only file_read - NOT web_search
            ws.send_json({"type": "hello", "capabilities": ["file_read"]})
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "message", "message": "search something"})

            # web_search runs server-side directly - no tool_request round trip
            done = ws.receive_json()
            assert done["type"] == "done"
            assert "Answer" in done["result"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_koda.py -k "test_server_side_tool_runs_without_client_capability" -v`
Expected: FAIL — the client receives a `tool_request` for `web_search` instead of `done`, because `enabled_tools` is currently seeded from the raw `capabilities` list (`["file_read"]`), so the LLM node never even offers `web_search` as... actually the scripted LLM always requests it regardless of binding, so instead the failure will surface at `tool_node`: `"Unknown tool: 'web_search'"` gets appended as a `ToolMessage`, and the run proceeds to a `done` event whose `result` does NOT contain `"Answer"` (it'll contain the `"Unknown tool"` echo). Confirm the assertion `"Answer" in done["result"]` fails.

- [ ] **Step 3: Implement the change**

In `api/routes/ws.py`, in `_drive_run` (around line 124-148), change the `else` branch:

```python
        else:
            inp = _build_state(frame, capabilities, thread_id, org_id, user_id)
```

to:

```python
        else:
            inp = _build_state(frame, backend.available_tools(), thread_id, org_id, user_id)
```

No other lines in this function change. `_build_state`'s signature (`frame, capabilities: list[str], thread_id, org_id, user_id`) is unchanged — it still just receives a list of tool names, now sourced from the backend instead of the raw hello frame.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_koda.py -k "test_server_side_tool_runs_without_client_capability" -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: same 9 pre-existing unrelated failures, all else passing (baseline count + all new tests from Tasks 1-3).

- [ ] **Step 6: Commit**

```bash
git add api/routes/ws.py tests/test_koda.py
git commit -m "feat: source WS enabled_tools from backend.available_tools()"
```
