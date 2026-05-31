# CLAUDE.md — Code Agent Architecture & Build Plan

> This file is the single source of truth for building a production-grade AI code agent
> inspired by Claude Code's internals. Any LLM or engineer working in this repo should
> read this file first. It defines architecture, component responsibilities, constraints,
> and build phases. Do not deviate from these decisions without updating this file.

---

## 1. What we are building

A **self-hosted, multi-tenant AI code agent** that can:

- Read, write, and reason about a codebase end-to-end
- Execute shell commands in a sandboxed environment
- Maintain memory across sessions without a vector store
- Spawn sub-agents for parallelisable tasks
- Run as a REST API consumed by a web UI or CLI
- Scale to thousands of concurrent users

**Codename:** `KODA` (Knowledge-Oriented Developer Agent)

**Not** a chat wrapper. Not a LangChain demo. A production harness.

---

## 2. Core design philosophy

These are non-negotiable. Every implementation decision flows from these.

```
1. Structure over prompting
   Safety and correctness come from architecture, not from asking the LLM nicely.
   Permission gates, schema validation, and execution sandboxes enforce behaviour.
   Never rely on the model to self-police.

2. Isolation is the primitive
   Every tool, every sub-agent, every tenant runs in an isolated context.
   No shared mutable state. A failure in one tool must not affect another.

3. Context is a budget, not a buffer
   Every token in context has a cost. The agent retrieves what it needs,
   when it needs it. It does not accumulate. It does not guess.

4. Memory maintains itself
   The agent writes, updates, and reconciles its own memory files.
   No manual maintenance between sessions. Self-healing by design.

5. Workers are stateless
   All persistent state lives in Redis (hot) or Postgres (cold).
   Any worker can resume any session. Adding machines is linear.
```

---

## 3. Technology stack

| Layer              | Technology                          | Why                                              |
|--------------------|-------------------------------------|--------------------------------------------------|
| Agent framework    | LangGraph                           | Graph-based, interrupt/resume, async checkpoints |
| LLM routing        | LiteLLM Router                      | Key pooling, multi-provider fallback             |
| Primary model      | claude-sonnet-4-5 (Anthropic)       | Best reasoning/speed tradeoff                    |
| Secondary model    | gpt-4o (OpenAI)                     | Fallback on Anthropic outage                     |
| Tertiary model     | gemini-1.5-pro (Google)             | Last resort                                      |
| API server         | FastAPI                             | Async, clean DI, fast                            |
| Task queue         | Celery + Redis broker               | Async execution, no HTTP timeouts                |
| Hot state          | Redis (AsyncRedisSaver)             | Sub-ms checkpoint reads/writes                   |
| Cold state         | Postgres                            | Durable storage, 90-day thread retention         |
| Execution sandbox  | Docker-in-Docker / gVisor           | Isolated bash execution per session              |
| Auth               | JWT (PyJWT)                         | org_id + user_id namespacing                     |
| Rate limiting      | Redis token bucket (Lua script)     | Per-user fairness, burst absorption              |
| Observability      | LangSmith + structured logging      | Per-node tracing, cost attribution per org       |
| Container runtime  | Kubernetes (min 3 warm replicas)    | Horizontal scale, no cold starts                 |
| Terminal UI        | Typer + Rich (CLI mode)             | Optional local CLI over the same API             |

---

## 4. Repository structure

```
koda/
├── CLAUDE.md                    ← you are here
│
├── agent/
│   ├── state.py                 ← AgentState TypedDict (single source of truth)
│   ├── graph.py                 ← Graph construction, edges, interrupt points
│   ├── nodes/
│   │   ├── agent_node.py        ← Main reasoning node
│   │   ├── tool_node.py         ← Tool execution + retry logic
│   │   ├── summarize_node.py    ← Context compression node
│   │   └── human_node.py        ← Interrupt + resume passthrough
│   └── routing.py               ← should_continue, should_summarize
│
├── tools/
│   ├── registry.py              ← Tool registration + permission mapping
│   ├── base.py                  ← BaseTool abstract class
│   ├── bash_tool.py             ← Shell execution (high-risk, sandboxed)
│   ├── file_read_tool.py        ← File reading (read-only)
│   ├── file_write_tool.py       ← File writing (scoped to workspace)
│   ├── grep_tool.py             ← Pattern search across codebase
│   ├── glob_tool.py             ← File tree navigation
│   └── mcp_bridge.py            ← MCP protocol bridge for external tools
│
├── memory/
│   ├── memory_manager.py        ← Reads/writes memory.md pointer index
│   ├── auto_dream.py            ← Background memory consolidation (idle)
│   └── schemas/
│       ├── memory.md            ← Pointer index template (per session)
│       └── CLAUDE.md            ← This file (project-level static config)
│
├── llm/
│   ├── router.py                ← LiteLLM multi-provider router
│   ├── context_builder.py       ← Assembles context from state + memory
│   └── cost_tracker.py          ← Token spend per org_id
│
├── coordinator/
│   ├── coordinator.py           ← Multi-agent orchestrator
│   ├── worker_spawner.py        ← Spawns sub-agents with scoped permissions
│   └── swarm_config.py          ← Parallelism limits, worker caps
│
├── api/
│   ├── main.py                  ← FastAPI app, lifespan, middleware
│   ├── routes/
│   │   ├── run.py               ← POST /run, POST /resume/{thread_id}
│   │   ├── status.py            ← GET /status/{task_id}
│   │   └── memory.py            ← GET/POST /memory/{thread_id}
│   └── middleware/
│       ├── auth.py              ← JWT extraction → org_id:user_id
│       └── rate_limit.py        ← Redis token bucket per user
│
├── infra/
│   ├── celery_app.py            ← Celery + Redis broker config
│   ├── redis_client.py          ← Shared async Redis client
│   ├── postgres.py              ← SQLAlchemy async session
│   └── sandbox.py               ← Docker sandbox lifecycle management
│
├── k8s/
│   ├── deployment.yaml          ← min 3 replicas, HPA config
│   ├── redis.yaml
│   └── postgres.yaml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── .env.example
├── pyproject.toml
└── docker-compose.yml           ← Local dev stack
```

---

## 5. Agent state schema

This is the single most important definition in the codebase.
**All nodes read from and write to this schema. Never add ad-hoc keys.**

```python
# agent/state.py

from typing import TypedDict

class AgentState(TypedDict):

    # ── Core conversation ──────────────────────────────────────────────
    messages: list              # Trimmed to last 20 on every resume.
                                # Full history lives in Postgres.

    summary: str                # Rolling compression of older turns.
                                # Populated by summarize_node.
                                # Prepended as SystemMessage on each LLM call.

    # ── Loop guard ────────────────────────────────────────────────────
    iterations: int             # Incremented at top of agent_node.
    max_iterations: int         # Set at run start. Hard ceiling. Default: 20.

    # ── Tool tracking ─────────────────────────────────────────────────
    tool_attempts: dict         # {tool_name: attempt_count}
                                # Reset to 0 on tool success.
                                # Triggers graceful_error at 3.

    last_error: str | None      # Surfaced to agent so it can adapt.
                                # Cleared after agent_node sees it.

    # ── Human-in-the-loop ─────────────────────────────────────────────
    approved: bool | None       # Set via /resume endpoint.
                                # None = not yet requested.

    awaiting_approval: bool     # True = graph is paused at human_node.

    # ── Memory ────────────────────────────────────────────────────────
    memory_index: str           # Contents of memory.md pointer index.
                                # Loaded at session start. Max 3000 tokens.

    workspace_path: str         # Absolute path to the sandboxed workspace.
                                # All file tools are scoped to this root.

    # ── Multi-tenancy ─────────────────────────────────────────────────
    org_id: str                 # Set from JWT. Never overridable by user.
    user_id: str                # Set from JWT.
    thread_id: str              # f"{org_id}:{user_id}:{uuid4()}"
                                # Used as Redis/Postgres key. Never raw user_id.

    # ── Cost tracking ─────────────────────────────────────────────────
    tokens_used: int            # Cumulative for this run.
    cost_usd: float             # Cumulative for this run.
    budget_limit_usd: float     # Per-run circuit breaker. Default: $2.00.
```

---

## 6. Tool system

### 6.1 Base contract

Every tool must implement this interface. No exceptions.

```python
# tools/base.py

from abc import ABC, abstractmethod
from pydantic import BaseModel

class ToolInput(BaseModel):
    pass  # Each tool defines its own input schema

class BaseTool(ABC):
    name: str                    # Unique identifier
    description: str             # Shown to the LLM in system prompt
    risk_level: str              # "low" | "medium" | "high"
    requires_approval: bool      # If True, triggers interrupt_before

    @abstractmethod
    async def execute(self, input: ToolInput, state: AgentState) -> str:
        """Execute the tool. Returns trimmed string output."""
        pass

    @abstractmethod
    def validate_input(self, input: ToolInput) -> bool:
        """Schema + safety validation before execution."""
        pass
```

### 6.2 Tool permission matrix

| Tool          | Risk    | Approval | Sandbox | Max output tokens |
|---------------|---------|----------|---------|-------------------|
| `file_read`   | low     | never    | no      | 2000              |
| `glob`        | low     | never    | no      | 500               |
| `grep`        | low     | never    | no      | 1000              |
| `file_write`  | medium  | on new   | no      | —                 |
| `bash`        | high    | always   | yes     | 2000              |
| MCP tools     | varies  | per-tool | no      | 1000              |

### 6.3 BashTool — the high-risk path

This is where things go wrong if not done right.

```
Execution flow:
  1. LLM generates bash command
  2. validate_input() runs 2500-line allowlist/blocklist check
     - Blocked: rm -rf /, curl to external hosts, env | grep KEY, etc.
     - Allowed: git, pytest, npm, pip, cat, ls, grep, sed, awk
  3. interrupt_before fires → human approval required
  4. On approval: spawn isolated Docker container scoped to workspace_path
  5. Execute with 30s timeout
  6. Capture stdout/stderr, trim to 2000 tokens
  7. Container destroyed after execution — no persistence

Validation rules live in tools/bash_validator.py.
Never inline validation logic in bash_tool.py.
```

### 6.4 Tool output trimming

Every tool output is trimmed before entering state.
The agent does not need the full API response. It needs the signal.

```python
def trim_tool_output(output: str, max_tokens: int) -> str:
    words = output.split()
    limit = int(max_tokens * 0.75)  # words ≈ tokens * 0.75
    if len(words) <= limit:
        return output
    return " ".join(words[:limit]) + f"\n... [trimmed — {len(words) - limit} words omitted]"
```

---

## 7. Memory architecture

Inspired directly by Claude Code's 3-layer system. No vector store.

### Layer 1 — CLAUDE.md (static, always in context)

This file. Project-level configuration, architecture, constraints.
Loaded at agent startup. Never modified at runtime.
Max size: 5000 tokens. If it grows beyond this, split into domain files
and reference them from memory.md.

### Layer 2 — memory.md (pointer index, per session)

Not a storage file. A navigation index.
Each line is a pointer to a domain-specific memory file.
Max 150 characters per line. Max 3000 tokens total.

```markdown
# memory.md — {thread_id}

## pointers
- [auth-decisions] ./memory/auth.md — JWT approach, org scoping decisions
- [db-schema] ./memory/schema.md — current table definitions, migration status
- [open-issues] ./memory/issues.md — known bugs, TODOs, blocked tasks
- [user-prefs] ./memory/prefs.md — user's preferred patterns, style rules
- [session-facts] ./memory/facts.md — verified facts from this session

## last-updated
{timestamp}
```

**Self-healing rule:** When the agent discovers a fact is wrong, it rewrites
the relevant domain file and updates the pointer in memory.md. No human needed.

### Layer 3 — Grep layer (live retrieval)

The codebase itself is external memory. The agent uses `grep_tool` and
`glob_tool` to retrieve what it needs when it needs it.

```
When should the agent grep vs use memory.md?

  memory.md → decisions, preferences, known issues, session facts
  grep       → actual code, current function signatures, file contents
```

### autoDream — idle memory consolidation

When the agent has been idle for >10 minutes, autoDream runs:

1. Load all domain memory files
2. Find contradictions (fact A vs fact B in different files)
3. Ask LLM to reconcile using a compact consolidation prompt
4. Rewrite the affected domain files
5. Update memory.md timestamps

This runs as a Celery beat task. It does not block the main agent loop.

```python
# memory/auto_dream.py

@celery_app.task
def run_auto_dream(thread_id: str):
    """Idle memory consolidation. Called by Celery beat after 10min inactivity."""
    memory = MemoryManager(thread_id)
    facts = memory.load_all_domains()
    contradictions = memory.find_contradictions(facts)
    if contradictions:
        reconciled = llm_router.completion(
            model="primary",
            messages=[{
                "role": "user",
                "content": RECONCILE_PROMPT.format(contradictions=contradictions)
            }],
            max_tokens=500,
        )
        memory.apply_reconciliation(reconciled)
```

---

## 8. LLM routing

### 8.1 Provider chain

```
Primary:   Anthropic claude-sonnet-4-5  (multiple API keys pooled)
Secondary: OpenAI gpt-4o                (on primary outage/saturation)
Tertiary:  Google gemini-1.5-pro        (last resort)
```

### 8.2 Key pool strategy

Add multiple API keys per provider to multiply effective TPM/RPM:

```python
# llm/router.py — add entries per key, same model_name
{
    "model_name": "primary",
    "litellm_params": {
        "model": "anthropic/claude-sonnet-4-5",
        "api_key": os.getenv("ANTHROPIC_KEY_A"),
        "rpm": 500,
        "tpm": 100_000,
    }
},
# Repeat for ANTHROPIC_KEY_B, ANTHROPIC_KEY_C...
```

### 8.3 Context assembly before every LLM call

Order of assembly (never deviate):
```
1. System prompt (role, capabilities, constraints)
2. CLAUDE.md content (project config)
3. memory_index (memory.md pointer index)
4. summary (rolling conversation compression)
5. last 20 messages (trimmed history)
6. last_error (if present — agent adapts strategy)
7. Current user message
```

Total must stay under 16,000 tokens. If it exceeds this, `summarize_node`
fires before the next LLM call.

### 8.4 Cost circuit breaker

```python
# In agent_node, before every LLM call:
if state["cost_usd"] >= state["budget_limit_usd"]:
    return {
        **state,
        "last_error": f"Budget limit ${state['budget_limit_usd']} reached. Stopping.",
        "messages": state["messages"] + [AIMessage(
            content="I've reached the run budget limit. Here's what I completed so far..."
        )]
    }
    # Route to END
```

---

## 9. Graph structure

```
                    ┌─────────────┐
                    │  START      │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ agent_node  │  ← iterations += 1, calls LLM
                    └──────┬──────┘
                           │
                    ┌──────▼──────────────────┐
                    │   should_continue()      │
                    │                          │
                    │  if iterations >= max    │──── "end" ──► END
                    │  if cost >= budget       │──── "end" ──► END
                    │  if tool_calls present   │──── "tools" ──►┐
                    │  else                    │──── "end" ──► END
                    └──────────────────────────┘               │
                                                               │
                    ┌──────────────────────────────────────────┘
                    │
             ┌──────▼──────┐
             │  tool_node  │  ← execute tools, retry up to 3x
             └──────┬──────┘
                    │
             ┌──────▼─────────────────────┐
             │   should_summarize()        │
             │                            │
             │  if tokens > 16000         │──── "summarize" ──►┐
             │  else                      │──── "agent" ────────┼──► back to agent_node
             └────────────────────────────┘                    │
                                                               │
             ┌─────────────────────────────────────────────────┘
             │
      ┌──────▼──────────┐
      │  summarize_node  │  ← compress history, keep last 4 msgs
      └──────┬───────────┘
             │
             └───────────────────────────────────────────► back to agent_node


Human approval path (when tool requires_approval = True):

      agent_node ──► human_node  (interrupt_before fires here)
                          │
                     [serialise to Redis, free worker]
                          │
                     [/resume endpoint called]
                          │
                     agent_node (continues from checkpoint)
```

### Routing functions

```python
# agent/routing.py

def should_continue(state: AgentState) -> str:
    if state["iterations"] >= state["max_iterations"]:
        return "end"
    if state["cost_usd"] >= state["budget_limit_usd"]:
        return "end"
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        tool_name = last.tool_calls[0]["name"]
        tool = registry.get(tool_name)
        if tool and tool.requires_approval and not state["approved"]:
            return "human"
        return "tools"
    return "end"

def should_summarize(state: AgentState) -> str:
    total = sum(len(str(m.content).split()) / 0.75 for m in state["messages"])
    return "summarize" if total > 16_000 else "agent"
```

---

## 10. Multi-agent coordinator

### When to use coordinator mode

Activate when the task is decomposable into independent parallel subtasks:
- "Refactor all API routes to use the new auth pattern" → one worker per route file
- "Write tests for every service" → one worker per service
- "Audit security across all endpoints" → parallelise by endpoint group

### Coordinator pattern

```python
# coordinator/coordinator.py

class Coordinator:
    """
    Receives a high-level task. Decomposes it into subtasks.
    Spawns worker agents with scoped tool permissions.
    Aggregates results.
    """

    async def run(self, task: str, workspace: str, max_workers: int = 5):
        # Step 1: decompose
        subtasks = await self.decompose(task)

        # Step 2: spawn workers (capped at max_workers)
        workers = [
            WorkerAgent(
                task=subtask,
                workspace=workspace,
                allowed_tools=["file_read", "grep", "glob"],  # scoped — no bash
                thread_id=f"worker:{uuid4()}"
            )
            for subtask in subtasks[:max_workers]
        ]

        # Step 3: run in parallel
        results = await asyncio.gather(*[w.run() for w in workers])

        # Step 4: aggregate
        return await self.aggregate(results)
```

### Worker scoping rules

Workers never get BashTool unless explicitly granted.
Default worker permissions: `file_read`, `grep`, `glob`.
Elevated worker permissions (requires coordinator flag): `file_write`.
BashTool is coordinator-only. Workers request it; coordinator approves.

---

## 11. Infrastructure

### 11.1 Thread namespacing

```python
# ALWAYS use this pattern. Never raw user_id.
thread_id = f"{org_id}:{user_id}:{uuid4()}"

# Redis keys follow the same pattern:
f"state:{thread_id}"      # hot state
f"result:{thread_id}"     # task result
f"rate:{org_id}:{user_id}" # rate limit bucket
```

### 11.2 State lifecycle

```
Active session  → Redis, TTL 30 min (auto-extends on activity)
Idle >5 min     → evict from Redis, persist to Postgres (keep in Redis with TTL 5 min)
Idle >24h       → Redis fully evicted, cold state in Postgres only
Resume          → Redis miss → lazy load from Postgres (last 20 messages only)
Expired >90d    → Postgres row deleted, notify user
```

### 11.3 Celery task structure

```python
# Two queues — do not mix:
# "agent"   → long-running graph executions (up to 10 min)
# "memory"  → short background tasks (autoDream, cost reporting)

@celery_app.task(queue="agent", bind=True, max_retries=2, time_limit=600)
def run_graph_task(self, thread_id, message, org_id, user_id): ...

@celery_app.task(queue="memory", bind=True)
def run_auto_dream(self, thread_id): ...
```

### 11.4 Kubernetes config (key settings)

```yaml
# k8s/deployment.yaml
spec:
  replicas: 3                      # Always-warm minimum — eliminates cold starts
  strategy:
    rollingUpdate:
      maxUnavailable: 0            # Zero downtime deploys
  resources:
    requests:
      memory: "1Gi"
      cpu: "500m"
    limits:
      memory: "2Gi"
      cpu: "2000m"

# HPA — scale on CPU AND queue depth
autoscaling:
  minReplicas: 3
  maxReplicas: 50
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          averageUtilization: 60
```

---

## 12. Security model

```
Principle of least privilege — everywhere.

1. Users can only access threads prefixed with their own org_id:user_id.
   Checked in every API endpoint. Never trust the client.

2. File tools are scoped to workspace_path.
   Any path traversal attempt (../../etc/passwd) is rejected by validate_input().
   Rule: resolved_path.startswith(workspace_path) — if False, reject.

3. BashTool runs in an isolated Docker container.
   Container has no network access (--network none).
   Container has no access to host filesystem except workspace_path (bind mount).
   Container is destroyed after each execution.

4. No credentials in state.
   API keys, tokens, secrets must never enter AgentState.messages.
   The agent may read .env files but must not print their contents.
   BashTool blocks: cat .env, echo $SECRET, env | grep KEY.

5. Prompt injection defence.
   User-supplied file contents that enter the context are wrapped:
   <user_file_content> ... </user_file_content>
   The system prompt instructs the agent to treat this as data, not instructions.

6. Audit log — append-only.
   Every tool execution written to: audit_logs table in Postgres.
   Schema: (timestamp, org_id, user_id, thread_id, tool_name, input_hash, output_hash)
   Input and output are hashed, not stored raw (privacy + size).
```

---

## 13. Build phases

### Phase 1 — Local single-user (2 weeks)

Goal: a working agent on one machine, one user, no infra.

```
✓ AgentState defined
✓ agent_node, tool_node, summarize_node implemented
✓ file_read, grep, glob tools
✓ memory.md pointer system (read/write)
✓ LiteLLM router (single key, single provider)
✓ FastAPI: POST /run, GET /status
✓ Celery + Redis locally (docker-compose)
✓ Basic test: "explain this codebase to me"
```

### Phase 2 — BashTool + sandbox (1 week)

Goal: safe shell execution.

```
✓ BashTool with Docker sandbox
✓ bash_validator.py (allowlist/blocklist)
✓ interrupt_before + /resume endpoint
✓ human_node in graph
✓ Test: "run the test suite and fix failing tests"
```

### Phase 3 — Multi-tenancy + scale (2 weeks)

Goal: multiple users, multiple orgs, deployed on K8s.

```
✓ JWT auth middleware
✓ Thread namespacing (org_id:user_id:uuid)
✓ Redis token bucket rate limiter
✓ Postgres cold storage + lazy load on resume
✓ State TTL lifecycle (active → idle → expired)
✓ Kubernetes deployment (min 3 replicas)
✓ Cost circuit breaker
✓ LangSmith tracing per request
```

### Phase 4 — Memory system (1 week)

Goal: sessions that improve over time.

```
✓ memory.md pointer index (full read/write/reconcile)
✓ Domain memory files (auto-created by agent)
✓ autoDream Celery beat task
✓ Memory loaded into context at session start
✓ Self-healing: agent detects and corrects stale facts
```

### Phase 5 — Multi-agent coordinator (2 weeks)

Goal: parallel task execution.

```
✓ Coordinator class
✓ WorkerAgent with scoped permissions
✓ Task decomposition prompt
✓ Result aggregation
✓ Worker cap enforcement (max 5 parallel)
✓ Test: "refactor all API endpoints to use async/await"
```

### Phase 6 — Hardening (ongoing)

```
✓ Prompt injection defence (file content wrapping)
✓ Audit log table
✓ Provider fallback testing (simulate outages)
✓ Load test at 1000 concurrent sessions
✓ P99 latency under 3s for all endpoints
✓ KAIROS-style daemon (background agent, optional)
```

---

## 14. What NOT to build (deliberate omissions)

```
✗ Vector store for memory
  Reason: grep + pointer index is faster, simpler, works offline.
  Add vector store only if semantic search across memory files is needed
  (Phase 6+ decision).

✗ Sticky sessions / session affinity in K8s
  Reason: stateless workers + Redis state eliminates the need.
  Session affinity is a smell that state is leaking into workers.

✗ Sync HTTP for agent execution
  Reason: agents run for minutes. HTTP timeouts at 30-60s.
  Everything goes through Celery. The API only accepts and polls.

✗ Per-tool LLM calls for validation
  Reason: use schema validation and allowlists. Fast, deterministic, cheap.
  LLM-based validation adds latency and can itself be prompt-injected.

✗ Storing raw message content in audit logs
  Reason: privacy, GDPR, size. Hash inputs and outputs only.
  Full replay can be reconstructed from Postgres checkpoints if needed.
```

---

## 15. Key environment variables

```bash
# LLM providers
ANTHROPIC_KEY_A=sk-ant-...
ANTHROPIC_KEY_B=sk-ant-...
OPENAI_KEY=sk-...
GOOGLE_KEY=...

# Infrastructure
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER=redis://localhost:6379/1
CELERY_BACKEND=redis://localhost:6379/2
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/koda

# Auth
JWT_SECRET=change-me-in-production

# Observability
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=koda-production

# Limits
DEFAULT_MAX_ITERATIONS=20
DEFAULT_BUDGET_LIMIT_USD=2.00
DEFAULT_THREAD_TTL_MINUTES=30
THREAD_COLD_STORAGE_DAYS=90

# Coordinator
MAX_WORKER_AGENTS=5
COORDINATOR_MODE_ENABLED=false   # feature flag — enable per org
```

---

## 16. Testing strategy

```
Unit tests:    Every tool's validate_input() — 100% coverage required.
               Every routing function (should_continue, should_summarize).
               Memory manager read/write/reconcile.

Integration:   Full graph run end-to-end with mocked LLM.
               Interrupt + resume flow.
               Redis TTL lifecycle (active → idle → cold → resume).
               Rate limiter under burst.

E2E:           "Read this repo and explain the architecture" → assert non-empty summary.
               "Write a test for this function" → assert runnable pytest output.
               "Run tests and fix failures" → multi-turn with BashTool approval.

Load:          1000 concurrent sessions, measure P50/P99 latency.
               P50 target: <500ms. P99 target: <3s.
               Simulate provider outage → assert fallback activates within 1 retry.
```

---

## 17. Glossary

| Term            | Definition                                                         |
|-----------------|--------------------------------------------------------------------|
| thread_id       | Namespaced session key: `org_id:user_id:uuid`. Used everywhere.    |
| hot state       | Redis — active/recent sessions, sub-ms access                      |
| cold state      | Postgres — all sessions, durable, paginated on load                |
| memory.md       | Pointer index file per session — references, not storage           |
| autoDream       | Background idle task that reconciles memory contradictions         |
| KAIROS          | Planned: persistent daemon that survives terminal close             |
| ULTRAPLAN       | Planned: cloud offload for large-scale refactoring tasks           |
| coordinator     | Orchestrator agent that spawns and manages worker sub-agents       |
| worker          | Sub-agent with scoped (limited) tool permissions                   |
| context budget  | Max 16,000 tokens assembled per LLM call                           |
| circuit breaker | Cost guard — halts run when cumulative spend >= budget_limit_usd   |

---

*Last updated: 2026-05-29*
*Maintained by: KODA architecture team*
*Next review: Before Phase 3 kickoff*