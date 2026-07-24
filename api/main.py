import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from api.routes.run import router as run_router
from api.routes.status import router as status_router
from api.routes.resume import router as resume_router
from api.routes.coordinate import router as coordinate_router
from api.routes.projects import router as projects_router
from api.routes.chats import router as chats_router
from api.routes.ws import router as ws_router
from api.routes.auth import router as auth_router

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

# Frontend is a separate Vercel deployment (different origin), so the browser
# needs an explicit CORS allow-list to send the session cookie cross-site.
_frontend_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGIN", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins + ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(run_router, prefix="/api/v1")
app.include_router(status_router, prefix="/api/v1")
app.include_router(resume_router, prefix="/api/v1")
app.include_router(coordinate_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(chats_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
