class InvalidMessageError(Exception):
    """El mensaje del usuario no se envía al modelo; reply es lo que se le responde."""

    def __init__(self, reply: str):
        super().__init__(reply)
        self.reply = reply
