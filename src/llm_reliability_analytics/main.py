from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm_reliability_analytics.api.routes import router
from llm_reliability_analytics.storage.duckdb_store import initialize_storage_schema


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_storage_schema()
    yield


app = FastAPI(title="LLM Reliability Analytics", version="0.1.0", lifespan=lifespan)

raw_origins = os.getenv(
    "LLM_RELIABILITY_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
