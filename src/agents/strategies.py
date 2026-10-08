import logging
from dataclasses import dataclass, field
from typing import Protocol
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.llm import AreaInfo
from src.models.business_area import AreaScope
from src.services.business_data import get_official_channels
from src.services.schedule import is_open, load_schedule
from src.utils.clock import Clock

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class NoAnswerContext:
    question: str
    areas: list[AreaInfo]  # áreas a las que correspondía la pregunta; vacía si ninguna
    user_name: str | None = None
    user_email: str | None = None

@dataclass(frozen=True)
class ChannelReply:
    text: str
    offer_human: bool = False
    channels: list[tuple[str, str]] = field(default_factory=list)

class ChannelStrategy(Protocol):
    scope: AreaScope

    async def on_no_answer(self, context: NoAnswerContext) -> ChannelReply: ...

class Notifier(Protocol):
    async def notify(self, space: str, text: str) -> None: ...

class ExternalStrategy:
    scope = AreaScope.external

    def __init__(self, session: AsyncSession, clock: Clock):
        self._session = session
        self._clock = clock

    async def on_no_answer(self, context: NoAnswerContext) -> ChannelReply:
        slots, holidays = await load_schedule(self._session)
        if is_open(self._clock.now(), slots, holidays):
            return ChannelReply("No encontré una respuesta a tu consulta. ¿Quieres hablar con un ejecutivo?", offer_human=True)
        return await official_channels_reply(self._session)

async def official_channels_reply(session: AsyncSession) -> ChannelReply:
    channels = await get_official_channels(session)
    return ChannelReply(
        "No encontré una respuesta a tu consulta. Por favor, reformula tu pregunta o contáctanos por nuestros canales oficiales.",
        channels=[(channel.label, channel.value) for channel in channels],
    )
