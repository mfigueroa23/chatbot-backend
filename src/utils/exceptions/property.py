class PropertyNotFoundError(Exception):
    """La property solicitada no existe en la tabla property."""

    def __init__(self, key: str):
        super().__init__(f"La property '{key}' no existe")
        self.key = key
