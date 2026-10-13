import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from src.agents.coordinator import coordinator_builder
from src.config import settings
from src.database.session import engine
from src.routers.health import router as health_router
from src.routers.chat import route as chat_router

async def check_connection(conn: AsyncConnection[DictRow]) -> None:
    await conn.execute("SELECT 1")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncConnectionPool(
        settings.checkpointer_url,
        connection_class = AsyncConnection[DictRow],
        kwargs = { "autocommit": True, "prepare_threshold": 0, "row_factory": dict_row },
        check = check_connection,
        min_size = 1,
        max_size = 2,
        open = False
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        app.state.graph = coordinator_builder.compile(checkpointer = checkpointer)
        yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(chat_router)

app_logger = logging.getLogger("src")
app_logger.handlers = logging.getLogger("uvicorn").handlers
app_logger.setLevel(settings.LOG_LEVEL)
app_logger.propagate = False
