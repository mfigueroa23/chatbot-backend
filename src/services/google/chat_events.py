from src.interfaces.google_chat import AddonEvent
from src.services.files.attachments import Attachment

def conversation_key(event: AddonEvent) -> str:
    # En un mensaje directo cada mensaje abre un hilo nuevo: la conversación es el space. En un space, el hilo.
    payload = event.chat.message_payload if event.chat else None
    space = payload.space if payload else None
    if space is not None and space.space_type == "DIRECT_MESSAGE":
        return space.name
    thread = payload.message.thread if payload and payload.message else None
    return thread.name if thread else (space.name if space else "")

def message_text(event: AddonEvent) -> str:
    payload = event.chat.message_payload if event.chat else None
    if payload is None or payload.message is None:
        return ""
    is_dm = payload.space is not None and payload.space.space_type == "DIRECT_MESSAGE"
    # En un space solo cuenta el texto que acompaña a la mención; en un mensaje directo, el texto completo.
    return (payload.message.text if is_dm else payload.message.argument_text) or ""

def requester_of(event: AddonEvent) -> str | None:
    """Correo de la cuenta de Google Chat que escribe, en minúsculas (spec 002, RF-1)."""
    email = event.chat.user.email if event.chat and event.chat.user else None
    return email.strip().lower() if email and email.strip() else None

def attachments_of(event: AddonEvent) -> list[Attachment]:
    """Adjuntos del mensaje (spec 002, RF-31). Solo se descargan los subidos al chat; un enlace de Drive llega sin
    resource_name y se responde como formato no admitido (RF-38)."""
    payload = event.chat.message_payload if event.chat else None
    if payload is None or payload.message is None:
        return []
    return [Attachment(item.content_name, item.content_type,
                       item.attachment_data_ref.resource_name
                       if item.source != "DRIVE_FILE" and item.attachment_data_ref else None)
            for item in payload.message.attachment]
