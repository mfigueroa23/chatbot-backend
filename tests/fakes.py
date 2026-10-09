from types import SimpleNamespace
from typing import Any


class PropertySession:
    """Sesión falsa sobre un dict: cuenta las consultas y lee el dict en cada una, como la tabla sin caché."""

    def __init__(self, values: dict[str, str], down: bool = False):
        self.values = values
        self.down = down
        self.queries = 0

    def _query(self) -> None:
        self.queries += 1
        if self.down:
            raise ConnectionRefusedError()

    async def scalar(self, statement: Any) -> str | None:
        self._query()
        key = next(iter(statement.compile().params.values()))
        return self.values.get(key)

    async def execute(self, statement: Any) -> list[SimpleNamespace]:
        self._query()
        return [SimpleNamespace(key=key, value=value) for key, value in self.values.items()]
