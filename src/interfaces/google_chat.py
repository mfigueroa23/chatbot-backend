from typing import Any
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class ChatModel(BaseModel):
  model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class ChatThread(ChatModel):
  name: str

class AttachmentDataRef(ChatModel):
  resource_name: str

class ChatAttachment(ChatModel):
  content_name: str = "archivo"
  content_type: str = ""
  # UPLOADED_CONTENT si se subió al chat (trae attachmentDataRef) o DRIVE_FILE si es un enlace de Drive.
  source: str | None = None
  attachment_data_ref: AttachmentDataRef | None = None

class ChatUser(ChatModel):
  # users/{id}: se usa para mencionar al remitente con <users/{id}>.
  name: str
  # HUMAN o BOT.
  type: str | None = None

class ChatMessage(ChatModel):
  text: str | None = None
  sender: ChatUser | None = None
  # En un space, el texto sin la mención al asistente.
  argument_text: str | None = None
  thread: ChatThread | None = None
  attachment: list[ChatAttachment] = []

class ChatSpace(ChatModel):
  name: str
  space_type: str | None = None

class MessagePayload(ChatModel):
  message: ChatMessage | None = None
  space: ChatSpace | None = None

class SpacePayload(ChatModel):
  space: ChatSpace | None = None

class AddonChat(ChatModel):
  message_payload: MessagePayload | None = None
  added_to_space_payload: SpacePayload | None = None

class AddonEvent(ChatModel):
  """Evento de Google Chat enviado por el complemento de Google Workspace, solo con los campos que se usan."""
  chat: AddonChat | None = None

def chat_reply(text: str) -> dict[str, Any]:
  # Respuesta síncrona del complemento: Google Chat la publica en el hilo del mensaje.
  return { "hostAppDataAction": { "chatDataAction": { "createMessageAction": { "message": { "text": text } } } } }
