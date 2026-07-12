# Web Search Tool — Design Spec

**Date:** 2026-07-12
**Status:** Approved
**Execution:** Claude implements end-to-end (explicit override of the default
project pairing rule for this task).

## Goal

Give the agent a `web_search` tool backed by Tavily, available on every
execution path (local/REST autonomous runs and WS client-proxy sessions),
without requiring the client to hold or forward a Tavily API key.

## Problem

koda has two workspace backends behind `WorkspaceBackend.dispatch()`:

- `LocalFsBackend` — runs every registered tool in-process. A newly
  registered tool is automatically available here.
- `ClientProxyBackend` — proxies every call to the connected client over
  WebSocket; the client executes it against its own environment. It only
  proxies tool names the client declared in its `hello` frame's
  `capabilities` list (`tools/backends/proxy.py:30-36`).

A search tool needs a server-held secret (`TAVILY_API_KEY`). The client
can never execute it, so it can never appear in `capabilities`, so today's
`ClientProxyBackend` would never bind it to the LLM — `api/routes/ws.py`
sets `enabled_tools` directly from the raw `capabilities` list
(`ws.py:93`, `ws.py:148`).

## Decision

`web_search` is a normal registered tool that always executes on koda's
server, regardless of which backend is active.

- **`LocalFsBackend`**: needs no change. It already runs any registered
  tool in-process against `all_tools()`.
- **`ClientProxyBackend`**: gets a `SERVER_SIDE_TOOLS = {"web_search"}`
  module-level constant in `tools/backends/proxy.py`.
  - `dispatch()` checks `tool_name in SERVER_SIDE_TOOLS` first and calls
    the tool directly (via `tools.registry.get_tool`), bypassing the
    proxy-to-client path entirely.
  - `available_tools()` returns `set(self._capabilities) | SERVER_SIDE_TOOLS`
    instead of just `self._capabilities`, so the LLM gets bound to it.
- **`api/routes/ws.py`**: the one call site that seeds `enabled_tools` for
  a fresh thread (`ws.py:148`, inside `_drive_run`) switches from passing
  the raw `capabilities` list to `backend.available_tools()`. This makes
  the backend the single source of truth for what's callable, instead of
  duplicating that logic in the route handler. `_build_state`'s signature
  is unchanged — it still just takes a `tools: list[str]` parameter.

This keeps `WorkspaceBackend` as the seam that already exists for "where
does this tool actually run" and doesn't leak Tavily-specific knowledge
into `ws.py` or the graph.

## Tool implementation

New file `tools/web_search_tool.py`, following the exact shape of
`tools/file_read_tool.py`:

```python
from pydantic import BaseModel
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
        ...
```

- **Client**: `tavily-python` SDK directly (`TavilyClient(api_key=...).search(query, max_results=max_results)`)
  — not the `langchain-community` wrapper, to match koda's existing pattern
  of thin direct-call tools (see `bash_tool.py`, `file_read_tool.py`; none
  of them wrap a LangChain tool class).
- **API key**: read from `os.environ["TAVILY_API_KEY"]` inside `execute()`,
  not at import time (mirrors how other server-held secrets are read
  lazily elsewhere in the codebase, e.g. `llm/model_config.py`).
- **Output formatting**: each result rendered as `title / url / content`
  lines, joined with blank lines between results, then passed through the
  existing `trim_tool_output(text, max_tokens=2000)` helper — same cap
  `file_read` and `grep` use.
- **Risk/approval**: `risk_level = "low"`, `requires_approval = False`.
  `agent/routing.py:17` only gates on `requires_approval`, so this tool
  never triggers the human-approval interrupt.

## Registration

`tools/registry.py` gets one more import + `_register()` call, identical
to the other four tools. This alone makes `web_search` available on the
local/REST path: `llm/router.get_llm(enabled_tools=None)` binds
`all_tools()` unfiltered (`llm/router.py:66-73`), and `run.py`/`chats.py`
never pass `enabled_tools`, so no further change is needed there.

## Error handling

- **Missing `TAVILY_API_KEY`**: `execute()` returns
  `"Error : TAVILY_API_KEY not configured"` (matches `file_read`'s
  `"Error : file not found"` style) rather than raising. Gives the LLM a
  clear, final signal instead of a stack trace to retry against.
- **Tavily API failure** (network error, non-2xx, timeout): caught inside
  `execute()`, returned as `f"Error : search failed - {e}"`. Same
  reasoning — a string the LLM can read and decide to retry or give up,
  rather than an unhandled exception that `tool_node.py`'s outer
  try/except would turn into a generic error anyway.
- **Empty/whitespace query**: rejected by `validate_input`, matching the
  pattern `file_read` uses for path validation.

## Config

- New dependency: `tavily-python` in `requirements.txt` and
  `pyproject.toml` (same dual-file update pattern used for `langfuse` and
  `langchain`).
- New env var: `TAVILY_API_KEY`, documented in `.env.example`. (Already
  present in the developer's local `.env`, not committed.)

## Testing

- Unit tests for `WebSearchTool.execute()` with a mocked `TavilyClient`
  (patch the class where it's imported in `web_search_tool.py`, same
  approach used for `CallbackHandler` in `test_langfuse_client.py`):
  success path (formatted output, trimmed), missing-key path, API-error
  path, empty-query validation path.
- Unit tests for `ClientProxyBackend`:
  - `available_tools()` includes `"web_search"` even when absent from
    `capabilities`.
  - `dispatch("web_search", ...)` calls the tool in-process and does
    **not** call `request_fn` (proves it bypasses the proxy path).
  - `dispatch()` for a non-server-side tool still behaves exactly as
    before (proxies via `request_fn`, raises on unsupported tool).
- One `ws.py` integration-style test (extending the `TestWsEndToEnd`
  class pattern already in `tests/test_koda.py`) confirming a proxy
  session's `enabled_tools` includes `web_search` even when the client's
  `hello.capabilities` doesn't mention it.

## Files touched

| File | Change |
|---|---|
| `tools/web_search_tool.py` | new — tool implementation |
| `tools/registry.py` | register `WebSearchTool` |
| `tools/backends/proxy.py` | add `SERVER_SIDE_TOOLS`, special-case `dispatch()`, union in `available_tools()` |
| `api/routes/ws.py` | seed `enabled_tools` from `backend.available_tools()` instead of raw `capabilities` |
| `requirements.txt`, `pyproject.toml` | add `tavily-python` |
| `.env.example` | add `TAVILY_API_KEY` |
| `tests/test_koda.py` | proxy backend + ws integration tests |
| new `tests/test_web_search_tool.py` | tool unit tests |

## Out of scope

- Rate limiting / caching search results.
- Configurable search providers (Tavily only, no abstraction layer).
- Surfacing search result citations/sources distinctly from the raw text
  blob returned to the LLM.
- Any change to `LocalFsBackend` (already handles this correctly by
  construction).
