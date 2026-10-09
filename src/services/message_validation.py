from src.utils.exceptions.message import InvalidMessageError

MAX_MESSAGE_LENGTH = 5000
# Impersonales: sirven igual con el trato de usted del web y el de tú de Google Chat.
EMPTY_MESSAGE = "El mensaje llegó vacío. ¿Cuál es la consulta?"
TOO_LONG_MESSAGE = f"El mensaje supera el límite de {MAX_MESSAGE_LENGTH} caracteres: la consulta debe ser más breve."

def validate_user_message(text: str) -> str:
    """Devuelve el texto sin espacios exteriores, o lanza InvalidMessageError sin llamar al modelo (RF-31, RF-32)."""
    text = text.strip()
    if not text:
        raise InvalidMessageError(EMPTY_MESSAGE)
    if len(text) > MAX_MESSAGE_LENGTH:
        raise InvalidMessageError(TOO_LONG_MESSAGE)
    return text
