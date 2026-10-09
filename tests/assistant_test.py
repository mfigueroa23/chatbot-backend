import logging
import uuid
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from src.agents.llm import Catalog, RoutingDecision, Subtask
from src.models.business_area import AreaScope
from src.models.conversation import Channel
from src.services.assistant import UNAVAILABLE, answer
from src.services.message_validation import EMPTY_MESSAGE
from src.utils.exceptions.llm import LlmUnavailableError
from tests.fakes import PROPERTIES, SAC, SECRET, AssistantHarness, FakeCoordinatorModel


@pytest.mark.anyio
async def test_sesion_inexistente_crea_una_nueva_y_una_existente_se_mantiene():
    harness = AssistantHarness()

    first = await answer(harness.deps(), Channel.web, uuid.uuid4(), "hola")
    second = await answer(harness.deps(), Channel.web, first.conversation_id, "hola de nuevo")

    assert second.conversation_id == first.conversation_id and first.reply == "¡Hola!"
    assert len(harness.store.messages[first.conversation_id]) == 4


@pytest.mark.anyio
async def test_el_historial_se_limita_y_empieza_en_un_mensaje_del_usuario():
    harness = AssistantHarness()
    conversation = await harness.store.web_conversation(None, harness.deps().now())
    harness.store.messages[conversation] = [HumanMessage("uno"), AIMessage("r1"), HumanMessage("dos"), AIMessage("r2")]
    harness.properties["history_messages"] = "3"

    await answer(harness.deps(), Channel.web, conversation, "tres")

    # Los últimos 3 serían r1, dos, r2: se recorta r1 para empezar por el usuario.
    assert harness.coordinator.route_calls[0][1:-1] == [HumanMessage("dos"), AIMessage("r2")]


@pytest.mark.anyio
async def test_las_conversaciones_no_se_mezclan():
    harness = AssistantHarness()
    first = await answer(harness.deps(), Channel.google_chat, "spaces/A/threads/1", "secreto del hilo 1")

    await answer(harness.deps(), Channel.google_chat, "spaces/A/threads/2", "hola")

    again = await answer(harness.deps(), Channel.google_chat, "spaces/A/threads/1", "sigo en el hilo 1")

    assert "secreto del hilo 1" not in str(harness.coordinator.route_calls[1])
    assert "secreto del hilo 1" in str(harness.coordinator.route_calls[2])
    assert again.conversation_id == first.conversation_id


@pytest.mark.anyio
@pytest.mark.parametrize("channel, scope", [(Channel.web, AreaScope.external), (Channel.google_chat, AreaScope.internal)])
async def test_cada_canal_usa_el_catalogo_de_su_alcance(channel, scope):
    harness = AssistantHarness()

    await answer(harness.deps(), channel, None if channel == Channel.web else "spaces/A", "hola")

    assert harness.requested_scopes == [scope]


@pytest.mark.anyio
async def test_un_cambio_del_catalogo_se_aplica_en_el_siguiente_mensaje():
    harness = AssistantHarness()
    await answer(harness.deps(), Channel.web, None, "hola")
    harness.catalogs[AreaScope.external] = Catalog(AreaScope.external, "Coordinador NUEVO.", "Reglas.", (SAC,))

    await answer(harness.deps(), Channel.web, None, "hola")

    assert "Coordinador NUEVO." in str(harness.coordinator.route_calls[1][0].content)


@pytest.mark.anyio
async def test_mensaje_invalido_no_llama_al_modelo():
    harness = AssistantHarness()

    reply = await answer(harness.deps(), Channel.web, None, "   ")

    assert reply.reply == EMPTY_MESSAGE and harness.coordinator.route_calls == []


@pytest.mark.anyio
async def test_falta_la_api_key_responde_no_disponible_sin_registrar_su_valor(caplog):
    harness = AssistantHarness(properties={"history_messages": "2"})

    with caplog.at_level(logging.ERROR, logger="src"):
        reply = await answer(harness.deps(), Channel.web, None, "hola")

    assert reply.reply == UNAVAILABLE and "gemini_api_key" in caplog.text


@pytest.mark.anyio
async def test_la_api_key_nunca_aparece_en_los_logs(caplog):
    harness = AssistantHarness(FakeCoordinatorModel(error=LlmUnavailableError("ConnectionError")))

    with caplog.at_level(logging.DEBUG, logger="src"):
        await answer(harness.deps(), Channel.web, None, "mi rut es 12.345.678-5")

    assert SECRET not in caplog.text and "12.345.678-5" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("coordinator", [FakeCoordinatorModel(error=LlmUnavailableError("caído")),
                                         FakeCoordinatorModel(delay=2.0)])
async def test_error_o_timeout_del_modelo_responde_no_disponible(coordinator):
    harness = AssistantHarness(coordinator, {**PROPERTIES, "response_timeout_seconds": "1"})

    reply = await answer(harness.deps(), Channel.web, None, "hola")

    assert reply.reply == UNAVAILABLE and harness.store.messages[reply.conversation_id] == []


@pytest.mark.anyio
async def test_respuesta_con_areas_no_registra_el_texto_del_usuario(caplog):
    coordinator = FakeCoordinatorModel(RoutingDecision("areas", (Subtask(1, "cómo pago la cuota"),)), reply="En la web.")

    with caplog.at_level(logging.DEBUG, logger="src"):
        reply = await answer(AssistantHarness(coordinator).deps(), Channel.web, None, "¿Cómo pago mi cuota número 4455?")

    assert reply.reply == "En la web."
    assert "4455" not in caplog.text and "Paso route" in caplog.text and "Paso synthesize" in caplog.text
