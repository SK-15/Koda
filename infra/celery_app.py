# ── Celery disabled for now — uncomment to re-enable ──────────────────────────
# import asyncio
# import os
# from celery import Celery
# from langchain_core.messages import HumanMessage
# from celery.schedules import crontab
#
# celery_app = Celery(
#     "koda",
#     broker=os.getenv("CELERY_BROKER", "redis://localhost:6379/1"),
#     backend=os.getenv("CELERY_BACKEND", "redis://localhost:6379/2"),
# )
#
# celery_app.conf.task_routes = {
#     "infra.celery_app.run_graph_task": {"queue": "agent"},
# }
#
# celery_app.conf.beat_schedule = {
#     "auto-dream-every-10-min": {
#         "task": "memory.auto_dream.run_auto_dream",
#         "schedule": crontab(minute="*/10"),
#         "args": [],
#     },
# }
#
# @celery_app.task(queue="agent", bind=True, max_retries=2, time_limit=600)
# def run_graph_task(
#     self,
#     thread_id: str,
#     message: str,
#     workspace_path: str,
#     org_id: str,
#     user_id: str,
#     budget_limit_usd: float,
#     max_iterations: int,
#     model: str = None,
# ):
#     from agent.graph import compiled_graph
#     initial_state = {
#         "messages": [HumanMessage(content=message)],
#         "summary": "",
#         "iterations": 0,
#         "max_iterations": max_iterations,
#         "tool_attempts": {},
#         "last_error": None,
#         "approved": None,
#         "awaiting_approval": False,
#         "memory_index": "",
#         "workspace_path": workspace_path,
#         "org_id": org_id,
#         "user_id": user_id,
#         "thread_id": thread_id,
#         "tokens_used": 0,
#         "cost_usd": 0.0,
#         "budget_limit_usd": budget_limit_usd,
#         "model": model,
#     }
#     config = {"configurable": {"thread_id": thread_id}}
#     result = asyncio.run(compiled_graph.ainvoke(initial_state, config=config))
#     last_message = result["messages"][-1]
#     return last_message.content
