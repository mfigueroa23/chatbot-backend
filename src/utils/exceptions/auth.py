class InvalidCredentialsError(Exception):
    """Usuario o contraseña incorrectos."""

class AccountLockedError(Exception):
    """La cuenta está bloqueada temporalmente por intentos fallidos."""

class InvalidSessionError(Exception):
    """La sesión no existe, está caducada o fue revocada."""
