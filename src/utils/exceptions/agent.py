class LlmNotConfiguredError(Exception):
    """Falta el modelo o la API key del LLM en la tabla property."""

class LlmUnavailableError(Exception):
    """El proveedor del LLM falló o superó el tiempo de espera."""
