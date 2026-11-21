from contextlib import asynccontextmanager, contextmanager
import fcntl
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm_reliability_analytics.api.routes import router
from llm_reliability_analytics.api.internal import router as internal_router
from llm_reliability_analytics.storage.duckdb_store import initialize_storage_schema
from llm_reliability_analytics.storage.db import get_db_path
from llm_reliability_analytics.workflow.evaluation_jobs import recover_interrupted_jobs, stop_worker


@contextmanager
def api_database_owner():
    """Hold ownership across connections, before startup recovery can change jobs."""
    path = get_db_path().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".api.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Run only one FastAPI worker per database; another API owns this database.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@asynccontextmanager
async def lifespan(_: FastAPI):
    with api_database_owner():
        initialize_storage_schema()
        recover_interrupted_jobs()
        try:
            yield
        finally:
            # Finish (or stop) the in-flight run while this process still owns the database.
            stop_worker()


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
app.include_router(internal_router)
