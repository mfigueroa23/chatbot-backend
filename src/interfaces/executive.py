from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field, TypeAdapter
from src.interfaces.live_chat import ChatSummary

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    expires_at: datetime

# WebSocket del ejecutivo

class ExecutiveAuth(BaseModel):
    type: Literal["auth"] = "auth"
    token: str

class ExecutiveText(BaseModel):
    type: Literal["message"] = "message"
    chat_id: int
    text: str

class ExecutivePing(BaseModel):
    type: Literal["ping"] = "ping"

ExecutiveClientMessage = Annotated[ExecutiveText | ExecutivePing, Field(discriminator="type")]
executive_message_adapter: TypeAdapter[ExecutiveClientMessage] = TypeAdapter(ExecutiveClientMessage)

class AssignedChats(BaseModel):
    type: Literal["assigned_chats"] = "assigned_chats"
    chats: list[ChatSummary]

class CustomerText(BaseModel):
    type: Literal["message"] = "message"
    chat_id: int
    text: str

class ExecutiveChatClosed(BaseModel):
    type: Literal["chat_closed"] = "chat_closed"
    chat_id: int
    reason: str
