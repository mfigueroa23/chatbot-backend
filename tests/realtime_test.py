import json
from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.realtime import ConnectionHub, Event


class NotifySession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)


@pytest.mark.anyio
async def test_publish_envia_por_pg_notify_solo_identificadores():
    session = NotifySession()
    event = Event("executive_message", chat_id=7, web_session_id="s-1", executive_id=5, message_id=42)

    await ConnectionHub().publish(cast(AsyncSession, session), event)

    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    assert "pg_notify" in str(compiled)
    payload = json.loads(next(value for value in compiled.params.values() if isinstance(value, str) and value.startswith("{")))
    assert payload == {"kind": "executive_message", "chat_id": 7, "web_session_id": "s-1", "executive_id": 5,
                       "message_id": 42, "reason": None}


@pytest.mark.anyio
async def test_dispatch_entrega_cada_evento_solo_al_socket_local_destinatario():
    hub = ConnectionHub()
    hub._ensure_listener = lambda: None  # sin BD: solo se prueba el reparto local
    received: dict[str, list[str]] = {"cliente-1": [], "cliente-2": [], "ejecutivo-5": [], "ejecutivo-6": []}

    def recorder(name: str):
        async def deliver(event: Event) -> None:
            received[name].append(event.kind)
        return deliver

    hub.register_customer("s-1", recorder("cliente-1"))
    hub.register_customer("s-2", recorder("cliente-2"))
    hub.register_executive(5, recorder("ejecutivo-5"))
    hub.register_executive(6, recorder("ejecutivo-6"))

    await hub.dispatch(Event("executive_message", 7, web_session_id="s-1", executive_id=5, message_id=1).to_payload())
    await hub.dispatch(Event("customer_message", 7, web_session_id="s-1", executive_id=5, message_id=2).to_payload())
    await hub.dispatch(Event("chat_closed", 8, web_session_id="s-2", executive_id=6, reason="executive").to_payload())
    await hub.dispatch(Event("executive_message", 9, web_session_id="s-remoto", executive_id=9, message_id=3).to_payload())

    assert received == {
        "cliente-1": ["executive_message"],
        "cliente-2": ["chat_closed"],
        "ejecutivo-5": ["customer_message"],
        "ejecutivo-6": ["chat_closed"],
    }
