from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
  chat_id: str
  mensaje: str = Field(min_length=1, max_length=2000)

class ChatResponse(BaseModel):
  respuesta: str
