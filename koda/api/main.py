import os                                                                                                                                                
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from api.routes.run import router as run_router
from api.routes.status import router as status_router

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    from agent.graph import compiled_graph
    app.state.graph = compiled_graph
    yield


app = FastAPI(
    title="KODA",
    description="Knowledge oriented Developer Agent",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(run_router, prefix="/api/v1")
app.include_router(status_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "ok"}


