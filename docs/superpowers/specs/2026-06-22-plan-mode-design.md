# Plan Mode — Design Spec

**Date:** 2026-06-22
**Status:** Approved (design)
**Project rule:** The agent guides; the user writes the implementation code.

## Goal

Add a human-approved planning phase to the KODA agent. Before executing a task,
the agent produces an explicit, ordered step list, then pauses for human
approval (reusing the existing interrupt/resume mechanism). The user may edit the
plan before approving. On approval, the agent executes against the plan.

This is the first of two related subsystems. The second — Projects + Chats
(multi-turn threads, hybrid persistence) — is deferred to its own spec.

## Behavior

Selected flavor: **human-approved plan gate**.

```
START ──route_entry──> planner          (if plan_mode == True)
                  └──> agent            (if plan_mode == False)

planner ──> plan_review ──route_after_review──> agent   (plan_approved == True)
                                          └──> END       (plan_approved == False)

agent ──should_continue──> tools | human | end          (unchanged)
tools ──should_summarize──> summarize | agent           (unchanged)
summarize ──> agent                                     (unchanged)
human ──> END                                           (unchanged)
```

When `plan_mode` is False the graph behaves exactly as today (entry goes straight
to `agent`), so existing one-shot runs are unaffected.

## Components

### 1. State additions (`koda/agent/state.py`)

```python
plan: list[dict] | None        # [{"id": 1, "description": "...", "status": "pending"}]
plan_approved: bool | None     # None = not decided, True = execute, False = rejected
plan_mode: bool                # per-run flag from RunRequest
current_step: int              # index into plan (starts at 0)
```

`status` values for a step: `"pending" | "done" | "skipped"`.

### 2. Planner node (`koda/agent/nodes/planner_node.py`)

- Runs once at the start of a `plan_mode` run.
- Calls the LLM bound to a single **forced** `submit_plan` tool (reuses the tool-schema
  machinery in `koda/llm/router.py`). The tool's input schema is the plan structure.
- Produces only the step list — no file/bash tools available in this node.
- Writes the result to `state["plan"]`, sets `current_step = 0`, `plan_approved = None`.
- Planner prompt (intent): "Break the user's request into ordered, verifiable steps.
  Do not execute anything. Return the steps via `submit_plan`."

### 3. Plan review node (`koda/agent/nodes/plan_review_node.py`)

- Separate from the existing `human` node because its resume payload differs:
  it can carry an **edited plan**, not just an approval boolean.
- Sets `awaiting_approval = True` and surfaces the proposed plan to the caller.
- The graph is compiled with `interrupt_before=["plan_review", "human"]`.

### 4. Graph wiring (`koda/agent/graph.py`)

- Add nodes `planner` and `plan_review`.
- Replace the fixed entry point with a conditional edge from `START`:
  - `route_entry(state)` → `"planner"` if `state["plan_mode"]` else `"agent"`.
- `planner ──> plan_review`.
- `route_after_review(state)` → `"agent"` if `plan_approved` is True, else `END`.
- Compile with `interrupt_before=["plan_review", "human"]`.

### 5. Agent sees the plan (`koda/agent/nodes/agent_node.py`)

- `build_system_prompt` gains a new block when `state["plan"]` exists: render the plan
  as a checklist and mark the `current_step`. The agent executes against it.
- **MVP:** agent narrates progress in its messages; no step-tracking tool.
- **Later:** add an `update_plan` tool so step `status`/`current_step` advance
  explicitly (addresses the observability gap noted during review).

### 6. API changes

`koda/api/routes/run.py`
- `RunRequest`: add `plan_mode: bool = False`.
- Add `plan`, `plan_approved`, `plan_mode`, `current_step` to `initial_state`.

`koda/api/routes/resume.py`
- `ResumeRequest`: add optional `plan: list[dict] | None`.
- On resume: if an edited `plan` is provided, write it to state before continuing.
  Apply `plan_approved` from the request. Distinguish plan approval from tool approval
  (e.g. by which interrupt the thread is paused at / which flag is unset).
- Fix the import mismatch: `resume.py` imports module-level `compiled_graph` while
  `run.py` uses `get_compiled_graph()`. Align both on `get_compiled_graph()`.

## Micro-decisions (resolved)

- **Planner output:** forced `submit_plan` tool call (consistent with the rest of the
  codebase) rather than model structured-output.
- **Step tracking:** narrate-only for MVP; `update_plan` tool deferred.

## Out of scope (this spec)

- Projects + Chats data model and multi-turn chat endpoints (hybrid persistence) —
  separate spec, built next.
- Replanning loop (planner re-invoked on execution failure).
- Fixes to unrelated gaps surfaced during review (read-only sandbox blocking
  verification, full-file-overwrite-only `file_write`, hardcoded cost pricing,
  `should_continue` only inspecting `tool_calls[0]`). Tracked, not addressed here.

## Affected files

- `koda/agent/state.py` — new fields
- `koda/agent/nodes/planner_node.py` — new
- `koda/agent/nodes/plan_review_node.py` — new
- `koda/agent/graph.py` — wiring, conditional entry, interrupt_before
- `koda/agent/routing.py` — `route_entry`, `route_after_review`
- `koda/agent/nodes/agent_node.py` — plan block in system prompt
- `koda/llm/router.py` — `submit_plan` tool schema (if not derived from a tool class)
- `koda/api/routes/run.py` — `plan_mode` field + initial_state
- `koda/api/routes/resume.py` — edited-plan support, import fix
```
