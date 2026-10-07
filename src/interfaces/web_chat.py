import uuid
from typing import Annotated, Literal
from pydantic import BaseModel, Field, TypeAdapter

# Cliente → servidor

class UserMessage(BaseModel):
    type: Literal["message"] = "message"
    text: str

class HumanResponse(BaseModel):
    type: Literal["human_response"] = "human_response"
    accept: bool

class ContactMessage(BaseModel):
    type: Literal["contact"] = "contact"
    name: str
    email: str | None = None
    phone: str | None = None

class RequestHuman(BaseModel):
    type: Literal["request_human"] = "request_human"

class Ping(BaseModel):
    type: Literal["ping"] = "ping"

ClientMessage = Annotated[UserMessage | HumanResponse | ContactMessage | RequestHuman | Ping, Field(discriminator="type")]
client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

# Servidor → cliente

class Channel(BaseModel):
    label: str
    value: str

class SessionStarted(BaseModel):
    type: Literal["session"] = "session"
    session_id: uuid.UUID

class Busy(BaseModel):
    type: Literal["busy"] = "busy"
    channels: list[Channel]

class TextMessage(BaseModel):
    type: Literal["message"] = "message"
    from_: Literal["bot", "executive"] = Field(serialization_alias="from")
    text: str

class OfferHuman(BaseModel):
    type: Literal["offer_human"] = "offer_human"

class RequestContact(BaseModel):
    type: Literal["request_contact"] = "request_contact"
    attempt: int

class Queued(BaseModel):
    type: Literal["queued"] = "queued"

class ExecutiveJoined(BaseModel):
    type: Literal["executive_joined"] = "executive_joined"

class ExecutiveDisconnected(BaseModel):
    type: Literal["executive_disconnected"] = "executive_disconnected"
    return_within_minutes: int

class ChatClosed(BaseModel):
    type: Literal["chat_closed"] = "chat_closed"
    reason: str
    channels: list[Channel] | None = None

class OfficialChannels(BaseModel):
    type: Literal["official_channels"] = "official_channels"
    channels: list[Channel]

class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: Literal["empty_message", "message_too_long", "service_unavailable"]
    text: str

ServerMessage = (SessionStarted | Busy | TextMessage | OfferHuman | RequestContact | Queued | ExecutiveJoined
                 | ExecutiveDisconnected | ChatClosed | OfficialChannels | ErrorMessage)
