from datetime import UTC, datetime, timedelta
from src.utils.clock import SystemClock
from tests.fakes import FakeClock


def test_system_clock_devuelve_hora_aware_en_utc():
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_fake_clock_avanza_el_tiempo():
    clock = FakeClock(datetime(2026, 10, 7, 12, 0, tzinfo=UTC))

    clock.advance(timedelta(minutes=15))

    assert clock.now() == datetime(2026, 10, 7, 12, 15, tzinfo=UTC)
