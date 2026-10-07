from collections.abc import AsyncIterator
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.config import settings

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Para trabajo que sigue después de responder (p. ej. Google Chat diferido): la sesión de la petición ya estaría cerrada.
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return SessionLocal

SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
