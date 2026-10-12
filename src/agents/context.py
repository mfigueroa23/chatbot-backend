from dataclasses import dataclass
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

@dataclass
class AgentContext:
  llm: ChatGoogleGenerativeAI
  system_prompt: str
  embeddings: GoogleGenerativeAIEmbeddings
  area: str
  audiencia: str
