from src.interfaces.google_chat import AddonEvent

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
