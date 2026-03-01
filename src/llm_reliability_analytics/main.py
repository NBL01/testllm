from contextlib import asynccontextmanager

from fastapi import FastAPI

from llm_reliability_analytics.api.routes import router
from llm_reliability_analytics.storage.duckdb_store import initialize_storage_schema


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_storage_schema()
    yield


app = FastAPI(title="LLM Reliability Analytics", version="0.1.0", lifespan=lifespan)
app.include_router(router)
