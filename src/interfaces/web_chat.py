import uuid
from pydantic import BaseModel

class ChatRequest(BaseModel):
    # Sin max_length: un mensaje largo se responde con un aviso (RF-32), no con un 422.
    session_id: uuid.UUID | None = None
    message: str

class ChatResponse(BaseModel):
    session_id: uuid.UUID
    reply: str
