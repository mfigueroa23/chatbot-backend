import logging
from typing import Self
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.faqs import EMBEDDING_DIMENSIONS
from src.services.property import get_property

logger = logging.getLogger(__name__)

class LLM():
  def __init__(self, llm: ChatGoogleGenerativeAI, embeddings: GoogleGenerativeAIEmbeddings):
    self.llm = llm
    self.embeddings = embeddings

  @classmethod
  async def create(cls, session: AsyncSession) -> Self:
    logger.debug("Configurando el modelo de IA")
    api_key = await get_property(session = session, key = "google_api_key")
    model = await get_property(session = session, key = "google_model")
    embedding_model = await get_property(session = session, key = "google_embedding_model")
    return cls(
      ChatGoogleGenerativeAI(model = model, api_key = api_key),
      GoogleGenerativeAIEmbeddings(model = embedding_model, api_key = SecretStr(api_key), output_dimensionality = EMBEDDING_DIMENSIONS)
    )
