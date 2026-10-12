import logging
from typing import Self
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.property import get_property

logger = logging.getLogger(__name__)

class LLM():
  def __init__(self, llm: ChatGoogleGenerativeAI):
    self.llm = llm

  @classmethod
  async def create(cls, session: AsyncSession) -> Self:
    logger.debug("Configurando el modelo de IA")
    api_key = await get_property(session = session, key = "google_api_key")
    model = await get_property(session = session, key = "google_model")
    return cls(ChatGoogleGenerativeAI(model = model, api_key = api_key))
