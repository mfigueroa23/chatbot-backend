import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from src.agents.graph import build_graph, checkpoint_serializer
from src.config import settings
from src.database.session import engine
from src.models.business_area import AreaScope
from src.routers.executive import router as executive_router
from src.routers.google_chat import router as google_chat_router
from src.routers.health import router as health_router
from src.routers.web_chat import router as web_chat_router

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # min_size=0: no abre conexiones hasta que se usa. Las tablas las crea la migración de Alembic, así que no se llama
    # a .setup().
    async with AsyncConnectionPool[AsyncConnection[DictRow]](
        settings.psycopg_conninfo, min_size=0, max_size=10, open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    ) as pool:
        app.state.checkpointer = AsyncPostgresSaver(pool, serde=checkpoint_serializer())
        app.state.external_graph = build_graph(AreaScope.external, app.state.checkpointer)
        yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
# Tareas en segundo plano de Google Chat que deben sobrevivir a la petición que las creó.
app.state.chat_tasks = set()

app.include_router(health_router)
app.include_router(google_chat_router)
app.include_router(executive_router)
app.include_router(web_chat_router)

app_logger = logging.getLogger("src")
app_logger.handlers = logging.getLogger("uvicorn").handlers
app_logger.setLevel(settings.LOG_LEVEL)
app_logger.propagate = False
