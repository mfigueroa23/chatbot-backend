from dataclasses import dataclass
from langchain_google_genai import ChatGoogleGenerativeAI

@dataclass
class AgentContext:
  llm: ChatGoogleGenerativeAI
  system_prompt: str
