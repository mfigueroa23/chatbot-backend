class AttachmentTooLargeError(Exception):
    """El archivo supera el tamaño máximo: la descarga se corta sin leerlo entero (spec 002, RF-37)."""
