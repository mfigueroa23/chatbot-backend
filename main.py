import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from src.config import settings
from src.database.session import SessionLocal, engine
from src.routers.google_chat import router as google_chat_router
from src.routers.health import router as health_router
from src.routers.web_chat import router as web_chat_router
from src.services.retention import purge_expired, run_retention

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    retention = asyncio.create_task(run_retention(lambda: purge_expired(SessionLocal)))
    yield
    retention.cancel()
    with suppress(asyncio.CancelledError):
        await retention
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(web_chat_router)
app.include_router(google_chat_router)

app_logger = logging.getLogger("src")
app_logger.handlers = logging.getLogger("uvicorn").handlers
app_logger.setLevel(settings.LOG_LEVEL)
app_logger.propagate = False
