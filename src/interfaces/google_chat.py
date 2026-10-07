from typing import Any
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

class MessagePayload(ChatModel):
    message: ChatMessage | None = None
    space: ChatSpace | None = None

class SpacePayload(ChatModel):
    space: ChatSpace | None = None

class AddonChat(ChatModel):
    user: ChatUser | None = None
    message_payload: MessagePayload | None = None
    added_to_space_payload: SpacePayload | None = None

class AddonEvent(ChatModel):
    """Evento de una app de Chat creada como complemento de Google Workspace: solo los campos que usa el bot."""
    chat: AddonChat | None = None

def chat_reply(text: str | None) -> dict[str, Any]:
    # Respuesta síncrona del complemento; sin texto no se publica nada.
    if not text:
        return {}
    return {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": text}}}}}
