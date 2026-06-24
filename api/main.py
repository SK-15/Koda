import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from api.routes.run import router as run_router
from api.routes.status import router as status_router
from api.routes.resume import router as resume_router
from api.routes.coordinate import router as coordinate_router
from api.routes.projects import router as projects_router
from api.routes.chats import router as chats_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import agent.graph as agent_graph
    from agent.graph import build_graph
    from infra.redis_client import get_redis, close_redis

    app.state.redis = await get_redis()
    agent_graph.compiled_graph = build_graph()

    yield
    await close_redis()


app = FastAPI(
    title="KODA",
    description="Knowledge oriented Developer Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(run_router, prefix="/api/v1")
app.include_router(status_router, prefix="/api/v1")
app.include_router(resume_router, prefix="/api/v1")
app.include_router(coordinate_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(chats_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
