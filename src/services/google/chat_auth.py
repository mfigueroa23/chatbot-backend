import re
import time
import httpx
from google.auth import exceptions, jwt
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

# Los complementos de Google Workspace firman sus peticiones con un ID token de Google.
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Caché de los certificados públicos de Google (no de la configuración): se respeta el max-age que indica Google.
_certs: dict[str, str] = {}
_certs_expire_at = 0.0

async def get_google_certs(http: httpx.AsyncClient) -> dict[str, str]:
    global _certs, _certs_expire_at
    if time.monotonic() >= _certs_expire_at:
        response = await http.get(GOOGLE_CERTS_URL)
        response.raise_for_status()
        _certs = response.json()
        max_age = re.search(r"max-age=(\d+)", response.headers.get("Cache-Control", ""))
        _certs_expire_at = time.monotonic() + (int(max_age.group(1)) if max_age else 0)
    return _certs

async def verify_addon_token(token: str | None, audience: str, service_account: str, http: httpx.AsyncClient) -> None:
    if not token:
        raise InvalidGoogleTokenError("Falta el token Bearer")
    try:
        claims = jwt.decode(token, certs=await get_google_certs(http), audience=audience)
    except (ValueError, exceptions.GoogleAuthError, httpx.HTTPError) as exc:
        raise InvalidGoogleTokenError(str(exc)) from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise InvalidGoogleTokenError("El emisor del token no es Google")
    # Solo la cuenta de servicio de este complemento: un ID token de Google de otra cuenta no basta (RF-35).
    if claims.get("email") != service_account or claims.get("email_verified") is not True:
        raise InvalidGoogleTokenError("El token no es de la cuenta de servicio del complemento")
