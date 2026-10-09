class EdrNotConfiguredError(Exception):
    """Falta la plantilla, la carpeta de Drive o la cuenta de servicio del EDR, o la plantilla no es base64 válido."""

class InvalidEdrError(Exception):
    """El modelo no devolvió un EDR válido ni después de corregirlo."""
