import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.config import settings
from src.database.session import engine
from src.routers.google_chat import router as google_chat_router
from src.routers.health import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
# Tareas en segundo plano de Google Chat que deben sobrevivir a la petición que las creó.
app.state.chat_tasks = set()

app.include_router(health_router)
app.include_router(google_chat_router)

app_logger = logging.getLogger("src")
app_logger.handlers = logging.getLogger("uvicorn").handlers
app_logger.setLevel(settings.LOG_LEVEL)
app_logger.propagate = False
