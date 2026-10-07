from src.utils.exceptions.message import EmptyMessageError, MessageTooLongError

MAX_MESSAGE_LENGTH = 5000

def validate_user_message(text: str) -> str:
    text = text.strip()
    if not text:
        raise EmptyMessageError()
    if len(text) > MAX_MESSAGE_LENGTH:
        raise MessageTooLongError(MAX_MESSAGE_LENGTH)
    return text
