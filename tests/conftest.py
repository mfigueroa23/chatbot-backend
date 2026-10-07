import pytest
from src.services import property as property_service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_property_cache():
    property_service._loaded_at = None
    yield
    property_service._loaded_at = None
