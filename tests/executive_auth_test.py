from datetime import UTC, datetime, timedelta
import jwt
import pytest
from src.services.executive_auth import AuthSettings, authenticate, login, logout, password_hasher
from src.utils.exceptions.auth import AccountLockedError, InvalidCredentialsError, InvalidSessionError
from tests.fakes import FakeClock, FakeExecutiveRepository, executive

PASSWORD = "Clave-Segura-123"
PASSWORD_HASH = password_hasher.hash(PASSWORD)
SECRET = "clave-de-firma-de-pruebas-con-32-caracteres"
SETTINGS = AuthSettings(max_attempts=5, lock_minutes=15, session_hours=8, jwt_secret=SECRET)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 7, 12, 0, tzinfo=UTC))


@pytest.fixture
def repo() -> FakeExecutiveRepository:
    return FakeExecutiveRepository([executive(PASSWORD_HASH)])


def test_hash_argon2_no_es_la_contrasena_y_se_verifica():
    assert PASSWORD_HASH.startswith("$argon2id$")
    assert PASSWORD not in PASSWORD_HASH
    assert password_hasher.verify(PASSWORD_HASH, PASSWORD)


@pytest.mark.anyio
async def test_login_correcto_crea_una_sesion_de_8_horas(repo: FakeExecutiveRepository, clock: FakeClock):
    token = await login(repo, clock, SETTINGS, "ANA", PASSWORD)

    claims = jwt.decode(token.token, SECRET, algorithms=["HS256"], options={"verify_exp": False, "verify_iat": False})
    assert token.expires_at == clock.now() + timedelta(hours=8)
    assert claims["sub"] == "1" and claims["exp"] == int(token.expires_at.timestamp())
    assert len(repo.sessions) == 1
    assert claims["jti"] not in repo.sessions  # solo se guarda el hash del identificador


@pytest.mark.anyio
async def test_login_incorrecto_y_usuario_inexistente_dan_el_mismo_error(repo: FakeExecutiveRepository, clock: FakeClock):
    with pytest.raises(InvalidCredentialsError) as wrong_password:
        await login(repo, clock, SETTINGS, "ana", "otra")
    with pytest.raises(InvalidCredentialsError) as unknown_user:
        await login(repo, clock, SETTINGS, "pedro", PASSWORD)

    assert str(wrong_password.value) == str(unknown_user.value)


@pytest.mark.anyio
async def test_login_bloquea_la_cuenta_al_quinto_fallo_aunque_luego_acierte(repo: FakeExecutiveRepository, clock: FakeClock):
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await login(repo, clock, SETTINGS, "ana", "otra")

    with pytest.raises(AccountLockedError):
        await login(repo, clock, SETTINGS, "ana", PASSWORD)


@pytest.mark.anyio
async def test_login_se_desbloquea_a_los_15_minutos(repo: FakeExecutiveRepository, clock: FakeClock):
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await login(repo, clock, SETTINGS, "ana", "otra")

    clock.advance(timedelta(minutes=15))

    assert await login(repo, clock, SETTINGS, "ana", PASSWORD)


@pytest.mark.anyio
async def test_session_valida_devuelve_el_ejecutivo(repo: FakeExecutiveRepository, clock: FakeClock):
    token = await login(repo, clock, SETTINGS, "ana", PASSWORD)

    assert (await authenticate(repo, clock, SECRET, token.token)).username == "ana"


@pytest.mark.anyio
async def test_session_caduca_a_las_8_horas(repo: FakeExecutiveRepository, clock: FakeClock):
    token = await login(repo, clock, SETTINGS, "ana", PASSWORD)
    clock.advance(timedelta(hours=8))

    with pytest.raises(InvalidSessionError):
        await authenticate(repo, clock, SECRET, token.token)


@pytest.mark.anyio
async def test_session_revocada_con_logout(repo: FakeExecutiveRepository, clock: FakeClock):
    token = await login(repo, clock, SETTINGS, "ana", PASSWORD)
    await logout(repo, SECRET, token.token)

    with pytest.raises(InvalidSessionError):
        await authenticate(repo, clock, SECRET, token.token)


@pytest.mark.anyio
async def test_session_inexistente(repo: FakeExecutiveRepository, clock: FakeClock):
    with pytest.raises(InvalidSessionError):
        await authenticate(repo, clock, SECRET, "token-inventado")


@pytest.mark.anyio
async def test_session_con_un_jwt_firmado_con_otra_clave_se_rechaza(repo: FakeExecutiveRepository, clock: FakeClock):
    token = await login(repo, clock, SETTINGS, "ana", PASSWORD)
    claims = jwt.decode(token.token, SECRET, algorithms=["HS256"], options={"verify_exp": False, "verify_iat": False})
    forged = jwt.encode(claims, "otra-clave-de-firma-con-mas-de-32-caracteres", algorithm="HS256")

    with pytest.raises(InvalidSessionError):
        await authenticate(repo, clock, SECRET, forged)
