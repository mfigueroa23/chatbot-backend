from datetime import UTC, date, datetime, time
from src.services.schedule import is_open

# Lunes a viernes de 9:00 a 18:00 (hora de Chile).
SLOTS = {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}


def at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_abierto_dentro_de_la_franja():
    # Miércoles 7 de octubre de 2026, 15:00 UTC = 12:00 en Santiago (UTC-3).
    assert is_open(at(2026, 10, 7, 15), SLOTS, set())


def test_cerrado_fuera_de_la_franja():
    assert not is_open(at(2026, 10, 7, 22), SLOTS, set())


def test_cerrado_en_dia_sin_franja():
    # Sábado 10 de octubre de 2026 a las 12:00 en Santiago.
    assert not is_open(at(2026, 10, 10, 15), SLOTS, set())


def test_cerrado_en_festivo():
    assert not is_open(at(2026, 10, 7, 15), SLOTS, {date(2026, 10, 7)})


def test_abierto_en_el_minuto_de_apertura():
    assert is_open(at(2026, 10, 7, 12), SLOTS, set())


def test_cerrado_en_el_minuto_de_cierre():
    assert not is_open(at(2026, 10, 7, 21), SLOTS, set())


def test_usa_el_horario_de_verano_de_santiago():
    # Las 12:00 UTC son las 08:00 en invierno (UTC-4) y las 09:00 en verano (UTC-3, desde el 6 de septiembre de 2026).
    assert not is_open(at(2026, 8, 31, 12), SLOTS, set())
    assert is_open(at(2026, 9, 7, 12), SLOTS, set())
