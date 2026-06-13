import os                                                                                                                                                
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from api.routes.run import router as run_router
from api.routes.status import router as status_router
from api.routes.resume import router as resume_router
from api.routes.coordinate import router as coordinate_router

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    import agent.graph as agent_graph
    from agent.graph import build_graph
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    except ImportError:
        AsyncRedisSaver = None
    from infra.redis_client import get_redis, close_redis
    from infra.postgres import create_tables

    app.state.redis = await get_redis()
    await create_tables()

    if AsyncRedisSaver is not None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        checkpointer = AsyncRedisSaver.from_conn_string(redis_url)
        agent_graph.compiled_graph = build_graph(checkpointer=checkpointer)
    else:
        agent_graph.compiled_graph = build_graph()

    yield
    await close_redis()


app = FastAPI(
    title="KODA",
    description="Knowledge oriented Developer Agent",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(run_router, prefix="/api/v1")
app.include_router(status_router, prefix="/api/v1")
app.include_router(resume_router, prefix="/api/v1")
app.include_router(coordinate_router, prefix="/api/v1")
@app.get("/health")
async def health_check():
    return {"status": "ok"}


