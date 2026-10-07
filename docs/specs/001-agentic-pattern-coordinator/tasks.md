# Tareas 001 — Asistente virtual con patrón agéntico coordinador (chatbot-backend)

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 21/59 hechas
Cada tarea dura menos de 30 min y deja los tests en verde. Se hacen en orden; `[P]` = puede ir en paralelo con la anterior.
Salvo que se diga otra cosa, "verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test
se conecta a la BD ni a la red (constitución, punto 6). Los dobles compartidos viven en `tests/fakes.py`, que no es un
archivo de tests.

## Fase 0 — Verificaciones previas
- [x] **T-1 — Verificar pgvector en el servidor PostgreSQL** · (habilita RF-9) · ~15 min
  Consultar `pg_available_extensions` (nombre `vector`) y comprobar que el usuario de la app puede crear extensiones (o pedírselo al DBA). Anotar el resultado en R1 del plan.
  Hecho cuando: R1 del plan dice "vector disponible y creada" o enlaza la solicitud al DBA; con una solicitud abierta, T-9 queda bloqueada.
- [x] **T-2 — Verificar zoneinfo en la imagen base** · (habilita RF-21) · ~10 min [P]
  Ejecutar en `python:3.14-slim` la carga de `ZoneInfo("America/Santiago")`. Anotar el resultado en R7 del plan.
  Hecho cuando: el comando termina con código 0, o R7 registra que hace falta `tzdata` y se pidió su aprobación.

## Fase 1 — Base
- [x] **T-3 — Añadir las dependencias aprobadas** · (habilita todos) · ~15 min
  `uv add` de `langgraph`, `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`, `langchain-google-genai`, `pgvector`, `google-auth` y `argon2-cffi`.
  Hecho cuando: `uv sync --locked` termina sin errores y la suite sigue en verde.
- [x] **T-4 — Crear `Clock` y `FakeClock`** · (habilita RF-34–56, RF-70–79) · ~15 min
  `src/utils/clock.py` con `Clock` (Protocol) y `SystemClock`; `tests/fakes.py` con `FakeClock(now)` y `advance(timedelta)`.
  Hecho cuando: `uv run pytest -q tests/clock_test.py` pasa y comprueba que `SystemClock().now()` es aware y está en UTC.
- [x] **T-5 — Añadir getters tipados de property con valor por defecto** · RF-12 · ~25 min
  `get_int_property`, `get_float_property` y `get_str_property(session, key, default)` en `src/services/property.py`. Lanzan `PropertyNotFoundError` si no hay default. Los tests reinician la caché del módulo.
  Hecho cuando: `uv run pytest -q tests/property_test.py` pasa con estos casos: valor presente, ausente con default, ausente sin default y valor no numérico.
- [x] **T-6 — Crear las excepciones nuevas** · (habilita RF-13, RF-16, RF-18, RF-40, RF-41, RF-60, RF-63, RF-71–75) · ~15 min
  Crear `agent.py`, `auth.py`, `live_chat.py`, `google_chat.py`, `mail.py` y `message.py` (`EmptyMessageError`, `MessageTooLongError`) en `src/utils/exceptions/`, con mensajes en español.
  Hecho cuando: `uv run pyright` da 0 errores y cada clase hereda de `Exception` con docstring en español.

## Fase 2 — Modelo de datos
- [x] **T-7 — Crear los modelos de negocio de áreas y FAQ** · (habilita RF-3–11) · ~25 min
  `src/models/business_area.py` (enum `AreaScope`), `faq_category.py`, `faq.py` (`Vector(768)`, `content_hash` como `Computed`) y `agent_prompt.py`.
  Hecho cuando: `uv run pyright` da 0 errores y los 4 modelos se importan sin error.
- [x] **T-8 — Crear los modelos de horario y contactos** · (habilita RF-19–24, RF-59) · ~15 min
  Crear `service_schedule.py` (CHECK 0–6 y apertura < cierre), `holiday.py`, `official_channel.py` y `fallback_contact.py` en `src/models/`.
  Hecho cuando: `uv run pyright` da 0 errores.
- [x] **T-9 — Generar y revisar la migración A** · (habilita RF-3–11, RF-19–24, RF-59) · ~30 min (depende de T-1)
  Importar los modelos en `alembic/env.py` y ejecutar `alembic revision --autogenerate -m "create business tables"`. Añadir a mano `CREATE EXTENSION IF NOT EXISTS vector`, la creación y el borrado de los enums, el índice HNSW `vector_cosine_ops` y la columna generada.
  Hecho cuando: en una BD local, `alembic upgrade head`, `alembic downgrade -1` y `alembic upgrade head` terminan con código 0, y `\d faq` muestra el índice HNSW y `content_hash` generada.
- [x] **T-10 — Crear los modelos de ejecutivos** · (habilita RF-70–75) · ~15 min
  `src/models/executive.py` y `executive_session.py`, según la sección 3 del plan.
  Hecho cuando: `uv run pyright` da 0 errores.
- [x] **T-11 — Generar y revisar la migración B** · (habilita RF-70–75) · ~20 min
  `alembic revision --autogenerate -m "create executive tables"`, con el índice único sobre `lower(username)` añadido a mano.
  Hecho cuando: el ciclo upgrade/downgrade -1/upgrade termina con código 0 y `\d executive` muestra el índice único sobre `lower(username)`.
- [x] **T-12 — Crear los modelos del chat web** · (habilita RF-25–56, RF-76–81) · ~25 min
  `src/models/web_session.py` (enum `WebPhase`), `live_chat.py` (enums `LiveChatStatus` y `CloseReason`) y `live_chat_message.py`.
  Hecho cuando: `uv run pyright` da 0 errores.
- [x] **T-13 — Generar y revisar la migración C** · (habilita RF-25–56, RF-76–81) · ~25 min
  `alembic revision --autogenerate -m "create web chat tables"`, con el índice único parcial `(web_session_id) WHERE status <> 'closed'` y el índice parcial de `executive_id`.
  Hecho cuando: el ciclo upgrade/downgrade -1/upgrade termina con código 0 y `\d live_chat` muestra ambos índices parciales.

## Fase 3 — Validación, horario y datos de negocio
- [x] **T-14 — Implementar la validación de mensajes** · RF-15, RF-16, RF-17 · ~20 min (depende de T-6)
  `src/services/message_validation.py` con `validate_user_message(text) -> str`.
  Hecho cuando: `uv run pytest -q tests/message_validation_test.py` pasa con estos casos: vacío, solo espacios, 5000 caracteres válido y 5001 rechazado.
- [x] **T-15 — Implementar `is_open` del horario** · RF-19–RF-23 · ~25 min (depende de T-2) [P]
  Función pura `is_open(now, slots, holidays)` en `src/services/schedule.py`, con la franja `[apertura, cierre)` evaluada en America/Santiago.
  Hecho cuando: `uv run pytest -q tests/schedule_test.py` pasa con estos casos: dentro, fuera, día sin franja, festivo, minuto de apertura, minuto de cierre y cambio de horario de verano.
- [x] **T-16 — Implementar los lectores de datos de negocio** · RF-3, RF-4, RF-10, RF-11, RF-24, RF-44, RF-59, RF-62 · ~25 min (depende de T-8)
  `src/services/business_data.py`: `get_areas(session, scope)`, `get_agent_prompt`, `get_official_channels` y `get_fallback_email`, más `load_schedule` en `schedule.py`. Sin caché.
  Hecho cuando: `uv run pytest -q tests/business_data_test.py` pasa. El test usa una sesión falsa y comprueba que la sentencia de `get_areas` filtra por `scope` y por `active`, y que dos llamadas seguidas ejecutan dos consultas.

## Fase 4 — LLM y RAG
- [x] **T-17 — Definir la interfaz `AgentLLM` y sus tipos** · (habilita RF-5–9) · ~20 min
  `src/agents/llm.py` con el Protocol `AgentLLM` y las dataclasses `AreaInfo`, `Classification`, `AreaAnswer` y `FaqHit`; `FakeAgentLLM` en `tests/fakes.py`, que registra las llamadas.
  Hecho cuando: `uv run pyright` da 0 errores con `FakeAgentLLM` tipado como `AgentLLM`.
- [x] **T-18 — Construir `GeminiAgentLLM` desde las properties** · RF-12, RF-13, RF-14, RF-18 · ~30 min
  Fábrica que lee `gemini_model`, `gemini_api_key` y `llm_timeout_seconds`. Si falta la clave o el modelo, lanza `LlmNotConfiguredError` y registra un log sin el valor. Los errores y timeouts de Gemini se convierten en `LlmUnavailableError`.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py` pasa: sin clave ⇒ `LlmNotConfiguredError` y `caplog` no contiene la clave; un cliente que lanza una excepción ⇒ `LlmUnavailableError`.
- [x] **T-19 — Construir los mensajes de `classify`, `answer` y `combine`** · RF-5, RF-6, RF-9 · ~30 min
  Funciones puras `build_classify_messages`, `build_answer_messages` y `build_combine_messages`, con los esquemas de salida estructurada. La respuesta de un área solo incluye su prompt y sus FAQ recuperadas.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py` pasa con un test que comprueba que `build_answer_messages` contiene el prompt del área y las FAQ dadas, y ninguna otra.
- [x] **T-20 — Implementar `FaqRetriever.search`** · RF-9 · ~25 min
  `src/agents/retriever.py`: embedding de la consulta (`RETRIEVAL_QUERY`, 768 dimensiones) con un `Embedder` inyectable, distancia coseno filtrada por área y por `rag_min_similarity`, top `rag_top_k`.
  Hecho cuando: `uv run pytest -q tests/retriever_test.py` pasa: la sentencia compilada filtra por `area_id`, ordena por distancia y descarta los resultados bajo el umbral.
- [x] **T-21 — Implementar `refresh_stale_embeddings`** · RF-11 · ~25 min
  Recalcula solo las FAQ con `embedded_hash IS DISTINCT FROM content_hash` de las áreas dadas (`RETRIEVAL_DOCUMENT`).
  Hecho cuando: `uv run pytest -q tests/retriever_test.py` pasa con un caso en el que el embedder falso solo recibe las FAQ desactualizadas.

## Fase 5 — Grafo y estrategias
- [ ] **T-22 — Implementar el estado del grafo y los nodos `load_context` y `classify`** · RF-3, RF-4, RF-5, RF-8, RF-10, RF-26 · ~30 min
  `src/agents/graph.py` con el estado tipado y `build_graph(scope, llm, retriever, checkpointer)`. `classify` produce `mixed_scope` y `wants_human`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "classify or mixed or human"` pasa.
- [ ] **T-23 — Implementar `answer_area` con fan-out** · RF-5, RF-9 · ~30 min
  Un `Send` por área. Sin FAQ sobre el umbral o sin prompt ⇒ `no_answer` sin llamar a `llm.answer` (D3).
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "answer_area or no_faq or no_prompt"` pasa y `FakeAgentLLM` registra 0 llamadas a `answer` en el caso sin FAQ.
- [ ] **T-24 — Implementar `combine` y los outcomes** · RF-6, RF-7 · ~25 min
  `answered`, `partial` (con indicación de la parte sin respuesta) y `no_answer`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "combine or partial"` pasa.
- [ ] **T-25 — Probar la memoria y el aislamiento de hilos** · RF-76, RF-77, RF-78 · ~20 min
  Grafo con `InMemorySaver`: el segundo mensaje del hilo A ve el primero, y el hilo B no ve nada de A.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "thread"` pasa.
- [ ] **T-26 — Probar que el grafo externo no accede a áreas internas** · RF-3, RF-4, RNF-3 · ~20 min
  El `FakeRetriever` registra las áreas consultadas. Incluye un mensaje que pide revelar el prompt o datos internos.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "rnf3"` pasa y el retriever del grafo externo solo recibió ids de áreas externas.
- [ ] **T-27 — Implementar `ChannelStrategy` y `ExternalStrategy`** · RF-1, RF-2, RF-24, RF-25, RF-32 · ~25 min
  `src/agents/strategies.py`. Dentro de horario ⇒ `offer_human`; fuera ⇒ reformular más los canales oficiales.
  Hecho cuando: `uv run pytest -q tests/channel_strategy_test.py -k external` pasa con un `FakeClock` dentro y fuera de horario.
- [ ] **T-28 — Implementar `Mailer`** · RF-58, RF-60 · ~25 min
  `src/services/mailer.py` con `smtplib` en `asyncio.to_thread` y las properties `smtp_*`. Los errores SMTP se convierten en `MailDeliveryError`.
  Hecho cuando: `uv run pytest -q tests/mailer_test.py` pasa con `smtplib.SMTP` sustituido: envío correcto y error ⇒ `MailDeliveryError`.
- [ ] **T-29 — Implementar `InternalStrategy`** · RF-57, RF-58, RF-59, RF-60, RF-61, RF-62 · ~25 min
  Correo al responsable del área o, si no hay área, al correo general. Si falla el envío, registra un log y responde con el mensaje de contactar directamente al área.
  Hecho cuando: `uv run pytest -q tests/channel_strategy_test.py -k internal` pasa con estos casos: responsable, correo general y fallo con `caplog`.

## Fase 6 — Google Chat (canal interno de punta a punta)
- [ ] **T-30 — Implementar `verify_chat_token`** · RF-63, RF-64 · ~30 min
  En `src/services/google_chat.py`: descarga los certificados de `chat@system.gserviceaccount.com` con httpx, los cachea según `Cache-Control` y valida con `google.auth.jwt.decode` (audiencia `google_chat_audience` y emisor).
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k token` pasa con una clave RSA de test servida por `httpx.MockTransport`: token válido, firma inválida, audiencia distinta y token ausente.
- [ ] **T-31 — Implementar el modelo del evento y `handle_event`** · RF-65, RF-66, RF-67 · ~30 min
  `src/interfaces/google_chat.py`: el DM usa `message.text` y la mención usa `argumentText`. `ADDED_TO_SPACE` ⇒ saludo con los nombres de las áreas internas; los demás eventos ⇒ `{}`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k "dm or mention or added or other_event"` pasa.
- [ ] **T-32 — Implementar `handle_internal_message`** · RF-1, RF-8, RF-13, RF-15, RF-16, RF-17, RF-18 · ~25 min
  En `src/services/chat_orchestrator.py`: valida el mensaje, ejecuta el grafo interno sin checkpointer y aplica `InternalStrategy`. Convierte los errores del LLM en un mensaje de no disponible.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k internal` pasa con estos casos: respondida, mixta, sin respuesta, LLM no configurado y LLM caído.
- [ ] **T-33 — Implementar `ChatApiClient`** · RF-69 · ~30 min
  Token OAuth de la cuenta de servicio (`google_chat_service_account_json`, permiso `chat.bot`) por JWT-bearer con httpx, y `create_message(space, thread, text)` con `messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k api_client` pasa. `httpx.MockTransport` comprueba la URL, el `thread.name` y la cabecera Bearer.
- [ ] **T-34 — Crear el router `POST /api/v1/google-chat/events`** · RF-63, RF-68, RF-69 · ~30 min
  `src/routers/google_chat.py`, registrado en `main.py`. `asyncio.wait_for` con `google_chat_sync_timeout_seconds`; si se agota, responde "Estoy procesando tu consulta…" y publica la respuesta con `ChatApiClient` desde una tarea guardada en `app.state`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k "router or slow"` pasa: 401 sin token y, con un timeout de 0.05 s y un agente lento, respuesta "procesando" y `create_message` llamado con el hilo original.

## Fase 7 — Ejecutivos
- [ ] **T-35 — Implementar el hash Argon2 y el comando `hash_password`** · RF-70, RNF-4 · ~20 min
  `PasswordHasher` configurado en `src/services/executive_auth.py`; `src/cli/hash_password.py` pide la contraseña con `getpass` (sin mostrarla) e imprime el hash.
  Hecho cuando: `uv run pytest -q tests/executive_auth_test.py -k hash` pasa (el hash es distinto de la contraseña y se verifica) y `uv run python -m src.cli.hash_password` imprime un hash `$argon2id$`.
- [ ] **T-36 — Implementar la lógica de login con bloqueo** · RF-71, RF-72, RF-73 · ~30 min
  En `executive_auth.py`: contador de fallos, `locked_until` (`login_max_attempts` y `login_lock_minutes`), error genérico para usuario inexistente, contraseña incorrecta o cuenta bloqueada, y hash ficticio para usuarios inexistentes. Usa `FakeClock` y un repositorio falso.
  Hecho cuando: `uv run pytest -q tests/executive_auth_test.py -k login` pasa con estos casos: correcto; incorrecto; inexistente (mismo mensaje); bloqueo al 5.º fallo; contraseña correcta rechazada durante el bloqueo; desbloqueo a los 15 min.
- [ ] **T-37 — Implementar las sesiones de ejecutivo** · RF-70, RF-74, RF-75 · ~25 min
  Token de 32 bytes guardado como sha256; `authenticate(token)` con caducidad según `executive_session_hours`; `logout`.
  Hecho cuando: `uv run pytest -q tests/executive_auth_test.py -k session` pasa con estos casos: válido, caducado a las 8 h, revocado e inexistente.
- [ ] **T-38 — Crear el router de login y logout** · RF-70, RF-71, RF-75 · ~25 min
  `src/routers/executive.py` (parte HTTP) y `src/interfaces/executive.py`. Dependencia `CurrentExecutive` que lee el Bearer y responde 401 si no es válido.
  Hecho cuando: `uv run pytest -q tests/executive_api_test.py -k "login or logout"` pasa: 200 con token, 401 genérico, 204 en logout, 401 sin token y 503 con la BD caída.

## Fase 8 — Canal web (bot, oferta y cola)
- [ ] **T-39 — Generar la migración D de las tablas del checkpointer** · (habilita RF-76–79) · ~30 min (depende de T-3)
  Añadir `include_object` en `alembic/env.py` para ignorar `checkpoint*`. Migración que ejecuta `AsyncPostgresSaver.MIGRATIONS` y registra sus versiones en `checkpoint_migrations`.
  Hecho cuando: `alembic upgrade head` termina con código 0, `SELECT count(*) FROM checkpoint_migrations` es igual a `len(MIGRATIONS)` y `alembic check` no detecta cambios.
- [ ] **T-40 — Abrir el checkpointer y los grafos en el lifespan** · RF-76, RF-78 · ~25 min
  En `main.py`: pool de psycopg (`max_size` 10, `autocommit`, `dict_row`), `AsyncPostgresSaver` y grafos por ámbito en `app.state`, sin llamar a `.setup()`. Cierre ordenado al apagar.
  Hecho cuando: la suite sigue en verde y `uv run fastapi dev` arranca contra la BD local sin crear tablas (sin entradas nuevas en `checkpoint_migrations`).
- [ ] **T-41 — Implementar la máquina de estados de la sesión web** · RF-25, RF-27, RF-28, RF-29, RF-30, RF-32, RF-33 · ~30 min
  Lógica pura en `src/services/web_session.py`: `bot → offering_human → collecting_contact → queued`, validación del nombre y del correo o teléfono, y máximo 3 intentos.
  Hecho cuando: `uv run pytest -q tests/web_session_test.py` pasa con estos casos: aceptar, rechazar, datos inválidos ×3 ⇒ canales oficiales, y datos válidos ⇒ `queued`.
- [ ] **T-42 — Implementar el SQL de la sesión web** · RF-79, RF-80, RF-81 · ~30 min
  `get_or_create(session_id)` (caducada o inexistente ⇒ nueva, contando `web_session_retention_days` desde `last_message_at`), `heartbeat`, `touch_last_message` y `admit()` con `pg_advisory_xact_lock` y el conteo de conectadas con heartbeat de menos de 90 s frente a `web_max_sessions`.
  Hecho cuando: `uv run pytest -q tests/web_session_test.py -k "sql"` pasa, comprobando sobre las sentencias compiladas el advisory lock y el filtro de 90 s.
- [ ] **T-43 — Implementar `live_chat.enqueue`** · RF-30, RF-31 · ~20 min
  Inserta el chat `waiting` con el nombre, el contacto y `pending_question`. Si ya hay un chat abierto en la sesión (violación del índice único parcial), lo devuelve en vez de crear otro.
  Hecho cuando: `uv run pytest -q tests/live_chat_test.py -k enqueue` pasa, incluido el caso de un chat ya abierto.
- [ ] **T-44 — Definir los mensajes WebSocket del cliente** · (habilita RF-25–56) · ~20 min
  `src/interfaces/web_chat.py`: unión discriminada por `type` con todos los mensajes de la sección 4 del plan.
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k parse` pasa: cada tipo válido se parsea y un tipo desconocido falla la validación.
- [ ] **T-45 — Implementar `handle_web_message`** · RF-2, RF-7, RF-8, RF-13, RF-18, RF-25, RF-26, RF-32, RF-82, RF-83 · ~30 min
  En `chat_orchestrator.py`: valida, ejecuta el grafo externo con `thread_id = session_id`, decide según el outcome con `ExternalStrategy` y la máquina de estados, y convierte `DatabaseUnavailableError` en `service_unavailable` con log.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k web` pasa con estos casos: respondida, parcial, mixta, sin respuesta dentro y fuera de horario, petición de humano, LLM caído y BD caída (con `caplog`).
- [ ] **T-46 — Crear el WebSocket `/ws/v1/chat` (conexión y mensajes)** · RF-2, RF-15, RF-16, RF-17, RF-76, RF-78, RF-80, RF-81, RF-82 · ~30 min
  `src/routers/web_chat.py`: `session`/`busy` al conectar, bucle `message`/`ping`, heartbeat, y descarte de la respuesta si el cliente se desconecta. Registrado en `main.py`.
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k "connect or busy or message or disconnect or db_down"` pasa con los servicios sustituidos por `dependency_overrides`.
- [ ] **T-47 — Completar los flujos de oferta, contacto y cola en el WebSocket** · RF-25–RF-33 · ~25 min
  Manejo de `human_response`, `contact` y `request_human` en el router.
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k "offer or contact or queue or reject or request_human"` pasa.

## Fase 9 — Chat en vivo
- [ ] **T-48 — Implementar el dominio del chat en vivo** · RF-34, RF-39, RF-40, RF-41, RF-47, RF-50, RF-51, RF-53, RF-55 · ~30 min
  Funciones puras de transición en `src/services/live_chat.py`: tomar, límite por ejecutivo, desconexión y retoma antes de 60 min, vencimiento del plazo, salida del cliente y cierre por el ejecutivo.
  Hecho cuando: `uv run pytest -q tests/live_chat_test.py -k domain` pasa con `FakeClock`, incluida la doble toma ⇒ `ChatAlreadyAssignedError`.
- [ ] **T-49 — Implementar el SQL del chat en vivo** · RF-39, RF-40, RF-41, RF-42, RF-55 · ~30 min
  `take` (bloqueo `FOR UPDATE` de la fila del ejecutivo, conteo frente a `executive_max_chats`, `UPDATE … WHERE status='waiting' RETURNING`), `list_waiting` FIFO, `post_message` y `close`.
  Hecho cuando: `uv run pytest -q tests/live_chat_test.py -k sql` pasa, comprobando en las sentencias compiladas `FOR UPDATE` y `status = 'waiting'` en el `WHERE` del `UPDATE`.
- [ ] **T-50 — Implementar `ConnectionHub` y LISTEN/NOTIFY** · RF-43, RF-44, RF-45, RF-48, RF-52, RF-54, RF-56 · ~30 min
  `src/services/realtime.py`: registro local de sockets, `publish` con `pg_notify` (payload solo con ids) y un listener asyncpg que reparte los eventos. `FakeHub` en `tests/fakes.py`.
  Hecho cuando: `uv run pytest -q tests/realtime_test.py` pasa: el payload nunca contiene el texto del mensaje y el despacho entrega cada evento solo al socket local destinatario.
- [ ] **T-51 — Crear el router de `live-chats`** · RF-39, RF-40, RF-41, RF-42, RF-55, RF-74, RF-75 · ~30 min
  `src/routers/live_chat.py` y `src/interfaces/live_chat.py`: `GET` en espera, `POST take` (resumen) y `POST close` (solo el ejecutivo asignado).
  Hecho cuando: `uv run pytest -q tests/executive_api_test.py -k live_chats` pasa con 200, 401, 403, 404, los dos tipos de 409 y 503.
- [ ] **T-52 — Crear el WebSocket `/ws/v1/executive`** · RF-44, RF-45, RF-47, RF-49, RF-50, RF-54, RF-75 · ~30 min
  En `src/routers/executive.py`: el primer mensaje `auth` (o 4401), `assigned_chats` al conectar (retoma), reenvío de mensajes y `mark_executive_disconnected` al cerrar el socket o al caducar la sesión.
  Hecho cuando: `uv run pytest -q tests/executive_ws_test.py` pasa con estos casos: 4401, retoma con chats asignados, mensaje del ejecutivo publicado en el hub, aviso de chat cerrado y sesión caducada tratada como desconexión.
- [ ] **T-53 — Implementar la fase en vivo en el WebSocket del cliente** · RF-35, RF-43, RF-44, RF-45, RF-46, RF-48, RF-53, RF-54, RF-56 · ~30 min
  En la fase `live` el bot no responde y los mensajes se reenvían al ejecutivo. Eventos `executive_joined`, `executive_disconnected` y `chat_closed`. Si el cliente se desconecta, el chat sale de la cola (si estaba en espera) o se cierra con aviso al ejecutivo (si estaba asignado).
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k live` pasa y `FakeAgentLLM` registra 0 llamadas durante la fase en vivo.

## Fase 10 — Barrido periódico
- [ ] **T-54 — Implementar las decisiones del barrido** · RF-36, RF-37, RF-38, RF-51, RF-52, RF-79 · ~30 min
  Funciones puras en `src/services/sweeper.py`: chats en espera al terminar el horario, ejecutivos desconectados más de `executive_reconnect_minutes`, heartbeats de más de 90 s y sesiones caducadas.
  Hecho cuando: `uv run pytest -q tests/sweeper_test.py` pasa con `FakeClock`, incluido el caso de que los chats asignados no se cierren al terminar el horario.
- [ ] **T-55 — Ejecutar el barrido en el lifespan** · RF-36, RF-51, RF-79, RF-81 · ~30 min
  Bucle de 30 s con `pg_try_advisory_lock`: aplica las decisiones por SQL, publica los eventos en el hub y llama a `checkpointer.adelete_thread` antes de borrar cada sesión. Se cancela al apagar.
  Hecho cuando: `uv run pytest -q tests/sweeper_test.py -k runner` pasa (sin el lock no ejecuta nada; con el lock llama a `adelete_thread` una vez por sesión caducada) y la suite sigue en verde.

## Cierre
- [ ] **T-56 — Ejecutar la prueba de carga del RNF-2** · RNF-1, RNF-2 · ~30 min
  50 sesiones WebSocket simultáneas contra el despliegue de prueba, con FAQ cargadas, midiendo hasta la respuesta completa. Si el p95 supera 5000 ms, actualizar RNF-2 de la spec a 8000 ms (decisión R2).
  Hecho cuando: R2 del plan registra el p95 medido y, si superó 5000 ms, RNF-2 de la spec dice 8000 ms.
- [ ] **T-57 — Actualizar el README** · todos · ~30 min
  Documentar los endpoints y WebSockets (sección 4 del plan), todas las properties nuevas, las tablas que hay que cargar, la extensión `vector`, el comando `hash_password` y la nota sobre las migraciones del checkpointer (R8).
  Hecho cuando: `README.md` contiene cada ruta de la sección 4 y cada key de property del plan (comprobado con `grep`) y enlaza a `docs/specs/001-agentic-pattern-coordinator/spec.md`.
- [ ] **T-58 — Calibrar `rag_min_similarity`** · RF-9 · ~20 min
  Cuando el usuario entregue las áreas y FAQ reales (R3), probar 10 preguntas por área y fijar el umbral.
  Hecho cuando: R3 del plan registra el valor elegido y la tasa de aciertos de las 10 preguntas por área.
- [ ] **T-59 — Verificación completa y demo** · todos · ~30 min
  `uv run pyright` y `uv run pytest` en local, y los 8 pasos de la demo manual de la spec en el despliegue contra PostgreSQL real.
  Hecho cuando: ambos comandos terminan con código 0 y la salida se adjunta; los 8 pasos de la demo quedan marcados en la sección "Criterios de finalización" de la spec.

## Cobertura
| RF | Tareas |
|---|---|
| RF-1 | T-27, T-32, T-34 |
| RF-2 | T-27, T-45, T-46 |
| RF-3, RF-4 | T-16, T-22, T-26 |
| RF-5 | T-19, T-22, T-23 |
| RF-6 | T-19, T-24 |
| RF-7 | T-24, T-45 |
| RF-8 | T-22, T-32, T-45 |
| RF-9 | T-19, T-20, T-23, T-58 |
| RF-10 | T-16, T-22 |
| RF-11 | T-16, T-21 |
| RF-12 | T-5, T-18 |
| RF-13, RF-14 | T-18, T-32, T-45 |
| RF-15, RF-16, RF-17 | T-14, T-32, T-46 |
| RF-18 | T-18, T-32, T-45 |
| RF-19–RF-23 | T-15, T-16 |
| RF-24 | T-16, T-27 |
| RF-25 | T-27, T-41, T-45, T-47 |
| RF-26 | T-22, T-45, T-47 |
| RF-27, RF-28, RF-29 | T-41, T-47 |
| RF-30, RF-31 | T-41, T-43, T-47 |
| RF-32, RF-33 | T-27, T-41, T-45, T-47 |
| RF-34 | T-48 |
| RF-35 | T-53 |
| RF-36, RF-37, RF-38 | T-54, T-55 |
| RF-39, RF-40, RF-41 | T-48, T-49, T-51 |
| RF-42 | T-49, T-51 |
| RF-43 | T-50, T-53 |
| RF-44, RF-45 | T-50, T-52, T-53 |
| RF-46 | T-53 |
| RF-47 | T-48, T-52 |
| RF-48 | T-50, T-53 |
| RF-49 | T-52 |
| RF-50 | T-48, T-52 |
| RF-51, RF-52 | T-48, T-50, T-54, T-55 |
| RF-53, RF-54 | T-48, T-50, T-52, T-53 |
| RF-55 | T-48, T-49, T-51 |
| RF-56 | T-50, T-53 |
| RF-57, RF-61 | T-29 |
| RF-58, RF-60 | T-28, T-29 |
| RF-59, RF-62 | T-16, T-29 |
| RF-63, RF-64 | T-30, T-34 |
| RF-65, RF-66, RF-67 | T-31 |
| RF-68 | T-34 |
| RF-69 | T-33, T-34 |
| RF-70 | T-35, T-37, T-38 |
| RF-71, RF-72, RF-73 | T-36, T-38 |
| RF-74, RF-75 | T-37, T-38, T-51, T-52 |
| RF-76, RF-77, RF-78 | T-25, T-40, T-46 |
| RF-79 | T-42, T-54, T-55 |
| RF-80 | T-42, T-46 |
| RF-81 | T-42, T-46, T-55 |
| RF-82, RF-83 | T-45, T-46 |
| RNF-1, RNF-2 | T-56 |
| RNF-3 | T-26 |
| RNF-4 | T-35 |

| Módulo del plan | Tareas |
|---|---|
| `pyproject.toml` / `uv.lock` | T-3 |
| `src/utils/clock.py` | T-4 |
| `src/services/property.py` | T-5 |
| `src/utils/exceptions/*` | T-6 |
| `src/models/*` + migraciones A–C | T-7–T-13 |
| `alembic/env.py` + migración D | T-9, T-39 |
| `src/services/message_validation.py` | T-14 |
| `src/services/schedule.py` | T-15, T-16 |
| `src/services/business_data.py` | T-16 |
| `src/agents/llm.py` | T-17, T-18, T-19 |
| `src/agents/retriever.py` | T-20, T-21 |
| `src/agents/graph.py` | T-22–T-26 |
| `src/agents/strategies.py` | T-27, T-29 |
| `src/services/mailer.py` | T-28 |
| `src/services/google_chat.py` | T-30, T-31, T-33 |
| `src/services/chat_orchestrator.py` | T-32, T-45 |
| `src/routers/google_chat.py` | T-34 |
| `src/services/executive_auth.py` + `src/cli/hash_password.py` | T-35, T-36, T-37 |
| `src/routers/executive.py` | T-38, T-52 |
| `main.py` (lifespan) | T-40, T-55 |
| `src/services/web_session.py` | T-41, T-42 |
| `src/services/live_chat.py` | T-43, T-48, T-49 |
| `src/interfaces/*` | T-31, T-38, T-44, T-51 |
| `src/routers/web_chat.py` | T-46, T-47, T-53 |
| `src/services/realtime.py` | T-50 |
| `src/routers/live_chat.py` | T-51 |
| `src/services/sweeper.py` | T-54, T-55 |
| `README.md` | T-57 |
