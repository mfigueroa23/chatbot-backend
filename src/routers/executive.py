import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from src.database.session import SessionDep
from src.interfaces.executive import LoginRequest, LoginResponse
from src.models.executive import Executive
from src.services.executive_auth import (
    ExecutiveRepository, SqlExecutiveRepository, authenticate, load_auth_settings, login, logout)
from src.utils.clock import Clock, get_clock
from src.utils.exceptions.auth import AccountLockedError, InvalidCredentialsError, InvalidSessionError
from src.utils.exceptions.database import DatabaseUnavailableError

router = APIRouter(tags=["Ejecutivos"])
logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Usuario o contraseña incorrectos"

def get_executive_repository(session: SessionDep) -> ExecutiveRepository:
    return SqlExecutiveRepository(session)

RepositoryDep = Annotated[ExecutiveRepository, Depends(get_executive_repository)]
ClockDep = Annotated[Clock, Depends(get_clock)]

def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida")
    return authorization.removeprefix("Bearer ")

async def get_current_executive(
    repo: RepositoryDep, clock: ClockDep, authorization: Annotated[str | None, Header()] = None
) -> Executive:
    try:
        return await authenticate(repo, clock, bearer_token(authorization))
    except InvalidSessionError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida") from exc
    except DatabaseUnavailableError as exc:
        logger.error("Autenticación de ejecutivo: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

CurrentExecutive = Annotated[Executive, Depends(get_current_executive)]

@router.post("/api/v1/executives/login", responses={401: {}, 503: {}})
async def executive_login(body: LoginRequest, session: SessionDep, repo: RepositoryDep, clock: ClockDep) -> LoginResponse:
    try:
        logger.debug("Login de ejecutivo iniciado")
        token = await login(repo, clock, await load_auth_settings(session), body.username, body.password)
        return LoginResponse(token=token.token, expires_at=token.expires_at)
    except (InvalidCredentialsError, AccountLockedError) as exc:
        # El mismo mensaje para todo: no se revela si el usuario existe o está bloqueado.
        logger.warning("Login de ejecutivo rechazado: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS) from exc
    except DatabaseUnavailableError as exc:
        logger.error("Login de ejecutivo: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

@router.post("/api/v1/executives/logout", status_code=status.HTTP_204_NO_CONTENT, responses={401: {}, 503: {}})
async def executive_logout(
    executive: CurrentExecutive, repo: RepositoryDep, authorization: Annotated[str | None, Header()] = None
) -> None:
    try:
        await logout(repo, bearer_token(authorization))
    except DatabaseUnavailableError as exc:
        logger.error("Logout de ejecutivo: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc
