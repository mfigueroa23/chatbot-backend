# Tareas 002 — Comportamiento de asistente (chatbot-backend)

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 32/60 hechas
Cada tarea dura menos de 30 min y deja los tests en verde. Se hacen en orden; `[P]` = puede ir en paralelo con la anterior.
Salvo que se diga otra cosa, "verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test
se conecta a la BD ni a la red (constitución, punto 6). Los dobles compartidos viven en `tests/fakes.py`. El código de
referencia de los agentes de área está en `git show 60a517e^:src/agents/{sub_agent,tools,llm,graph}.py`.

## Fase 0 — Verificaciones previas
- [ ] **T-1 — Comprobar si el frontend permite escribir durante la oferta y el formulario** · (habilita RF-41, RF-42, RF-43) · ~15 min
  En el repo del frontend web, revisar si el campo de texto sigue activo con `offer_human` y `request_contact` en pantalla. Anotar el resultado en R4 del plan.
  Hecho cuando: R4 del plan dice «el frontend permite escribir» o enlaza la tarea abierta en el repo del frontend.
- [x] **T-2 — Cerrar con el usuario los huecos R6 y R7** · RF-36, RF-43 · ~10 min [P]
  Preguntar si un saludo mantiene la oferta pendiente (R6) y si «solo el otro ámbito» con candidatos propios es fuera de tema (R7).
  Hecho cuando: R6 y R7 del plan dicen «Decisión del usuario» con la respuesta; si cambia algo, la spec tiene el RF correspondiente.

## Fase 1 — Datos y catálogo
- [x] **T-3 — Crear la migración de datos de los textos fijos** · RF-1, RNF-3 · ~20 min
  `alembic/versions/<rev>_seed_fixed_messages.py` con `down_revision = '36f04146ef00'`: 6 keys de `agent_prompt` con los textos de la sección 3 del plan y `ON CONFLICT (key) DO NOTHING`; el downgrade borra esas keys.
  Hecho cuando: en local, `uv run alembic upgrade head` deja las 6 keys en `agent_prompt` y `uv run alembic downgrade -1` las quita.
- [x] **T-4 — Leer los textos fijos y los nombres de áreas en el catálogo** · RF-1, RF-2 · ~20 min
  `Catalog` añade `fixed: dict[str, str | None]` y `area_names`; `load_catalog` lee `{scope}_greeting`, `{scope}_closing` y `{scope}_off_topic` con `get_agent_prompt`, sin caché.
  Hecho cuando: `uv run pytest -q tests/business_data_test.py -k catalog` pasa con un texto presente, uno ausente (`None`) y los nombres de todas las áreas activas del ámbito.

## Fase 2 — Lógica pura (`src/agents/behavior.py`)
- [x] **T-5 — Crear los tipos de aclaración y `requester_key`** · (habilita RF-24) · ~15 min
  `ClarifyOption`, `Clarification` y `requester_key(requester)` (correo de Google Chat o `"web"`).
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k requester_key` pasa.
- [x] **T-6 — Implementar `build_options`** · RF-11, RF-12, RF-13 · ~25 min
  Orden único de FAQ y procedimientos por similitud, empate alfabético, texto repetido una vez, máximo 3, numeradas desde 1.
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k build_options` pasa con 5 candidatos, un empate y un texto repetido.
- [x] **T-7 — Implementar `options_text` y `areas_question`** · RF-14, RF-15, RF-16 · ~20 min (depende de T-5) [P]
  Constantes `CLARIFY_OPTIONS` y `CLARIFY_AREAS`; las opciones van numeradas y sin respuesta ni pasos; la pregunta de áreas sin lista si no hay áreas.
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k "options_text or areas_question"` pasa, incluido el caso sin áreas.
- [x] **T-8 — Implementar `can_clarify`** · RF-17, RF-18 · ~15 min
  Opciones pendientes bloquean cualquier aclaración; pregunta de áreas pendiente solo bloquea otra de áreas.
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k can_clarify` pasa con las 6 combinaciones (sin pendiente, opciones, áreas × tipo pedido).
- [x] **T-9 — Implementar `fixed_text`** · RF-6, RF-37 · ~15 min [P]
  Añade «Puedo ayudarte con temas de: A, B y C.» al texto fijo; sin áreas, el texto tal cual.
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k fixed_text` pasa con 0, 1 y 3 áreas.
- [x] **T-10 — Implementar `chosen` y `OTHER_PROCEDURES`** · RF-27, RF-28, RF-29 · ~20 min (depende de T-5)
  Separa las FAQ elegidas y el primer procedimiento mencionado; el resto de procedimientos van al texto `OTHER_PROCEDURES`.
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k chosen` pasa con 2 FAQ, 1 FAQ + 2 procedimientos y un número fuera de rango.
- [x] **T-11 — Implementar `combine` y `PARTIAL_ANSWER`** · RF-59, (RF-6 y RF-7 de la spec 001) · ~20 min
  Una respuesta tal cual; varias en párrafos con el nombre del área; las áreas sin respuesta, nombradas en `PARTIAL_ANSWER`.
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k combine` pasa con una, dos y una parcial.

## Fase 3 — Recuperador
- [x] **T-12 — Leer el umbral de aclaración** · RF-20, RF-21, RF-22 · ~20 min
  `read_clarify_similarity()` en `src/agents/retriever.py`; `FaqRetriever` recibe `clarify_similarity: float | None`; `build_faq_retriever` lo pasa con 0.55 por defecto.
  Hecho cuando: `uv run pytest -q tests/retriever_test.py -k clarify` pasa con valor ausente (0.55), no numérico, ≥ `rag_min_similarity` (los dos últimos devuelven `None` y registran un aviso con `caplog`).
- [x] **T-13 — Crear `scope_signals` con áreas propias y otro ámbito** · (habilita RF-36, RF-52) · ~25 min
  `ScopeSignals(embedding, own_area_ids, candidates, other_scope_match)`; consultas solo de ids, etiquetas y similitudes; reutiliza el filtrado por ámbito y activo de `search_scope`.
  Hecho cuando: `uv run pytest -q tests/retriever_test.py -k scope_signals` pasa y las sentencias compiladas no seleccionan `answer` ni `steps`.
- [x] **T-14 — Añadir los candidatos a `scope_signals`** · RF-10 · ~20 min
  FAQ y procedimientos entre el umbral de aclaración y el de respuesta, con su etiqueta y área; sin candidatos si el umbral de aclaración es `None`.
  Hecho cuando: `uv run pytest -q tests/retriever_test.py -k candidates` pasa con aciertos por encima, entre y por debajo de los umbrales.
- [x] **T-15 — Crear `search_area` con el embedding del turno** · RF-56 · ~20 min
  FAQ y procedimientos de un área sobre el umbral de respuesta, con campos de los procedimientos, sin llamar al embedder.
  Hecho cuando: `uv run pytest -q tests/retriever_test.py -k search_area` pasa y el `FakeEmbedder` registra 0 llamadas.
- [x] **T-16 — Crear las búsquedas de las tools y `get_faq`** · RF-25, RF-56 · ~25 min
  `search_area_faqs(area_id, query)`, `search_area_procedures(area_id, query)` (con su propio embedding) y `get_faq(area_id, faq_id)` (solo activa y del área).
  Hecho cuando: `uv run pytest -q tests/retriever_test.py -k "area_faqs or area_procedures or get_faq"` pasa, incluida una FAQ inactiva que devuelve `None`.

## Fase 4 — Modelo (`src/agents/llm.py`)
- [x] **T-17 — Crear `CoordinatorOutput` y `GeminiAgentLLM.coordinate`** · RF-5, RF-7, RF-8, RF-23, RF-30, RF-31, RF-35, RF-49, RF-51 · ~25 min
  Kinds de la sección 2 del plan, `area_ids`, `chosen_options` y descripciones con las reglas de la spec; conversión a `CoordinatorReply`; `temperature=0`, `thinking_budget=0`.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k coordinate` pasa con un modelo doble que devuelve cada kind.
- [x] **T-18 — Crear `build_coordinator_messages`** · RF-34, RF-41, RF-42, RF-50 · ~25 min
  Áreas con nombre y descripción, sin FAQ ni procedimientos; etiquetas de las opciones pendientes del usuario; líneas de oferta y de procedimiento en curso solo si aplican.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k coordinator_messages` pasa y ningún texto de respuesta de FAQ aparece en los mensajes.
- [x] **T-19 — Recuperar `ToolSpec`, `AgentStep` y `GeminiAgentLLM.step`** · (habilita RF-55) · ~25 min [P]
  Desde `60a517e^:src/agents/llm.py`: `bind_tools`, `ToolCalls`/`FinalText` y conversión de `tool_calls`.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k step` pasa con una respuesta con tool calls y otra final.
- [x] **T-20 — Crear `build_area_messages`** · RF-49, RF-57 · ~20 min
  Prompt del área, `area_rules`, lo encontrado, lo elegido, el procedimiento en curso y la regla de responder en español.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k area_messages` pasa y el prompt de otra área no aparece en los mensajes.
- [x] **T-21 — Ampliar los dobles del modelo y del recuperador** · (habilita todos los tests de grafo) · ~25 min
  En `tests/fakes.py`: `FakeAgentLLM` guioniza `coordinate` y `step` por área y cuenta llamadas por tipo; traduce los `AgentReply` antiguos (`answer`, `procedure`, `manipulation`…) a guiones nuevos; `FakeRetriever` con señales y búsquedas por área.
  Hecho cuando: la suite sigue en verde y `uv run pytest -q tests/gemini_llm_test.py` no cambia de resultado.

## Fase 5 — Agente de área
- [x] **T-22 — Recuperar `AreaToolbox` con las tools de búsqueda** · RF-56, RF-57 · ~25 min
  `src/agents/tools.py` desde `60a517e^`: `buscar_faq` y `buscar_procedimiento` limitadas al área; registro de evidencias (encontrado, elegido, buscado).
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k toolbox` pasa y una búsqueda nunca devuelve contenido de otra área.
- [x] **T-23 — Añadir la tool terminal `iniciar_procedimiento`** · RF-26 · ~25 min
  Llama a `procedure_flow.handle_procedure` y cierra el agente con su resultado (`ask`, `sent`, `failed`, `gave_up`).
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k iniciar_procedimiento` pasa con los 4 resultados.
- [x] **T-24 — Recuperar el bucle de `run_sub_agent`** · RF-55, RNF-1 · ~25 min
  `src/agents/sub_agent.py` desde `60a517e^` con `AreaAnswer`; tope `max_steps`; un área sin `system_prompt` no llama al modelo.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k "loop or max_steps or sin_prompt"` pasa, con 1 paso en el caso normal y nunca más de `max_steps`.
- [x] **T-25 — Aplicar el guardarraíl de evidencias** · RF-25, RF-45, RF-46 · ~20 min
  Texto final sin evidencias ⇒ `no_answer`; lo elegido cuenta como evidencia aunque esté bajo el umbral.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k guardrail` pasa con y sin evidencias y con una opción elegida.

## Fase 6 — Grafo nuevo con el comportamiento de la spec 001
El grafo nuevo se construye como `build_coordinator_graph` en `src/agents/graph.py`, junto al actual, con sus tests en `tests/coordinator_graph_test.py`; T-31 lo pone en lugar de `build_graph`.
- [x] **T-26 — Definir el estado, el contexto y `AreaTask`** · (habilita RF-24, RF-50 a RF-60) · ~20 min
  `AgentState` con los campos persistentes y por turno de la sección 2 del plan, reductor de `area_answers`, `AgentContext.offer_pending` y `max_steps`, tipos nuevos en `CHECKPOINT_TYPES`.
  Hecho cuando: `uv run pytest -q tests/coordinator_graph_test.py -k checkpoint` pasa serializando y deserializando un estado con una `Clarification`.
- [x] **T-27 — Implementar el nodo `coordinate`** · RF-39, RF-50, RF-51 · ~30 min
  Catálogo; `asyncio.gather` de `llm.coordinate` y `refresh_stale_embeddings` + `scope_signals`; niveles 2, 3 y 5 de RF-39 (manipulación, persona, mixta); reinicio de los campos por turno.
  Hecho cuando: `uv run pytest -q tests/coordinator_graph_test.py -k coordinate` pasa, con un doble que demuestra que las dos tareas se lanzan antes de que termine la primera.
- [x] **T-28 — Implementar `route` y `area_agent` con `Send`** · RF-52, RF-55, RF-57, RF-58 · ~30 min
  Nivel 9: `area_ids` ∩ áreas activas con prompt, respaldo con `own_area_ids` (también si el agente del canal responde `no_answer`, decisión tras T-33); `area_agent` hace `search_area` y `run_sub_agent`.
  Hecho cuando: `uv run pytest -q tests/coordinator_graph_test.py -k route` pasa con dos áreas atendidas en el mismo superpaso y el respaldo.
- [x] **T-29 — Implementar `finalize` para respuestas y procedimientos** · RF-46, RF-47, RF-48, RF-59, RF-60 · ~30 min
  Prioridad de `notification_failed`; procedimiento `ask` guarda `pending_*`; `sent`, `failed`, `gave_up` como hoy; `combine` y auditor por texto; sin respuestas ⇒ `no_answer`; memoria.
  Hecho cuando: `uv run pytest -q tests/coordinator_graph_test.py -k finalize` pasa con respuesta, combinada, parcial, auditor, procedimiento y sin respuesta.
- [x] **T-30 — Enrutar el procedimiento en curso a su área** · RF-53 · ~20 min
  Nivel 7 de RF-39 en `route`: ignora las `area_ids` del coordinador.
  Hecho cuando: `uv run pytest -q tests/coordinator_graph_test.py -k procedimiento_en_curso` pasa en dos turnos con el procedimiento notificado.
- [x] **T-31 — Sustituir `build_graph` por el grafo nuevo** · RF-50 · ~30 min
  `build_graph` pasa a ser el grafo de 4 nodos; se eliminan el nodo `answer`, `respond`, `build_reply_messages` y `search_scope`; se ajustan `chat_orchestrator_test`, `web_chat_ws_test` y `google_chat_test` a los guiones nuevos.
  Hecho cuando: la suite está en verde y `grep -rn "search_scope\|build_reply_messages" src tests` no devuelve nada.
- [x] **T-32 — Portar los casos de la spec 001 a `agent_graph_test.py`** · RF-47, RF-48, RNF-1, RNF-4 · ~30 min
  Mover `tests/coordinator_graph_test.py` a `tests/agent_graph_test.py` y añadir memoria e hilos aislados, seguimiento con contexto, guardarraíl, auditor, web sin contenido interno y recuento de llamadas (FAQ = 2; dos áreas = 3; nunca más de 1 + 4 por área).
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py` pasa y `tests/coordinator_graph_test.py` ya no existe.
- [x] **T-33 — Medir la latencia local con 50 sesiones** · RNF-2 · ~30 min
  Mismas condiciones que la medición de T-100 de la spec 001 (local, `gemini-3.1-flash-lite`, 50 WebSocket con preguntas respondibles por FAQ). Registrar p50, p95 y máximo en R3 del plan y avisar al usuario antes de seguir.
  Hecho cuando: R3 del plan contiene la medición con fecha y el usuario respondió si se sigue.

## Fase 7 — Mensajes fijos y oferta en el grafo
- [ ] **T-34 — Resolver saludo, cierre y fuera de tema en `coordinate`** · RF-3, RF-4, RF-5, RF-7, RF-8, RF-35, RF-37, RF-39, RNF-4 · ~25 min
  Nivel 6 de RF-39 con `fixed_text` y `area_names`; sin texto fijo, error en el log y sigue al nivel 7; saludo con consulta ⇒ delega.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "greeting or closing or off_topic or texto_fijo"` pasa con 1 llamada al modelo por caso y el saludo web sin áreas internas.
- [ ] **T-35 — Responder fuera de tema cuando solo coincide el otro ámbito** · RF-36 · ~15 min
  En `coordinate`: `other_scope_match` sin `own_area_ids` ⇒ `off_topic` tras los niveles 1 a 5.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k otro_ambito` pasa.
- [ ] **T-36 — Resolver la respuesta a la oferta** · RF-41, RF-42 · ~15 min
  Nivel 4: `accept_offer`/`decline_offer` solo con `offer_pending`; sin oferta se tratan como mensaje normal.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k oferta` pasa con y sin `offer_pending`.
- [ ] **T-37 — Mantener el procedimiento ante un mensaje fijo** · RF-43 · ~15 min
  Un saludo con procedimiento en curso no toca `pending_*` ni `procedure_attempts`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k fijo_en_procedimiento` pasa en tres turnos (inicia, saluda, completa).
- [ ] **T-38 — Comprobar que los textos fijos cambian sin reiniciar** · RF-2 · ~10 min [P]
  Dos mensajes con un `load_catalog` doble que cambia el texto entre ambos.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k texto_fijo_cambia` pasa.

## Fase 8 — Aclaraciones y elección
- [ ] **T-39 — Hacer la pregunta con opciones en `finalize`** · RF-10, RF-19 · ~25 min
  Sin respuestas y con `turn_candidates` ⇒ `build_options` + `options_text`, guarda la `Clarification` del usuario, outcome `clarify`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k pregunta_con_opciones` pasa y el contenido de los candidatos no llega al modelo.
- [ ] **T-40 — Hacer la pregunta de áreas** · RF-16, RF-17, RF-18, RF-19 · ~20 min
  Sin candidatos ⇒ `areas_question`; tras ella se permite una pregunta con opciones, no otra de áreas; tras opciones, "sin respuesta".
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k pregunta_de_areas` pasa con la secuencia áreas → opciones → `no_answer`.
- [ ] **T-41 — Guardar y borrar la aclaración por usuario** · RF-24, RF-40 · ~20 min
  Toda salida ≠ `clarify` borra solo la aclaración de ese usuario; otra persona del hilo no la toca.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "aclaracion_por_usuario or descarta_aclaracion"` pasa con dos `Requester` en el mismo hilo.
- [ ] **T-42 — Enrutar la elección de una opción** · RF-23, RF-25, RF-26, RF-34, RF-54 · ~30 min
  Nivel 8: `chosen_options` válidas de la aclaración del mismo usuario ⇒ `Send` al área de cada opción con lo elegido (`get_faq`/`get_procedure`); opción inactiva ⇒ `no_answer`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k eleccion` pasa con FAQ, procedimiento, opción inactiva y elección de otra persona del hilo.
- [ ] **T-43 — Atender varias opciones elegidas** · RF-27, RF-28, RF-29 · ~25 min
  FAQ elegidas combinadas, solo el primer procedimiento iniciado y el resto mencionado con `OTHER_PROCEDURES`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k varias_opciones` pasa con 2 FAQ y con 1 FAQ + 2 procedimientos.
- [ ] **T-44 — Cerrar las respuestas que no eligen opción** · RF-21, RF-32, RF-33 · ~15 min
  Con opciones pendientes: número fuera de rango, «ninguna» o mensaje sin respuesta ⇒ `no_answer`; «2» sin aclaración ⇒ mensaje nuevo.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k no_elige` pasa con los 4 casos.
- [ ] **T-45 — Probar la prioridad de RF-39 por pares contiguos** · RF-39 · ~25 min
  Un test por cada par de niveles (1–2 … 10–11) donde el mensaje cumple ambos y gana el de mayor prioridad.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k prioridad` pasa con 10 casos.

## Fase 9 — Orquestador
- [ ] **T-46 — Pasar `offer_pending` y `agent_max_steps` al contexto** · (habilita RF-41, RF-42, RNF-1) · ~15 min
  `build_agent_context(session, requester, offer_pending=False)` lee `agent_max_steps` (4).
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k contexto` pasa con la property ausente y presente.
- [ ] **T-47 — Responder mensajes fijos y aclaraciones en ambos canales** · RF-9, RF-29, RF-38 · ~20 min
  `greeting`, `closing`, `off_topic` y `clarify` devuelven su texto sin aviso al área ni oferta.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k "fijo or aclaracion"` pasa y el `FakeNotifier` no recibe avisos.
- [ ] **T-48 — Aceptar o rechazar la oferta por texto en el web** · RF-41, RF-42 · ~20 min
  `offer_accepted` ⇒ `answer_offer(True)` + `RequestContact(attempt=1)`; `offer_declined` ⇒ `OFFER_REJECTED` + canales.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k oferta_por_texto` pasa con ambos casos y la fase resultante.
- [ ] **T-49 — Mantener la fase web ante un mensaje fijo** · RF-43, RF-44, RF-61 · ~20 min
  `greeting`/`closing`/`off_topic` no llaman a `reset_to_bot` en `offering_human` ni en `collecting_contact`; `queued` sigue sin llegar al agente.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k mantiene_fase` pasa con las 3 fases.
- [ ] **T-50 — Probar proveedor caído y "sin respuesta" tras aclaración** · RF-38, (RF-32 de la spec 001) · ~15 min
  «hola» con el modelo caído ⇒ servicio no disponible; aclaración fallida fuera de horario ⇒ canales oficiales.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k "caido_saludo or aclaracion_fuera_de_horario"` pasa.

## Fase 10 — Baterías, auditor y documentación
- [ ] **T-51 — Ampliar los nombres internos del auditor** · RF-47 · ~10 min
  `INTERNAL_NAMES` con los kinds nuevos, `area_ids`, `chosen_options` y los nombres de las tools.
  Hecho cuando: `uv run pytest -q tests/audit_test.py` pasa con un texto que contiene `iniciar_procedimiento`.
- [ ] **T-52 — Añadir ataques contra las tools a `jailbreak_check`** · RF-47 · ~15 min [P]
  Ataques que piden usar o nombrar `buscar_faq` e `iniciar_procedimiento`.
  Hecho cuando: `uv run pytest -q tests/jailbreak_check_test.py` pasa y `ATTACKS` tiene al menos 2 ataques nuevos.
- [ ] **T-53 — Crear la batería de clasificación de `behavior_check`** · RNF-5, RF-49 · ~30 min
  `src/cli/behavior_check.py --scope internal|external`: tabla de la spec, un hilo `MemorySaver` por mensaje, notificador que solo registra, compara `outcome`; código 1 si falla alguno.
  Hecho cuando: `uv run pytest -q tests/behavior_check_test.py -k clasificacion` pasa con un grafo de dobles que acierta y otro que falla.
- [ ] **T-54 — Añadir la batería de elección a `behavior_check`** · RNF-5, RF-23, RF-30, RF-31 · ~25 min
  `--faqs ID,ID --procedure ID`: fija la pregunta con `graph.aupdate_state` y comprueba la opción u opciones atendidas por cada mensaje de la spec.
  Hecho cuando: `uv run pytest -q tests/behavior_check_test.py -k eleccion` pasa.
- [ ] **T-55 — Actualizar el README y el plan 001** · todos · ~25 min
  README: grafo de 4 nodos, alta de un área, `rag_clarify_similarity`, `agent_max_steps`, keys nuevas de `agent_prompt`, papel de coordinador de `internal_agent`/`external_agent`, `behavior_check` y oferta por texto. Plan 001: nota en D32 y RNF-10.
  Hecho cuando: `grep -c "rag_clarify_similarity\|agent_max_steps\|behavior_check\|external_greeting" README.md` da al menos 4 y el plan 001 cita la spec 002 en D32.
- [ ] **T-56 — Verificación completa** · todos · ~15 min
  `uv run pyright` y `uv run pytest` (AGENTS.md), y la matriz de cobertura del plan revisada contra los tests creados.
  Hecho cuando: pyright da 0 errores, pytest no tiene fallos y cada test citado en la matriz del plan existe (`uv run pytest --collect-only -q`).

## Fase 11 — Despliegue de prueba
- [ ] **T-57 — Reescribir los prompts de coordinador en la BD** · RF-50 a RF-52 · ~30 min
  `internal_agent` y `external_agent` instruyen clasificar y delegar, conservando las cláusulas de manipulación (D29 de la spec 001).
  Hecho cuando: `jailbreak_check` contra el despliegue termina con código 0.
- [ ] **T-58 — Calibrar `rag_clarify_similarity`** · RF-10, RF-20 · ~25 min
  Medir la similitud de las frases de la demo con las FAQ reales y fijar la property.
  Hecho cuando: R2 del plan registra las similitudes y el valor elegido, y «tengo un problema con mi pago» produce una pregunta con opciones en el web.
- [ ] **T-59 — Ejecutar las baterías y la demo** · RNF-5, todos · ~30 min
  `behavior_check` en ambos ámbitos, la demo de 8 pasos y las 10 preguntas legítimas de la spec 001.
  Hecho cuando: `behavior_check` termina con código 0 en ambos ámbitos y la demo pasa entera (resultado anotado en R3 del plan).
- [ ] **T-60 — Ejecutar la prueba de carga y fijar RNF-2** · RNF-1, RNF-2 · ~30 min
  50 sesiones contra el despliegue de prueba; el usuario fija el umbral con la medición.
  Hecho cuando: R3 del plan registra el p95 y RNF-2 de esta spec (y de la spec 001, si cambia) tiene el umbral decidido.

## Cobertura
| RF | Tareas |
|---|---|
| RF-1 | T-3, T-4 |
| RF-2 | T-4, T-38 |
| RF-3 | T-34 |
| RF-4 | T-34 |
| RF-5 | T-17, T-34 |
| RF-6 | T-9 |
| RF-7 | T-17, T-34 |
| RF-8 | T-17, T-34 |
| RF-9 | T-47 |
| RF-10 | T-14, T-39, T-58 |
| RF-11 | T-6 |
| RF-12 | T-6 |
| RF-13 | T-6 |
| RF-14 | T-7 |
| RF-15 | T-7 |
| RF-16 | T-7, T-40 |
| RF-17 | T-8, T-40 |
| RF-18 | T-8, T-40 |
| RF-19 | T-39, T-40 |
| RF-20 | T-12, T-58 |
| RF-21 | T-12, T-44 |
| RF-22 | T-12 |
| RF-23 | T-17, T-42, T-54 |
| RF-24 | T-5, T-41 |
| RF-25 | T-16, T-25, T-42 |
| RF-26 | T-23, T-42 |
| RF-27 | T-10, T-43 |
| RF-28 | T-10, T-43 |
| RF-29 | T-10, T-43, T-47 |
| RF-30 | T-17, T-54 |
| RF-31 | T-17, T-54 |
| RF-32 | T-44 |
| RF-33 | T-44 |
| RF-34 | T-18, T-42 |
| RF-35 | T-17, T-34 |
| RF-36 | T-35 |
| RF-37 | T-9, T-34 |
| RF-38 | T-47, T-50 |
| RF-39 | T-27, T-34, T-45 |
| RF-40 | T-41 |
| RF-41 | T-18, T-36, T-48 |
| RF-42 | T-18, T-36, T-48 |
| RF-43 | T-37, T-49 |
| RF-44 | T-49 |
| RF-45 | T-25 |
| RF-46 | T-25, T-29 |
| RF-47 | T-29, T-32, T-51, T-52 |
| RF-48 | T-29, T-32 |
| RF-49 | T-17, T-20, T-53 |
| RF-50 | T-18, T-27, T-31, T-57 |
| RF-51 | T-17, T-27 |
| RF-52 | T-28 |
| RF-53 | T-30 |
| RF-54 | T-42 |
| RF-55 | T-24, T-28 |
| RF-56 | T-15, T-16, T-22 |
| RF-57 | T-20, T-22, T-28 |
| RF-58 | T-28 |
| RF-59 | T-11, T-29 |
| RF-60 | T-29 |
| RF-61 | T-49 |
| RNF-1 | T-24, T-32, T-60 |
| RNF-2 | T-33, T-60 |
| RNF-3 | T-3 |
| RNF-4 | T-32, T-34 |
| RNF-5 | T-53, T-54, T-59 |

| Módulo del plan | Tareas |
|---|---|
| `src/agents/llm.py` | T-17 a T-20, T-31 |
| `src/agents/tools.py` | T-22, T-23 |
| `src/agents/sub_agent.py` | T-24, T-25 |
| `src/agents/retriever.py` | T-12 a T-16, T-31 |
| `src/agents/behavior.py` | T-5 a T-11 |
| `src/agents/graph.py` | T-4, T-26 a T-31, T-34 a T-45 |
| `src/agents/audit.py` | T-51 |
| `src/services/chat_orchestrator.py` | T-46 a T-50 |
| `src/cli/behavior_check.py` | T-53, T-54 |
| `src/cli/jailbreak_check.py` | T-52 |
| migración `seed_fixed_messages` | T-3 |
| `README.md`, plan 001 | T-55 |
