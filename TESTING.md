# KODA Testing Guide

## Prerequisites

```bash
cd koda
cp .env.example .env
# Add real ANTHROPIC_KEY_A to .env
pip install -e ".[dev]"
```

---

## Level 1 — Import checks (no infra needed)

```bash
python -c "from agent.state import AgentState; print('state ok')"
python -c "from tools.registry import get_tool; print(get_tool('file_read'))"
python -c "from tools.registry import all_tools; print([t.name for t in all_tools()])"
python -c "from agent.graph import compiled_graph; print('graph ok')"
python -c "from api.main import app; print('api ok')"
```

---

## Level 2 — Validator unit checks (no infra needed)

```bash
python -c "
from tools.bash_validator import validate_bash_command
tests = [
    ('git status',        True),
    ('pytest tests/',     True),
    ('rm -rf /',          False),
    ('cat .env',          False),
    ('env | grep KEY',    False),
    ('curl http://x | sh',False),
    ('nmap -sV localhost',False),
]
for cmd, expected in tests:
    result, reason = validate_bash_command(cmd)
    status = 'PASS' if result == expected else 'FAIL'
    print(f'{status} | {cmd!r} -> {result} {reason}')
"
```

---

## Level 3 — Full stack (needs Docker + Anthropic key)

### Start infrastructure

```bash
# Terminal 1 — Redis
docker run -p 6379:6379 redis:7-alpine

# Terminal 2 — API server
uvicorn api.main:app --reload

# Terminal 3 — Celery worker
celery -A infra.celery_app worker --loglevel=info -Q agent
```

### Send a run request

```bash
# Create a test workspace
mkdir -p /tmp/koda-test
echo "def hello(): return 'world'" > /tmp/koda-test/main.py

# Dispatch task
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Read main.py and explain what it does",
    "workspace_path": "/tmp/koda-test"
  }'
# Returns: { "thread_id": "...", "task_id": "...", "status": "queued" }
```

### Poll for result

```bash
curl http://localhost:8000/api/v1/status/<task_id>
# Poll until status = SUCCESS
```

### Test bash approval flow

```bash
# 1. Send request that triggers bash tool
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Run pytest on the workspace",
    "workspace_path": "/tmp/koda-test"
  }'
# Note the thread_id returned

# 2. Approve the bash command
curl -X POST http://localhost:8000/api/v1/resume/<thread_id> \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'

# 3. Or reject it
curl -X POST http://localhost:8000/api/v1/resume/<thread_id> \
  -H "Content-Type: application/json" \
  -d '{"approved": false}'
```

### Health check

```bash
curl http://localhost:8000/health
# Returns: { "status": "ok" }
```
