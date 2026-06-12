import json
from infra.redis_client import get_redis

TTL = 3600  # results kept 1 hour


async def set_task_status(task_id: str, status: str, result: str = None):
    r = await get_redis()
    payload = {"status": status, "result": result}
    await r.set(f"task:{task_id}", json.dumps(payload), ex=TTL)


async def get_task_status(task_id: str) -> dict:
    r = await get_redis()
    raw = await r.get(f"task:{task_id}")
    if not raw:
        return {"status": "not_found", "result": None}
    return json.loads(raw)
