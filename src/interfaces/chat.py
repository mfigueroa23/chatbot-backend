from pydantic import BaseModel

class ChatRequest(BaseModel):
  chat_id: str
  mensaje: str

class ChatResponse(BaseModel):
  respuesta: str
