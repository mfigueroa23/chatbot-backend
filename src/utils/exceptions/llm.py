class LlmUnavailableError(Exception):
    """El proveedor del modelo falló, superó el tiempo de espera o falta su configuración."""
