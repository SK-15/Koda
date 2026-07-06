# Langfuse Observability — Design

## Goal
Add trace-level observability to the koda agent graph (planner → plan_review → agent → tools → summarize → human loop) using Langfuse Cloud, without disturbing existing cost/budget enforcement.

## Deployment
Langfuse Cloud (managed), not self-hosted.

## Architecture
Wire a Langfuse `CallbackHandler` into the existing graph invocation config in `api/routes/ws.py`, at both `astream_events` call sites (~line 61, ~line 124). This is the single choke point where the compiled LangGraph graph is invoked per WS turn — no per-node instrumentation needed, since LangGraph propagates callbacks to every node automatically (planner, plan_review, agent, tools, summarize, human).

```python
config = {
    "configurable": {"thread_id": thread_id, "backend": backend},
    "callbacks": [langfuse_handler],
}
```

Resulting trace shape (one trace per WS message turn):

```
Trace: WS message turn
├─ planner (if plan_mode)
├─ plan_review
├─ agent (LLM call, tokens, latency)
├─ tools (bash/grep/file_read + input/output)
├─ summarize (if triggered)
└─ agent (loop continues...)
```

## Handler lifecycle
A new `CallbackHandler` instance is built per WS request/turn (not an app-level singleton), so that trace tags are always correct for the current caller:

- `user_id` = `state["user_id"]`
- `session_id` = `thread_id` (chat id) — groups every turn of one conversation into one Langfuse session
- `metadata` = `{"org_id": state["org_id"], "project_id": project.id}`

## Coexistence with existing cost tracking
`llm/cost_tracker.py` and the `cost_usd >= budget_limit_usd` gate in `agent/nodes/agent_node.py` are unchanged. That remains the runtime enforcement path for stopping execution on budget. Langfuse is purely observational — it reads token/cost data emitted by the langchain-anthropic callback independently, and is not consulted for any runtime decision.

## Configuration
New env vars (added to `.env` and `.env.example`, loaded via the existing `load_dotenv()` call in `api/main.py`):

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST` (default `https://cloud.langfuse.com`)

New dependency: `langfuse` added to `pyproject.toml`.

## Files touched
- `pyproject.toml` — add `langfuse` dependency
- `.env.example` — 3 new vars
- `api/routes/ws.py` — construct handler, append to `config["callbacks"]` at both graph-invocation call sites

No changes to `agent/`, `tools/`, or `llm/cost_tracker.py`.

## Out of scope
- Replacing `cost_tracker.py` with Langfuse-sourced cost data
- Self-hosting Langfuse
- Langfuse prompt-management features
- Langfuse datasets/evaluation features (tracked separately as the "output evaluation" item — benefits from this work being done first, but is its own design)
