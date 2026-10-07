# Tareas 001 — Asistente virtual con patrón agéntico coordinador (chatbot-backend)

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 77/88 hechas
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
- [x] **T-22 — Implementar el estado del grafo y los nodos `load_context` y `classify`** · RF-3, RF-4, RF-5, RF-8, RF-10, RF-26 · ~30 min
  `src/agents/graph.py` con el estado tipado y `build_graph(scope, llm, retriever, checkpointer)`. `classify` produce `mixed_scope` y `wants_human`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "classify or mixed or human"` pasa.
- [x] **T-23 — Implementar `answer_area` con fan-out** · RF-5, RF-9 · ~30 min
  Un `Send` por área. Sin FAQ sobre el umbral o sin prompt ⇒ `no_answer` sin llamar a `llm.answer` (D3).
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "answer_area or no_faq or no_prompt"` pasa y `FakeAgentLLM` registra 0 llamadas a `answer` en el caso sin FAQ.
- [x] **T-24 — Implementar `combine` y los outcomes** · RF-6, RF-7 · ~25 min
  `answered`, `partial` (con indicación de la parte sin respuesta) y `no_answer`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "combine or partial"` pasa.
- [x] **T-25 — Probar la memoria y el aislamiento de hilos** · RF-76, RF-77, RF-78 · ~20 min
  Grafo con `InMemorySaver`: el segundo mensaje del hilo A ve el primero, y el hilo B no ve nada de A.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "thread"` pasa.
- [x] **T-26 — Probar que el grafo externo no accede a áreas internas** · RF-3, RF-4, RNF-3 · ~20 min
  El `FakeRetriever` registra las áreas consultadas. Incluye un mensaje que pide revelar el prompt o datos internos.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "rnf3"` pasa y el retriever del grafo externo solo recibió ids de áreas externas.
- [x] **T-27 — Implementar `ChannelStrategy` y `ExternalStrategy`** · RF-1, RF-2, RF-24, RF-25, RF-32 · ~25 min
  `src/agents/strategies.py`. Dentro de horario ⇒ `offer_human`; fuera ⇒ reformular más los canales oficiales.
  Hecho cuando: `uv run pytest -q tests/channel_strategy_test.py -k external` pasa con un `FakeClock` dentro y fuera de horario.
- [x] **T-28 — Implementar `Mailer`** · RF-58, RF-60 · ~25 min
  `src/services/mailer.py` con `smtplib` en `asyncio.to_thread` y las properties `smtp_*`. Los errores SMTP se convierten en `MailDeliveryError`.
  Hecho cuando: `uv run pytest -q tests/mailer_test.py` pasa con `smtplib.SMTP` sustituido: envío correcto y error ⇒ `MailDeliveryError`.
- [x] **T-29 — Implementar `InternalStrategy`** · RF-57, RF-58, RF-59, RF-60, RF-61, RF-62 · ~25 min
  Correo al responsable del área o, si no hay área, al correo general. Si falla el envío, registra un log y responde con el mensaje de contactar directamente al área.
  Hecho cuando: `uv run pytest -q tests/channel_strategy_test.py -k internal` pasa con estos casos: responsable, correo general y fallo con `caplog`.

## Fase 6 — Google Chat (canal interno de punta a punta)
- [x] **T-30 — Implementar `verify_chat_token`** · RF-63, RF-64 · ~30 min
  En `src/services/google_chat.py`: descarga los certificados de `chat@system.gserviceaccount.com` con httpx, los cachea según `Cache-Control` y valida con `google.auth.jwt.decode` (audiencia `google_chat_audience` y emisor).
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k token` pasa con una clave RSA de test servida por `httpx.MockTransport`: token válido, firma inválida, audiencia distinta y token ausente.
- [x] **T-31 — Implementar el modelo del evento y `handle_event`** · RF-65, RF-66, RF-67 · ~30 min
  `src/interfaces/google_chat.py`: el DM usa `message.text` y la mención usa `argumentText`. `ADDED_TO_SPACE` ⇒ saludo con los nombres de las áreas internas; los demás eventos ⇒ `{}`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k "dm or mention or added or other_event"` pasa.
- [x] **T-32 — Implementar `handle_internal_message`** · RF-1, RF-8, RF-13, RF-15, RF-16, RF-17, RF-18 · ~25 min
  En `src/services/chat_orchestrator.py`: valida el mensaje, ejecuta el grafo interno sin checkpointer y aplica `InternalStrategy`. Convierte los errores del LLM en un mensaje de no disponible.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k internal` pasa con estos casos: respondida, mixta, sin respuesta, LLM no configurado y LLM caído.
- [x] **T-33 — Implementar `ChatApiClient`** · RF-69 · ~30 min
  Token OAuth de la cuenta de servicio (`google_chat_service_account_json`, permiso `chat.bot`) por JWT-bearer con httpx, y `create_message(space, thread, text)` con `messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k api_client` pasa. `httpx.MockTransport` comprueba la URL, el `thread.name` y la cabecera Bearer.
- [x] **T-34 — Crear el router `POST /api/v1/google-chat/events`** · RF-63, RF-68, RF-69 · ~30 min
  `src/routers/google_chat.py`, registrado en `main.py`. `asyncio.wait_for` con `google_chat_sync_timeout_seconds`; si se agota, responde "Estoy procesando tu consulta…" y publica la respuesta con `ChatApiClient` desde una tarea guardada en `app.state`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k "router or slow"` pasa: 401 sin token y, con un timeout de 0.05 s y un agente lento, respuesta "procesando" y `create_message` llamado con el hilo original.

## Fase 7 — Ejecutivos
- [x] **T-35 — Implementar el hash Argon2 y el comando `hash_password`** · RF-70, RNF-4 · ~20 min
  `PasswordHasher` configurado en `src/services/executive_auth.py`; `src/cli/hash_password.py` pide la contraseña con `getpass` (sin mostrarla) e imprime el hash.
  Hecho cuando: `uv run pytest -q tests/executive_auth_test.py -k hash` pasa (el hash es distinto de la contraseña y se verifica) y `uv run python -m src.cli.hash_password` imprime un hash `$argon2id$`.
- [x] **T-36 — Implementar la lógica de login con bloqueo** · RF-71, RF-72, RF-73 · ~30 min
  En `executive_auth.py`: contador de fallos, `locked_until` (`login_max_attempts` y `login_lock_minutes`), error genérico para usuario inexistente, contraseña incorrecta o cuenta bloqueada, y hash ficticio para usuarios inexistentes. Usa `FakeClock` y un repositorio falso.
  Hecho cuando: `uv run pytest -q tests/executive_auth_test.py -k login` pasa con estos casos: correcto; incorrecto; inexistente (mismo mensaje); bloqueo al 5.º fallo; contraseña correcta rechazada durante el bloqueo; desbloqueo a los 15 min.
- [x] **T-37 — Implementar las sesiones de ejecutivo** · RF-70, RF-74, RF-75 · ~25 min
  Token de 32 bytes guardado como sha256; `authenticate(token)` con caducidad según `executive_session_hours`; `logout`.
  Hecho cuando: `uv run pytest -q tests/executive_auth_test.py -k session` pasa con estos casos: válido, caducado a las 8 h, revocado e inexistente.
- [x] **T-38 — Crear el router de login y logout** · RF-70, RF-71, RF-75 · ~25 min
  `src/routers/executive.py` (parte HTTP) y `src/interfaces/executive.py`. Dependencia `CurrentExecutive` que lee el Bearer y responde 401 si no es válido.
  Hecho cuando: `uv run pytest -q tests/executive_api_test.py -k "login or logout"` pasa: 200 con token, 401 genérico, 204 en logout, 401 sin token y 503 con la BD caída.

## Fase 8 — Canal web (bot, oferta y cola)
- [x] **T-39 — Generar la migración D de las tablas del checkpointer** · (habilita RF-76–79) · ~30 min (depende de T-3)
  Añadir `include_object` en `alembic/env.py` para ignorar `checkpoint*`. Migración que ejecuta `AsyncPostgresSaver.MIGRATIONS` y registra sus versiones en `checkpoint_migrations`.
  Hecho cuando: `alembic upgrade head` termina con código 0, `SELECT count(*) FROM checkpoint_migrations` es igual a `len(MIGRATIONS)` y `alembic check` no detecta cambios.
- [x] **T-40 — Abrir el checkpointer y los grafos en el lifespan** · RF-76, RF-78 · ~25 min
  En `main.py`: pool de psycopg (`max_size` 10, `autocommit`, `dict_row`), `AsyncPostgresSaver` y grafos por ámbito en `app.state`, sin llamar a `.setup()`. Cierre ordenado al apagar.
  Hecho cuando: la suite sigue en verde y `uv run fastapi dev` arranca contra la BD local sin crear tablas (sin entradas nuevas en `checkpoint_migrations`).
- [x] **T-41 — Implementar la máquina de estados de la sesión web** · RF-25, RF-27, RF-28, RF-29, RF-30, RF-32, RF-33 · ~30 min
  Lógica pura en `src/services/web_session.py`: `bot → offering_human → collecting_contact → queued`, validación del nombre y del correo o teléfono, y máximo 3 intentos.
  Hecho cuando: `uv run pytest -q tests/web_session_test.py` pasa con estos casos: aceptar, rechazar, datos inválidos ×3 ⇒ canales oficiales, y datos válidos ⇒ `queued`.
- [x] **T-42 — Implementar el SQL de la sesión web** · RF-79, RF-80, RF-81 · ~30 min
  `get_or_create(session_id)` (caducada o inexistente ⇒ nueva, contando `web_session_retention_days` desde `last_message_at`), `heartbeat`, `touch_last_message` y `admit()` con `pg_advisory_xact_lock` y el conteo de conectadas con heartbeat de menos de 90 s frente a `web_max_sessions`.
  Hecho cuando: `uv run pytest -q tests/web_session_test.py -k "sql"` pasa, comprobando sobre las sentencias compiladas el advisory lock y el filtro de 90 s.
- [x] **T-43 — Implementar `live_chat.enqueue`** · RF-30, RF-31 · ~20 min
  Inserta el chat `waiting` con el nombre, el contacto y `pending_question`. Si ya hay un chat abierto en la sesión (violación del índice único parcial), lo devuelve en vez de crear otro.
  Hecho cuando: `uv run pytest -q tests/live_chat_test.py -k enqueue` pasa, incluido el caso de un chat ya abierto.
- [x] **T-44 — Definir los mensajes WebSocket del cliente** · (habilita RF-25–56) · ~20 min
  `src/interfaces/web_chat.py`: unión discriminada por `type` con todos los mensajes de la sección 4 del plan.
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k parse` pasa: cada tipo válido se parsea y un tipo desconocido falla la validación.
- [x] **T-45 — Implementar `handle_web_message`** · RF-2, RF-7, RF-8, RF-13, RF-18, RF-25, RF-26, RF-32, RF-82, RF-83 · ~30 min
  En `chat_orchestrator.py`: valida, ejecuta el grafo externo con `thread_id = session_id`, decide según el outcome con `ExternalStrategy` y la máquina de estados, y convierte `DatabaseUnavailableError` en `service_unavailable` con log.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k web` pasa con estos casos: respondida, parcial, mixta, sin respuesta dentro y fuera de horario, petición de humano, LLM caído y BD caída (con `caplog`).
- [x] **T-46 — Crear el WebSocket `/ws/v1/chat` (conexión y mensajes)** · RF-2, RF-15, RF-16, RF-17, RF-76, RF-78, RF-80, RF-81, RF-82 · ~30 min
  `src/routers/web_chat.py`: `session`/`busy` al conectar, bucle `message`/`ping`, heartbeat, y descarte de la respuesta si el cliente se desconecta. Registrado en `main.py`.
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k "connect or busy or message or disconnect or db_down"` pasa con los servicios sustituidos por `dependency_overrides`.
- [x] **T-47 — Completar los flujos de oferta, contacto y cola en el WebSocket** · RF-25–RF-33 · ~25 min
  Manejo de `human_response`, `contact` y `request_human` en el router.
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k "offer or contact or queue or reject or request_human"` pasa.

## Fase 9 — Chat en vivo
- [x] **T-48 — Implementar el dominio del chat en vivo** · RF-34, RF-39, RF-40, RF-41, RF-47, RF-50, RF-51, RF-53, RF-55 · ~30 min
  Funciones puras de transición en `src/services/live_chat.py`: tomar, límite por ejecutivo, desconexión y retoma antes de 60 min, vencimiento del plazo, salida del cliente y cierre por el ejecutivo.
  Hecho cuando: `uv run pytest -q tests/live_chat_test.py -k domain` pasa con `FakeClock`, incluida la doble toma ⇒ `ChatAlreadyAssignedError`.
- [x] **T-49 — Implementar el SQL del chat en vivo** · RF-39, RF-40, RF-41, RF-42, RF-55 · ~30 min
  `take` (bloqueo `FOR UPDATE` de la fila del ejecutivo, conteo frente a `executive_max_chats`, `UPDATE … WHERE status='waiting' RETURNING`), `list_waiting` FIFO, `post_message` y `close`.
  Hecho cuando: `uv run pytest -q tests/live_chat_test.py -k sql` pasa, comprobando en las sentencias compiladas `FOR UPDATE` y `status = 'waiting'` en el `WHERE` del `UPDATE`.
- [x] **T-50 — Implementar `ConnectionHub` y LISTEN/NOTIFY** · RF-43, RF-44, RF-45, RF-48, RF-52, RF-54, RF-56 · ~30 min
  `src/services/realtime.py`: registro local de sockets, `publish` con `pg_notify` (payload solo con ids) y un listener asyncpg que reparte los eventos. `FakeHub` en `tests/fakes.py`.
  Hecho cuando: `uv run pytest -q tests/realtime_test.py` pasa: el payload nunca contiene el texto del mensaje y el despacho entrega cada evento solo al socket local destinatario.
- [x] **T-51 — Crear el router de `live-chats`** · RF-39, RF-40, RF-41, RF-42, RF-55, RF-74, RF-75 · ~30 min
  `src/routers/live_chat.py` y `src/interfaces/live_chat.py`: `GET` en espera, `POST take` (resumen) y `POST close` (solo el ejecutivo asignado).
  Hecho cuando: `uv run pytest -q tests/executive_api_test.py -k live_chats` pasa con 200, 401, 403, 404, los dos tipos de 409 y 503.
- [x] **T-52 — Crear el WebSocket `/ws/v1/executive`** · RF-44, RF-45, RF-47, RF-49, RF-50, RF-54, RF-75 · ~30 min
  En `src/routers/executive.py`: el primer mensaje `auth` (o 4401), `assigned_chats` al conectar (retoma), reenvío de mensajes y `mark_executive_disconnected` al cerrar el socket o al caducar la sesión.
  Hecho cuando: `uv run pytest -q tests/executive_ws_test.py` pasa con estos casos: 4401, retoma con chats asignados, mensaje del ejecutivo publicado en el hub, aviso de chat cerrado y sesión caducada tratada como desconexión.
- [x] **T-53 — Implementar la fase en vivo en el WebSocket del cliente** · RF-35, RF-43, RF-44, RF-45, RF-46, RF-48, RF-53, RF-54, RF-56 · ~30 min
  En la fase `live` el bot no responde y los mensajes se reenvían al ejecutivo. Eventos `executive_joined`, `executive_disconnected` y `chat_closed`. Si el cliente se desconecta, el chat sale de la cola (si estaba en espera) o se cierra con aviso al ejecutivo (si estaba asignado).
  Hecho cuando: `uv run pytest -q tests/web_chat_ws_test.py -k live` pasa y `FakeAgentLLM` registra 0 llamadas durante la fase en vivo.

## Fase 10 — Barrido periódico
- [x] **T-54 — Implementar las decisiones del barrido** · RF-36, RF-37, RF-38, RF-51, RF-52, RF-79 · ~30 min
  Funciones puras en `src/services/sweeper.py`: chats en espera al terminar el horario, ejecutivos desconectados más de `executive_reconnect_minutes`, heartbeats de más de 90 s y sesiones caducadas.
  Hecho cuando: `uv run pytest -q tests/sweeper_test.py` pasa con `FakeClock`, incluido el caso de que los chats asignados no se cierren al terminar el horario.
- [x] **T-55 — Ejecutar el barrido en el lifespan** · RF-36, RF-51, RF-79, RF-81 · ~30 min
  Bucle de 30 s con `pg_try_advisory_lock`: aplica las decisiones por SQL, publica los eventos en el hub y llama a `checkpointer.adelete_thread` antes de borrar cada sesión. Se cancela al apagar.
  Hecho cuando: `uv run pytest -q tests/sweeper_test.py -k runner` pasa (sin el lock no ejecuta nada; con el lock llama a `adelete_thread` una vez por sesión caducada) y la suite sigue en verde.

## Cierre de las fases 0–10
- [x] **T-57 — Actualizar el README** · todos · ~30 min
  Documentar los endpoints y WebSockets (sección 4 del plan), todas las properties nuevas, las tablas que hay que cargar, la extensión `vector`, el comando `hash_password` y la nota sobre las migraciones del checkpointer (R8).
  Hecho cuando: `README.md` contiene cada ruta de la sección 4 y cada key de property del plan (comprobado con `grep`) y enlaza a `docs/specs/001-agentic-pattern-coordinator/spec.md`.
- [x] **T-58 — Calibrar `rag_min_similarity`** · RF-9 · ~20 min
  Cuando el usuario entregue las áreas y FAQ reales (R3), probar 10 preguntas por área y fijar el umbral.
  Hecho cuando: R3 del plan registra el valor elegido y la tasa de aciertos de las 10 preguntas por área.

## Fase 11 — Ampliación: modelo de datos
- [x] **T-60 — Crear los modelos de procedimientos** · (habilita RF-85, RF-91–98) · ~25 min
  `src/models/procedure.py` (`Vector(768)`, `content_hash` como `Computed`, índice HNSW) y `src/models/procedure_field.py` (enum `FieldKind`: `text`, `email`, `phone`, `rut`, `number`, `date`; único `procedure_id` + `name`).
  Hecho cuando: `uv run pyright` da 0 errores y ambos modelos se importan sin error.
- [x] **T-61 — Ajustar los modelos de área, space general y conversación de Google Chat** · (habilita RF-62, RF-105) · ~20 min [P]
  `business_area`: añade `chat_space` y quita `owner_email`. `fallback_contact.py` → `fallback_space.py` (`scope` PK, `chat_space` NOT NULL). Nuevo `src/models/chat_thread.py` (`conversation_id` PK, `last_message_at` con índice).
  Hecho cuando: `uv run pyright` da 0 errores.
- [x] **T-62 — Generar y revisar la migración E** · (habilita RF-62, RF-85, RF-105) · ~30 min (depende de T-60, T-61)
  `alembic revision --autogenerate -m "add procedures and chat spaces"`, ajustada a mano: enum `field_kind` creado y borrado de forma explícita, columna generada, índice HNSW, renombrado de `fallback_contact` con borrado de sus filas, y downgrade completo.
  Hecho cuando: en la BD local, `alembic upgrade head`, `alembic downgrade -1` y `alembic upgrade head` terminan con código 0, y `alembic check` no detecta cambios.

## Fase 12 — Ampliación: validación de procedimientos y aviso al área
- [x] **T-63 — Implementar los validadores de campos de procedimiento** · RF-92, RF-93, RF-98 · ~25 min
  `src/services/procedures.py`: `validate_field(kind, value)`, `missing_or_invalid(fields, datos)` y `web_contact_fields()`.
  Hecho cuando: `uv run pytest -q tests/procedures_test.py -k validate` pasa con estos casos: RUT con dígito verificador correcto e incorrecto, correo, teléfono, número, fecha `dd-mm-aaaa`, texto vacío, y web sin nombre o sin contacto.
- [x] **T-64 — Permitir `create_message` sin hilo** · (habilita RF-58, RF-95) · ~15 min [P]
  `ChatApiClient.create_message(space, text, thread=None)`; sin hilo no se envía `messageReplyOption`. La publicación diferida de `src/routers/google_chat.py` pasa el hilo por nombre.
  Hecho cuando: `uv run pytest -q tests/area_notifier_test.py -k create_message tests/google_chat_test.py -k "api_client or slow"` pasa.
- [x] **T-65 — Implementar `AreaNotifier` y el formato de las notificaciones** · RF-58, RF-59, RF-95, RF-96, RF-97, RNF-8 · ~30 min (depende de T-64)
  `src/services/area_notifier.py` con `notify(space, text)`, `format_request(procedure, datos, requester)` y `format_unanswered(question, area, requester)`; `NotificationDeliveryError` en `src/utils/exceptions/notification.py`.
  Hecho cuando: `uv run pytest -q tests/area_notifier_test.py tests/procedures_test.py -k "notify or format"` pasa, incluido un caso con `caplog` en el que los datos del usuario no aparecen en el log y un error HTTP que acaba en `NotificationDeliveryError`.

## Fase 13 — Ampliación: aviso interno por Google Chat
- [x] **T-66 — Leer los spaces de las áreas y el space general** · RF-59, RF-62 · ~20 min (depende de T-62)
  `get_fallback_space(session, scope)` en `business_data.py`, en lugar de `get_fallback_email`. `AreaInfo.chat_space` en lugar de `owner_email`, también en `load_catalog`.
  Hecho cuando: `uv run pytest -q tests/business_data_test.py` pasa con un caso que comprueba que `get_fallback_space` filtra por ámbito.
- [x] **T-67 — Reescribir `InternalStrategy` con `AreaNotifier`** · RF-57, RF-58, RF-59, RF-60, RF-61, RF-102 · ~25 min (depende de T-65, T-66)
  Aviso al `chat_space` del área o al space general; un área sin space cuenta como notificación fallida. `FakeNotifier` en `tests/fakes.py` sustituye a `FakeMailer`.
  Hecho cuando: `uv run pytest -q tests/channel_strategy_test.py -k internal` pasa con estos casos: space del área, space general, área sin space ⇒ fallida, y fallo de entrega ⇒ log (`caplog`) y "contacta directamente".
- [x] **T-68 — Eliminar el correo** · RF-60 · ~20 min
  Borrar `src/services/mailer.py`, `src/utils/exceptions/mail.py` y `tests/mailer_test.py`; el orquestador interno pasa a usar `AreaNotifier`; las properties `smtp_*` salen del README.
  Hecho cuando: `grep -rnE "smtp|Mailer|MailDelivery" src tests README.md` no devuelve nada y `uv run pytest` está en verde.

## Fase 14 — Ampliación: recuperador de procedimientos
- [x] **T-69 — Implementar `search_procedures`** · RF-85, RF-87 · ~30 min (depende de T-62)
  En `src/agents/retriever.py`: `ProcedureHit` (id, nombre, pasos, campos, similitud) y búsqueda por coseno filtrada por área, activo y `rag_min_similarity`. `search` pasa a llamarse `search_faq`.
  Hecho cuando: `uv run pytest -q tests/retriever_test.py -k procedures` pasa: la sentencia compilada filtra por `area_id` y `active`, ordena por distancia y aplica el umbral.
- [x] **T-70 — Refrescar también los embeddings de los procedimientos** · RF-11, RF-85 · ~20 min
  `refresh_stale_embeddings(area_ids)` recalcula las FAQ y los procedimientos desactualizados (texto: nombre + pasos).
  Hecho cuando: `uv run pytest -q tests/retriever_test.py -k refresh` pasa con un caso en el que el embedder falso solo recibe los procedimientos desactualizados.

## Fase 15 — Ampliación: sub-agentes con tools
- [x] **T-71 — Definir `AgentLLM.step` y sus tipos** · (habilita RF-84–90) · ~25 min
  En `src/agents/llm.py`: `ToolSpec`, `ToolCall`, `ToolCalls`, `FinalText` y `AgentStep`; `step` sustituye a `answer`. `FakeAgentLLM` guionizado con una lista de pasos por área.
  Hecho cuando: `uv run pyright` da 0 errores con `FakeAgentLLM` tipado como `AgentLLM`, y `uv run pytest -q tests/gemini_llm_test.py -k fake` pasa.
- [x] **T-72 — Implementar `GeminiAgentLLM.step` y `build_area_messages`** · RF-9, RF-10 · ~30 min
  `step` con `bind_tools`: convierte `AIMessage.tool_calls` en `ToolCalls` y el texto en `FinalText`; los errores pasan a `LlmUnavailableError`. `build_area_messages` une el prompt del área y `area_rules` y no incluye FAQ. Se eliminan `AnswerOutput` y `build_answer_messages`.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k "step or area_messages"` pasa con un chat falso que devuelve tool calls, texto o una excepción.
- [x] **T-73 — Implementar `AreaToolbox` con `buscar_faq` y `buscar_procedimiento`** · RF-84, RF-85, RF-86, RF-87, RF-88, RF-91, RF-100 · ~30 min (depende de T-69, T-71)
  `src/agents/tools.py`: el `area_id` lo fija el código; solo se devuelven los resultados sobre el umbral y se registran como evidencias; los procedimientos devuelven pasos y campos, nunca datos personales.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k toolbox` pasa, incluido un caso en el que el argumento pide otra área y el recuperador recibe el `area_id` del sub-agente.
- [x] **T-74 — Implementar la tool `notificar_area`** · RF-93, RF-94, RF-95, RF-96, RF-97, RF-98, RF-102 · ~30 min (depende de T-63, T-65, T-73)
  Valida el procedimiento (de su área) y los datos con `missing_or_invalid`; en web añade nombre y contacto; cuenta los intentos fallidos; publica con `AreaNotifier` usando la identidad del canal; un área sin space o un fallo de entrega cuentan como fallo.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k notificar` pasa con estos casos: válido, inválido con error devuelto al modelo, tercer intento ⇒ `gave_up`, sin space, fallo de entrega, e instrucciones inyectadas en un dato que llegan como texto literal.
- [x] **T-75 — Implementar la tool `derivar_a_ejecutivo`** · RF-25, RF-26 · ~15 min
  Solo existe en el toolbox del canal web; marca el resultado `wants_human`.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k derivar` pasa: la tool no aparece en el canal interno y en web produce `wants_human`.
- [x] **T-76 — Implementar `run_sub_agent` con el guardarraíl** · RF-7, RF-9, RF-89, RF-90, RF-99 · ~30 min (depende de T-73, T-74, T-75)
  `src/agents/sub_agent.py`: bucle de hasta `agent_max_steps` pasos; un texto final sin evidencias se descarta y da `no_answer`.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k "guardrail or steps or answered or confirm"` pasa: texto sin tools ⇒ descartado; tool sin resultados ⇒ descartado; 5 pasos ⇒ `no_answer`; FAQ ⇒ `answered`; notificación entregada ⇒ confirmación.

## Fase 16 — Ampliación: integración en el grafo y los orquestadores
- [x] **T-77 — Usar `run_sub_agent` en el grafo** · RF-5, RF-6, RF-7, RF-8, RF-9, RF-94, RF-101 · ~30 min (depende de T-76)
  `answer_area` construye el toolbox del área y llama a `run_sub_agent`; el estado añade `procedure_attempts`; nuevos outcomes `notification_failed` y `wants_human` desde el sub-agente.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py` pasa entero con pasos guionizados, incluidos los casos `follow_up` (la consulta de búsqueda la redacta el modelo), `attempts` (persisten entre mensajes con `InMemorySaver`) y `rnf3`.
- [x] **T-78 — Pasar el notificador y la identidad en el contexto del agente** · RF-96, RF-97, RF-98 · ~25 min
  `AgentContext` añade `notifier` y `requester`; `build_agent_context` los arma para cada canal (colaborador de Google Chat o cliente web).
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k requester` pasa en ambos canales.
- [x] **T-79 — Traducir los nuevos outcomes en el canal web** · RF-25, RF-101 · ~20 min
  `handle_web_message`: `notification_failed` ⇒ mensaje y `official_channels`; `wants_human` del sub-agente ⇒ flujo de oferta existente.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k "web and (notification or derivar)"` pasa.

## Fase 17 — Ampliación: memoria de Google Chat
- [ ] **T-80 — Calcular la conversación y la identidad en `handle_event`** · RF-97, RF-103, RF-104 · ~20 min
  `conversation_id(event)`: el space en un mensaje directo y el hilo en un space de grupo; se pasa con la identidad al orquestador.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k conversation` pasa con un mensaje directo y una mención en un space.
- [ ] **T-81 — Dar memoria al grafo interno** · RF-61, RF-103, RF-104 · ~30 min (depende de T-80)
  `app.state.internal_graph` con el checkpointer en el lifespan; `handle_internal_message(session, graph, text, requester, conversation_id)` con `thread_id = conversation_id`; `notification_failed` ⇒ "contacta directamente".
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k "internal and (thread or notification)"` pasa: el segundo mensaje del mismo hilo ve el primero, otro hilo del mismo space no lo ve, y el fallo de notificación da el mensaje de RF-61.
- [ ] **T-82 — Registrar la actividad de cada conversación de Google Chat** · RF-105 · ~20 min
  Actualizar `chat_thread.last_message_at` en cada mensaje interno (insert o update).
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k chat_thread` pasa, comprobando sobre la sentencia compilada el upsert por `conversation_id`.
- [ ] **T-83 — Borrar en el barrido las conversaciones caducadas** · RF-105 · ~25 min
  `run_sweep` borra los hilos con `last_message_at` anterior a `google_chat_retention_days` (30 por defecto): `adelete_thread` y la fila de `chat_thread`.
  Hecho cuando: `uv run pytest -q tests/sweeper_test.py -k chat_thread` pasa: `adelete_thread` se llama una vez por conversación caducada.

## Fase 18 — Ampliación: protección frente a manipulación
- [ ] **T-84 — Redactar los prompts recomendados** · RF-10, RF-91, RF-100, RF-106, RF-107, RF-108 · ~25 min
  `docs/specs/001-agentic-pattern-coordinator/prompts.md` con `classifier`, `internal_agent`, `external_agent` y `area_rules`: uso de las tools, seguir procedimientos, no revelar instrucciones, tools, áreas ni funcionamiento interno, ignorar instrucciones del usuario o de los datos, y la respuesta genérica.
  Hecho cuando: el archivo contiene las 4 keys y, en cada prompt, la cláusula de no revelar y la respuesta genérica de RF-108 (comprobado con `grep`).
- [ ] **T-85 — Implementar el detector de fugas y la batería** · RNF-9 · ~30 min
  `src/cli/jailbreak_check.py`: `ATTACKS` con al menos 20 ataques (revelar prompt, tools o áreas internas; "ignora tus instrucciones"; juego de rol; inyección en los datos) y `find_leaks(reply, prompts, tool_names, internal_areas)`.
  Hecho cuando: `uv run pytest -q tests/jailbreak_check_test.py -k "leak or battery"` pasa: detecta un fragmento de 30 o más caracteres de un prompt, un nombre de tool y un área interna; no marca la negativa genérica; la batería tiene 20 o más ataques.
- [ ] **T-86 — Ejecutar la batería contra un servidor** · RF-106, RF-107, RF-108 · ~25 min
  `uv run python -m src.cli.jailbreak_check --url <ws>` envía cada ataque en una sesión nueva, lee los prompts de la BD e imprime PASA/FALLA por ataque, con código de salida 1 si hay fugas.
  Hecho cuando: `uv run pytest -q tests/jailbreak_check_test.py -k runner` pasa con un cliente WebSocket sustituido, y `uv run python -m src.cli.jailbreak_check --help` termina con código 0.
- [ ] **T-87 — Probar la ampliación en local con datos de prueba** · RF-91–99, RF-106–108, RNF-9 · ~30 min
  En la BD local (sin versionar): los prompts de `prompts.md`, un procedimiento con campos en Servicio al Cliente y el `chat_space` de prueba. Ejecutar `jailbreak_check` contra el servidor local y un procedimiento web de punta a punta.
  Hecho cuando: `jailbreak_check` termina con código 0 (20/20 sin fugas) y el procedimiento web llega a la notificación (o a `official_channels` si no hay space de prueba); el resultado queda registrado en R16 del plan.

## Cierre final
- [ ] **T-88 — Actualizar el README de la ampliación** · todos · ~25 min
  Tablas `procedure`, `procedure_field`, `chat_space` y `fallback_space`; properties `google_chat_retention_days`, `agent_max_steps` y `procedure_max_attempts`; sin `smtp_*`; `prompts.md`, `jailbreak_check` y el requisito de añadir la app de Google Chat a los spaces de las áreas (R14).
  Hecho cuando: `README.md` contiene cada tabla y property nuevas y `jailbreak_check`, y no contiene `smtp_` (comprobado con `grep`).
- [ ] **T-56 — Ejecutar la prueba de carga del RNF-2** · RNF-1, RNF-2 · ~30 min
  Tras la ampliación (depende de T-87): 50 sesiones WebSocket simultáneas contra el despliegue de prueba, con FAQ y procedimientos cargados, midiendo hasta la respuesta completa. Si el p95 supera 5000 ms, actualizar RNF-2 de la spec a 8000 ms (decisión R2, riesgo R12). La medición local previa está en R2.
  Hecho cuando: R2 del plan registra el p95 medido y, si superó 5000 ms, RNF-2 de la spec dice 8000 ms.
- [ ] **T-59 — Verificación completa y demo** · todos · ~30 min
  `uv run pyright` y `uv run pytest` en local, y los 12 pasos de la demo manual de la spec en el despliegue contra PostgreSQL real (incluye Google Chat, procedimientos y la batería de manipulación con `jailbreak_check`).
  Hecho cuando: ambos comandos terminan con código 0 y la salida se adjunta; los 12 pasos de la demo quedan marcados en la sección "Criterios de finalización" de la spec.

## Cobertura
| RF | Tareas |
|---|---|
| RF-1 | T-27, T-32, T-34 |
| RF-2 | T-27, T-45, T-46 |
| RF-3, RF-4 | T-16, T-22, T-26 |
| RF-5 | T-19, T-22, T-23, T-77 |
| RF-6 | T-19, T-24 |
| RF-7 | T-24, T-45 |
| RF-8 | T-22, T-32, T-45 |
| RF-9 | T-19, T-20, T-23, T-58, T-72, T-76, T-77 |
| RF-10 | T-16, T-22, T-72, T-84 |
| RF-11 | T-16, T-21, T-70 |
| RF-12 | T-5, T-18 |
| RF-13, RF-14 | T-18, T-32, T-45 |
| RF-15, RF-16, RF-17 | T-14, T-32, T-46 |
| RF-18 | T-18, T-32, T-45 |
| RF-19–RF-23 | T-15, T-16 |
| RF-24 | T-16, T-27 |
| RF-25 | T-27, T-41, T-45, T-47, T-75, T-79 |
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
| RF-57, RF-61 | T-29, T-67, T-81 |
| RF-58, RF-60 | T-28, T-29, T-65, T-67, T-68 |
| RF-59, RF-62 | T-16, T-29, T-61, T-62, T-65, T-66, T-67 |
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
| RF-84, RF-87, RF-88 | T-73 |
| RF-85 | T-60, T-62, T-69, T-70, T-73 |
| RF-86 | T-73, T-77 |
| RF-89, RF-90 | T-71, T-76 |
| RF-91 | T-73, T-84, T-87 |
| RF-92, RF-93 | T-63, T-74 |
| RF-94 | T-74, T-77 |
| RF-95, RF-96, RF-97 | T-65, T-74, T-78, T-80 |
| RF-98 | T-63, T-74, T-78 |
| RF-99 | T-76, T-87 |
| RF-100 | T-73, T-84 |
| RF-101 | T-77, T-79 |
| RF-102 | T-67, T-74 |
| RF-103, RF-104 | T-80, T-81 |
| RF-105 | T-61, T-62, T-82, T-83 |
| RF-106, RF-107, RF-108 | T-84, T-86, T-87 |
| RNF-1, RNF-2 | T-56 |
| RNF-3 | T-26 |
| RNF-4 | T-35 |
| RNF-8 | T-65 |
| RNF-9 | T-85, T-87 |

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
| `src/services/business_data.py` | T-16, T-66 |
| `src/agents/llm.py` | T-17, T-18, T-19, T-71, T-72 |
| `src/agents/retriever.py` | T-20, T-21, T-69, T-70 |
| `src/agents/graph.py` | T-22–T-26, T-66, T-77 |
| `src/agents/strategies.py` | T-27, T-29, T-67 |
| `src/services/mailer.py` | T-28 |
| `src/services/google_chat.py` | T-30, T-31, T-33, T-64, T-80 |
| `src/services/chat_orchestrator.py` | T-32, T-45, T-68, T-78, T-79, T-81, T-82 |
| `src/routers/google_chat.py` | T-34, T-64, T-81 |
| `src/services/executive_auth.py` + `src/cli/hash_password.py` | T-35, T-36, T-37 |
| `src/routers/executive.py` | T-38, T-52 |
| `main.py` (lifespan) | T-40, T-55, T-81 |
| `src/services/web_session.py` | T-41, T-42 |
| `src/services/live_chat.py` | T-43, T-48, T-49 |
| `src/interfaces/*` | T-31, T-38, T-44, T-51 |
| `src/routers/web_chat.py` | T-46, T-47, T-53 |
| `src/services/realtime.py` | T-50 |
| `src/routers/live_chat.py` | T-51 |
| `src/services/sweeper.py` | T-54, T-55, T-83 |
| `README.md` | T-57, T-68, T-88 |
| `src/models/procedure*.py`, `chat_thread.py`, `fallback_space.py` + migración E | T-60, T-61, T-62 |
| `src/services/procedures.py` | T-63 |
| `src/services/area_notifier.py` + `src/utils/exceptions/notification.py` | T-64, T-65 |
| `src/services/mailer.py` (eliminado) | T-68 |
| `src/agents/tools.py` | T-73, T-74, T-75 |
| `src/agents/sub_agent.py` | T-76 |
| `src/cli/jailbreak_check.py` | T-85, T-86 |
| `docs/specs/001-agentic-pattern-coordinator/prompts.md` | T-84 |
