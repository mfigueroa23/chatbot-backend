from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class ChatModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class ChatUser(ChatModel):
    email: str | None = None
    display_name: str | None = None

class ChatThread(ChatModel):
    name: str

class ChatMessage(ChatModel):
    text: str | None = None
    argument_text: str | None = None
    thread: ChatThread | None = None

class ChatSpace(ChatModel):
    name: str
    space_type: str | None = None

class ChatEvent(ChatModel):
    """Evento de interacción de Google Chat: solo los campos que usa el bot."""
    type: str
    space: ChatSpace | None = None
    message: ChatMessage | None = None
    user: ChatUser | None = None
