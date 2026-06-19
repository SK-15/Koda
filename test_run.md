Terminal 1:
cd /home/saurav/Projects/koda/koda
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000

Terminal 2 — test:
# health
curl http://localhost:8000/health

# create workspace + test file
mkdir -p /tmp/koda-test
echo "def add(a, b): return a + b" > /tmp/koda-test/math.py

# run agent
curl -X POST http://localhost:8000/api/v1/run \
-H "Content-Type: application/json" \
-d '{"message": "Read math.py and explain what it does", "workspace_path": "/tmp/koda-test"}'

Copy task_id from response, then poll:
curl http://localhost:8000/api/v1/status/<task_id>

Activate venv first — paste any errors from pip install.