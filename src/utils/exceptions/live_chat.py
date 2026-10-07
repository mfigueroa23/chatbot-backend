class ChatNotFoundError(Exception):
    """El chat en vivo no existe."""

class ChatAlreadyAssignedError(Exception):
    """El chat ya fue tomado por otro ejecutivo."""

class ExecutiveChatLimitError(Exception):
    """El ejecutivo alcanzó el máximo de chats simultáneos."""

class NotChatOwnerError(Exception):
    """Solo el ejecutivo asignado puede operar sobre el chat."""
