from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.jira_board import JiraBoard
from src.utils.exceptions.database import DatabaseUnavailableError

async def allowed_boards(session: AsyncSession) -> list[str]:
    """Tableros permitidos, sin caché: un cambio se aplica desde la siguiente consulta (spec 002, RF-23)."""
    try:
        return list(await session.scalars(select(JiraBoard.key).where(JiraBoard.active).order_by(JiraBoard.key)))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
