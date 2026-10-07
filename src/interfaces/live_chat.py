from datetime import datetime
from pydantic import BaseModel
from src.models.live_chat import LiveChat

class WaitingChat(BaseModel):
    id: int
    customer_name: str
    created_at: datetime

class ChatSummary(BaseModel):
    id: int
    customer_name: str
    customer_contact: str
    pending_question: str

    @classmethod
    def from_chat(cls, chat: LiveChat) -> "ChatSummary":
        return cls(id=chat.id, customer_name=chat.customer_name, customer_contact=chat.customer_contact,
                   pending_question=chat.pending_question)
