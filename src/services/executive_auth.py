import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.executive import Executive
from src.models.executive_session import ExecutiveSession
from src.services.property import get_int_property, get_str_property
from src.utils.clock import Clock
from src.utils.exceptions.auth import (
    AccountLockedError, AuthNotConfiguredError, InvalidCredentialsError, InvalidSessionError)
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
# HS256 necesita una clave de al menos 256 bits para no poder adivinarse por fuerza bruta.
MIN_JWT_SECRET_LENGTH = 32

password_hasher = PasswordHasher()
# Se verifica contra este hash cuando el usuario no existe: así la respuesta tarda lo mismo y no revela qué usuarios hay.
DUMMY_HASH = password_hasher.hash("contraseña-ficticia")

@dataclass(frozen=True)
class AuthSettings:
    max_attempts: int
    lock_minutes: int
    session_hours: int
    jwt_secret: str

@dataclass(frozen=True)
class SessionToken:
    token: str
    expires_at: datetime

class ExecutiveRepository(Protocol):
    async def find_by_username(self, username: str) -> Executive | None: ...
    async def add_session(self, session: ExecutiveSession) -> None: ...
    async def find_session(self, token_hash: str) -> tuple[ExecutiveSession, Executive] | None: ...
    async def delete_session(self, token_hash: str) -> None: ...
    async def save(self) -> None: ...

class SqlExecutiveRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_username(self, username: str) -> Executive | None:
        try:
            return await self._session.scalar(select(Executive).where(func.lower(Executive.username) == username.lower()))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def add_session(self, session: ExecutiveSession) -> None:
        self._session.add(session)

    async def find_session(self, token_hash: str) -> tuple[ExecutiveSession, Executive] | None:
        statement = (
            select(ExecutiveSession, Executive)
            .join(Executive, ExecutiveSession.executive_id == Executive.id)
            .where(ExecutiveSession.token_hash == token_hash)
        )
        try:
            row = (await self._session.execute(statement)).first()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        return (row[0], row[1]) if row else None

    async def delete_session(self, token_hash: str) -> None:
        try:
            await self._session.execute(delete(ExecutiveSession).where(ExecutiveSession.token_hash == token_hash))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def save(self) -> None:
        try:
            await self._session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

async def load_auth_settings(session: AsyncSession) -> AuthSettings:
    return AuthSettings(
        max_attempts=await get_int_property(session, "login_max_attempts", 5),
        lock_minutes=await get_int_property(session, "login_lock_minutes", 15),
        session_hours=await get_int_property(session, "executive_session_hours", 8),
        jwt_secret=await load_jwt_secret(session),
    )

async def load_jwt_secret(session: AsyncSession) -> str:
    try:
        secret = await get_str_property(session, "jwt_secret")
    except PropertyNotFoundError:
        secret = ""
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        logger.error("Falta la property jwt_secret o tiene menos de %s caracteres", MIN_JWT_SECRET_LENGTH)
        raise AuthNotConfiguredError()
    return secret

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerificationError:
        return False

async def login(repo: ExecutiveRepository, clock: Clock, settings: AuthSettings, username: str, password: str) -> SessionToken:
    executive = await repo.find_by_username(username)
    if executive is None or not executive.active:
        verify_password(DUMMY_HASH, password)
        raise InvalidCredentialsError()
    now = clock.now()
    password_ok = verify_password(executive.password_hash, password)
    if executive.locked_until is not None and executive.locked_until > now:
        raise AccountLockedError()
    if not password_ok:
        executive.failed_attempts += 1
        if executive.failed_attempts >= settings.max_attempts:
            executive.locked_until = now + timedelta(minutes=settings.lock_minutes)
            executive.failed_attempts = 0
        await repo.save()
        raise InvalidCredentialsError()
    executive.failed_attempts = 0
    executive.locked_until = None
    session_id = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=settings.session_hours)
    token = jwt.encode(
        {"sub": str(executive.id), "jti": session_id, "iat": now, "exp": expires_at}, settings.jwt_secret, algorithm=JWT_ALGORITHM)
    # Solo se guarda el hash del jti: permite revocar el JWT con el logout sin guardar nada reutilizable.
    await repo.add_session(ExecutiveSession(executive_id=executive.id, token_hash=hash_token(session_id), expires_at=expires_at))
    await repo.save()
    return SessionToken(token, expires_at)

def decode_token(secret: str, token: str) -> dict:
    try:
        # La caducidad se comprueba con el reloj inyectado contra la sesión guardada, no con la hora del sistema.
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM],
                          options={"verify_exp": False, "verify_iat": False, "require": ["sub", "jti", "exp"]})
    except jwt.InvalidTokenError as exc:
        raise InvalidSessionError() from exc

async def authenticate(repo: ExecutiveRepository, clock: Clock, secret: str, token: str) -> Executive:
    claims = decode_token(secret, token)
    found = await repo.find_session(hash_token(claims["jti"]))
    if found is None:
        raise InvalidSessionError()
    session, executive = found
    if str(executive.id) != claims["sub"] or session.expires_at <= clock.now() or not executive.active:
        raise InvalidSessionError()
    return executive

async def logout(repo: ExecutiveRepository, secret: str, token: str) -> None:
    await repo.delete_session(hash_token(decode_token(secret, token)["jti"]))
    await repo.save()
