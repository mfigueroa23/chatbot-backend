class InvalidCredentialsError(Exception):
    """Usuario o contraseña incorrectos."""

    def __init__(self):
        super().__init__("Usuario o contraseña incorrectos")

class AccountLockedError(Exception):
    """La cuenta está bloqueada temporalmente por intentos fallidos."""

class InvalidSessionError(Exception):
    """La sesión no existe, está caducada o fue revocada."""

class AuthNotConfiguredError(Exception):
    """Falta la clave de firma de los tokens de ejecutivo o es demasiado corta."""
