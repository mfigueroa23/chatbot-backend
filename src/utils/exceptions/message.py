class EmptyMessageError(Exception):
    """El mensaje está vacío o solo tiene espacios."""

class MessageTooLongError(Exception):
    """El mensaje supera el máximo de caracteres permitido."""

    def __init__(self, max_length: int):
        super().__init__(f"El mensaje supera los {max_length} caracteres permitidos")
        self.max_length = max_length
