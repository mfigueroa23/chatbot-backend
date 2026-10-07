# Plan 001 — Asistente virtual con patrón agéntico coordinador

**Spec:** `docs/specs/001-agentic-pattern-coordinator/spec.md` · **Estado:** fases 0–19 implementadas; rediseño de una sola llamada y Google Chat como complemento en borrador (2026-10-07)
Se reutilizan la capa router → service → model, `SessionDep`, `get_property`, las excepciones
de `src/utils/exceptions/`, el advisory lock de `alembic/env.py` y el patrón de tests con `dependency_overrides`. Se
añaden una capa de agentes (`src/agents/`), comunicación en tiempo real (WebSocket + LISTEN/NOTIFY de PostgreSQL) y
un barrido periódico de tareas temporales.

## 1. Resumen
> **Rediseño del 2026-10-07 (una sola llamada):** por latencia (R12: p95 de 8,69 s con tools) el usuario pidió una sola
> llamada de generación por mensaje (RNF-10). Las FAQ y los procedimientos del canal se recuperan antes de llamar al
> modelo; una única llamada con salida estructurada devuelve el tipo de respuesta, el texto, las FAQ usadas y, si aplica,
> el procedimiento con sus datos; el código aplica el guardarraíl, valida y notifica con plantillas y pasa un auditor
> determinista de fugas (RF-109). Se eliminan el clasificador como llamada aparte, los sub-agentes con tools y el bucle
> de tools. Además, Google Chat pasa a la modalidad de complemento de Google Workspace, que es como está creada la app.
> Las secciones marcadas «Rediseño» describen este cambio y sustituyen a lo que contradigan de la Ampliación.

> **Ampliación del 2026-10-07** (spec ampliada con RF-84 a RF-108): los sub-agentes pasan a ser agentes con tools
> (`buscar_faq`, `buscar_procedimiento`, `notificar_area` y, en el canal web, `derivar_a_ejecutivo`) con un guardarraíl
> en código; se añaden los procedimientos; el aviso al área pasa del correo al space de Google Chat del área; el canal
> interno gana memoria por conversación; y la protección frente a manipulación vive en los prompts de la BD. Se reutiliza
> todo lo implementado (coordinador, clasificador, RAG, estrategias, checkpointer, routers, chat en vivo y barrido) y se
> reescriben el nodo de sub-agente y el aviso interno. Las secciones marcadas «Ampliación» describen ese cambio.

- **Agentes (RF-1–18):** un grafo LangGraph por ámbito (interno/externo). Un nodo clasificador elige las áreas, un sub-agente por área responde solo con las FAQ recuperadas por RAG (pgvector + embeddings de Gemini) y un nodo combina las respuestas. La estrategia del canal (patrón strategy) decide qué hacer cuando no hay respuesta.
- **Horario (RF-19–24):** función pura sobre las tablas de horario y festivos, evaluada en America/Santiago.
- **Canal web (RF-25–38, RF-76–83):** WebSocket del cliente con protocolo tipado. Una máquina de estados de la sesión (bot → oferta → datos de contacto → en cola → en vivo) y la memoria de la conversación en el checkpointer de PostgreSQL.
- **Chat en vivo (RF-39–56):** WebSocket del ejecutivo. Mensajes persistidos y repartidos entre pods con LISTEN/NOTIFY. Asignación atómica en SQL.
- **Canal interno (RF-57–69):** endpoint HTTP de Google Chat con verificación del token, respuesta síncrona o asíncrona según el límite de 30 s, y aviso al space de Google Chat del área (antes correo por SMTP; ver Ampliación).
- **Ampliación — sub-agentes con tools (RF-84–90), procedimientos (RF-91–102), memoria de Google Chat (RF-103–105) y protección frente a manipulación (RF-106–108):** ver las secciones «Ampliación» de este plan.
- **Ejecutivos (RF-70–75):** login con Argon2, sesión con JWT revocable (D13) y bloqueo por intentos fallidos.
- **Barrido periódico:** fin de horario, plazo de 1 hora, sesiones caducadas y conexiones muertas.

## 2. Módulos

### Transversal
| Módulo | Cambio | RF |
|---|---|---|
| `pyproject.toml` / `uv.lock` | Añade `langgraph`, `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`, `langchain-google-genai`, `pgvector`, `google-auth` y `argon2-cffi` | — |
| `src/utils/clock.py` | `Clock` (Protocol) con `now() -> datetime` (UTC aware); `SystemClock`. Se inyecta en todo lo que depende del tiempo | RF-34–56, RF-70–79 |
| `src/services/property.py` | Añade helpers tipados `get_int_property`, `get_float_property` y `get_str_property(session, key, default)`. `get_property` no cambia | RF-12, RF-41, RF-70, RF-72, RF-79, RF-81 |
| `src/utils/exceptions/*.py` | Nuevas excepciones: `agent.py` (`LlmNotConfiguredError`, `LlmUnavailableError`), `auth.py` (`InvalidCredentialsError`, `AccountLockedError`, `InvalidSessionError`), `live_chat.py` (`ChatNotFoundError`, `ChatAlreadyAssignedError`, `ExecutiveChatLimitError`), `google_chat.py` (`InvalidGoogleTokenError`), `mail.py` (`MailDeliveryError`) | RF-13, RF-18, RF-40, RF-41, RF-60, RF-63, RF-71–75 |
| `main.py` | En el lifespan: abre el pool de psycopg y el checkpointer, arranca el listener de `NOTIFY` y el barrido periódico, y cierra todo al apagar. Registra los routers nuevos | — |
| `src/cli/hash_password.py` | Comando que pide la contraseña con `getpass` e imprime el hash Argon2 con los mismos parámetros que `executive_auth` | RF-70 (habilita), RNF-4 |
| `alembic/env.py` | Importa los modelos nuevos; `include_object` ignora las tablas `checkpoint*` para que autogenerate no las borre | — |

### Agentes (`src/agents/`)
| Módulo | Cambio | RF |
|---|---|---|
| `src/agents/llm.py` | *(Ampliación: `answer` se sustituye por `step`, ver abajo.)* `AgentLLM` (Protocol tipado): `classify(question, areas) -> Classification`, `answer(area, question, faqs, history) -> AreaAnswer`, `combine(parts) -> str`. `GeminiAgentLLM` lo implementa con `ChatGoogleGenerativeAI` y salida estructurada; lee `gemini_model` y `gemini_api_key` y lanza `LlmNotConfiguredError` si faltan. Los errores y timeouts de Gemini se convierten en `LlmUnavailableError` | RF-5, RF-6, RF-9, RF-12–14, RF-18 |
| `src/agents/retriever.py` | `FaqRetriever.search(area_id, question, k) -> list[FaqHit]`: calcula el embedding de la consulta (`gemini-embedding-001`, 768 dimensiones, `RETRIEVAL_QUERY`) y busca por distancia coseno filtrando por área y por `rag_min_similarity`. `refresh_stale_embeddings(area_ids)` recalcula las FAQ cuyo `content_hash` ≠ `embedded_hash` antes de buscar | RF-9, RF-11 |
| `src/agents/graph.py` | `build_graph(scope, llm, retriever, checkpointer)`. Estado: `messages`, `scope`, `candidate_areas`, `classification`, `area_answers`, `outcome`. Nodos: `load_context` (lee áreas y prompts del ámbito desde la BD en cada mensaje), `classify`, `answer_area` (fan-out con `Send`, uno por área), `combine`. `outcome` ∈ `answered` / `partial` / `no_answer` / `mixed_scope` / `wants_human` | RF-1–11 |
| `src/agents/strategies.py` | `ChannelStrategy` (Protocol): `scope`, `prompt_key` y `async on_no_answer(ctx) -> ChannelReply`. Implementaciones `ExternalStrategy` (horario → oferta de humano o canales oficiales) e `InternalStrategy` (*Ampliación:* aviso al space del área o al space general; antes correo) | RF-1, RF-2, RF-25, RF-32, RF-57–61 |

### Servicios
| Módulo | Cambio | RF |
|---|---|---|
| `src/services/message_validation.py` | `validate_user_message(text) -> str`: recorta espacios exteriores y lanza `EmptyMessageError` o `MessageTooLongError` (> 5000) | RF-15–17 |
| `src/services/schedule.py` | `is_open(now, slots, holidays) -> bool` (pura; franja `[opens_at, closes_at)` en America/Santiago) y `load_schedule(session)` | RF-19–24 |
| `src/services/business_data.py` | Lectores sin caché: `get_areas(session, scope)`, `get_agent_prompt(session, key)`, `get_official_channels(session)`, `get_fallback_email(session, scope)` | RF-10, RF-11, RF-24, RF-44, RF-59, RF-62 |
| `src/services/mailer.py` | *(Ampliación: se elimina, lo sustituye `area_notifier.py`.)* `Mailer.send(to, subject, body)` con `smtplib` en `asyncio.to_thread` y properties `smtp_*`; lanza `MailDeliveryError` | RF-58–61 |
| `src/services/google_chat.py` | `verify_chat_token(authorization)` (certificados de `chat@system.gserviceaccount.com` cacheados según `Cache-Control`, `google.auth.jwt.decode` con audiencia `google_chat_audience`); `handle_event(event)`; `ChatApiClient.create_message(space, thread, text)` (token OAuth de la cuenta de servicio vía JWT-bearer, firmado con `google.auth.crypt`, por httpx) | RF-63–69 |
| `src/services/executive_auth.py` | `login(username, password) -> SessionToken` (JWT), `authenticate(token) -> Executive`, `logout(token)`. Argon2 con comparación de tiempo constante, hash ficticio para usuarios inexistentes, contador de fallos y `locked_until` | RF-70–75 |
| `src/services/web_session.py` | Máquina de estados de la sesión web (`phase`: `bot`, `offering_human`, `collecting_contact`, `queued`, `live`). `admit(session_id)` aplica el límite de 50 bajo un advisory lock de transacción. Incluye heartbeat y `touch_last_message` | RF-25–33, RF-76–81 |
| `src/services/live_chat.py` | `enqueue`, `list_waiting`, `take(chat_id, executive_id)` (UPDATE … WHERE status='waiting' RETURNING, más el conteo de chats del ejecutivo con su fila bloqueada `FOR UPDATE`), `post_message`, `close`, `mark_executive_disconnected`, `resume`, `customer_disconnected` | RF-34–56 |
| `src/services/realtime.py` | `ConnectionHub` por pod: registro de los WebSocket de clientes y ejecutivos, y `publish(event)` → `pg_notify('chatbot_events', json)` con identificadores (nunca contenido). Listener asyncpg que reenvía cada evento al socket local que corresponda | RF-30, RF-31, RF-37, RF-43–56 |
| `src/services/sweeper.py` | `run_sweep(now)` cada 30 s, solo en el pod que obtiene `pg_try_advisory_lock`. Hace cinco cosas: cierra los chats en espera cuando termina el horario; cierra los chats asignados con el ejecutivo desconectado más de 60 min; marca como desconectados las sesiones y los ejecutivos sin heartbeat desde hace 90 s; borra las sesiones web caducadas y su hilo del checkpointer (`adelete_thread`) | RF-35–38, RF-47–53, RF-79, RF-81 |
| `src/services/chat_orchestrator.py` | Une el grafo, la estrategia y la máquina de estados: `handle_web_message(session_id, text)` y `handle_internal_message(event)`. Traduce `LlmNotConfiguredError`, `LlmUnavailableError` y `DatabaseUnavailableError` en mensajes de servicio no disponible | RF-1, RF-2, RF-7, RF-8, RF-13, RF-18, RF-26, RF-82, RF-83 |

### Ampliación con tools (2026-10-07)
| Módulo | Cambio | RF |
|---|---|---|
| `src/agents/llm.py` | `AgentLLM.answer` se sustituye por `step(messages, tools: list[ToolSpec]) -> AgentStep`, donde `AgentStep` es `ToolCalls(list[ToolCall])` o `FinalText(str)`. `GeminiAgentLLM.step` usa `bind_tools` y convierte `AIMessage.tool_calls`. `build_area_messages(area, rules, question, history)` arma el system prompt del área + `area_rules` (sin FAQ: las trae la tool). `classify` y `combine` no cambian. Se eliminan `AnswerOutput` y `build_answer_messages` | RF-5, RF-9, RF-84–90, RF-106, RF-107 |
| `src/agents/tools.py` (nuevo) | `ToolSpec` (nombre, descripción, esquema de argumentos) y `AreaToolbox(area, scope, retriever, notifier, requester)`: ejecuta `buscar_faq(consulta)`, `buscar_procedimiento(consulta)`, `notificar_area(procedimiento_id, datos)` y, solo en web, `derivar_a_ejecutivo()`. El `area_id` lo fija el código, nunca el modelo. Registra las **evidencias** (FAQ o procedimientos sobre el umbral devueltos y notificaciones entregadas) | RF-84–88, RF-95–102 |
| `src/agents/sub_agent.py` (nuevo) | `run_sub_agent(llm, toolbox, messages, max_steps=4) -> SubAgentResult` con `kind` ∈ `answered`, `no_answer`, `wants_human`, `notification_failed`, `gave_up`. Bucle llamar al modelo → ejecutar tools → devolver resultados. **Guardarraíl:** un texto final sin evidencias se descarta (`no_answer`) | RF-7, RF-9, RF-89, RF-90, RF-94 |
| `src/agents/graph.py` | `answer_area` llama a `run_sub_agent` en lugar de buscar FAQ y llamar a `llm.answer`. El estado añade `procedure_attempts: dict[int, int]` (persistido por el checkpointer). Nuevos outcomes `notification_failed` y `wants_human` desde el sub-agente. `AreaInfo.owner_email` pasa a `chat_space` | RF-5–9, RF-89–94, RF-101 |
| `src/agents/retriever.py` | Se generaliza: `search_faq(area_id, query)`, `search_procedures(area_id, query) -> list[ProcedureHit]` (id, nombre, pasos, campos, similitud) y `refresh_stale_embeddings` para ambas tablas | RF-84, RF-85, RF-87 |
| `src/agents/strategies.py` | `InternalStrategy(session, notifier)`: aviso al `chat_space` de las áreas o al space general; sin space ⇒ notificación fallida. `MailSender` se sustituye por `AreaNotifier` | RF-57–62, RF-102 |
| `src/services/procedures.py` (nuevo) | `validate_field(kind, value) -> str \| None` (texto no vacío, correo, teléfono, RUT con dígito verificador, número, fecha `dd-mm-aaaa`), `missing_or_invalid(fields, datos)` y `web_contact_fields()` (nombre + correo o teléfono, RF-98) | RF-92, RF-93, RF-98 |
| `src/services/area_notifier.py` (nuevo) | `AreaNotifier.notify(space, text)` sobre `ChatApiClient.create_message(space, text)` sin hilo; lanza `NotificationDeliveryError`. `format_request(procedure, datos, requester)` y `format_unanswered(question, requester)`. No registra datos en el log | RF-58, RF-59, RF-95–97, RNF-8 |
| `src/services/google_chat.py` | `ChatApiClient.create_message(space, text, thread=None)`. `conversation_id(event)`: en un mensaje directo es el space, en un space de grupo es el hilo. `handle_event` pasa la identidad y el `conversation_id` al orquestador | RF-97, RF-103, RF-104 |
| `src/services/chat_orchestrator.py` | `handle_internal_message(session, graph, text, requester, conversation_id)` con el grafo interno con checkpointer (desde `app.state`) y `thread_id = conversation_id`; registra el hilo en `chat_thread`. Ambos canales traducen `notification_failed` (web ⇒ canales oficiales; interno ⇒ contactar con el área) y `wants_human` | RF-61, RF-101, RF-103–105 |
| `src/services/business_data.py` | `get_fallback_space(session, scope)` sustituye a `get_fallback_email`; `get_procedure(session, area_id, procedure_id)` con sus campos | RF-59, RF-62, RF-95 |
| `src/services/sweeper.py` | Borra los hilos de Google Chat caducados según `google_chat_retention_days`: `adelete_thread` y la fila de `chat_thread` | RF-105 |
| `src/services/mailer.py`, `src/utils/exceptions/mail.py` | Se eliminan; `NotificationDeliveryError` en `src/utils/exceptions/notification.py` | RF-60 |
| `main.py` | El lifespan crea también `app.state.internal_graph` con el checkpointer | RF-103 |
| `src/routers/google_chat.py` | Usa `app.state.internal_graph` y la publicación diferida pasa el hilo de forma explícita | RF-69, RF-103 |
| `src/cli/jailbreak_check.py` (nuevo) | Ejecuta contra un servidor (`--url`) una batería de al menos 20 ataques por WebSocket y marca como fallo cualquier respuesta que contenga fragmentos de los prompts de la BD, nombres de tools o nombres de áreas internas | RF-106–108, RNF-9 |

### Rediseño: una sola llamada y Google Chat como complemento (2026-10-07)
| Módulo | Cambio | RF |
|---|---|---|
| `src/agents/llm.py` | `AgentLLM` queda con un solo método: `respond(messages) -> AgentReply`. `AgentReply` (dataclass) y `ReplyOutput` (Pydantic, salida estructurada): `kind` ∈ `answer`, `no_answer`, `wants_human`, `manipulation`, `procedure`; `text`; `faq_ids`; `procedure_id`; `data` (pares campo/valor). `GeminiAgentLLM.respond` con `with_structured_output`, `temperature=0` y `thinking_budget=0`. `build_reply_messages(agent_prompt, rules, sections, pending, history, question)`. Se eliminan `classify`, `step`, `combine`, `ToolSpec`, `ToolCall(s)`, `FinalText`, `ClassificationOutput` y sus `build_*` | RF-5–10, RF-89, RF-106–108, RNF-10 |
| `src/agents/retriever.py` | `search_scope(scope, query) -> Knowledge`: un embedding y dos búsquedas (FAQ y procedimientos de todas las áreas activas del ámbito, con su `area_id`), más la mejor similitud del otro ámbito (sin su contenido) para detectar preguntas mixtas | RF-8, RF-84–88 |
| `src/agents/audit.py` (nuevo) | `find_leaks(text, prompts, internal_names)` (se mueve desde `jailbreak_check`, más detección de código) y `sanitize(text, …) -> str` que sustituye por la negativa genérica | RF-109, RNF-9 |
| `src/agents/procedure_flow.py` (nuevo; sustituye a `tools.py`) | `handle_procedure(procedure, data, requester, message, attempts, notifier)`: valida con `missing_or_invalid`, cuenta intentos, notifica y devuelve el resultado con el texto de plantilla (faltan datos, inválidos, enviada, fallida) | RF-91–102 |
| `src/agents/graph.py` | Nodos `load_context` → `retrieve` → `respond` (la única llamada) → `finalize` (determinista: preguntas mixtas por similitud, guardarraíl, procedimiento, auditor). Estado con `pending_procedure_id` y `procedure_attempts`. `AgentContext` sin `max_steps`; añade `history_messages` | RF-5–9, RF-89–94, RF-103, RF-109, RNF-10 |
| `src/agents/tools.py`, `src/agents/sub_agent.py` | Se eliminan | — |
| `src/services/chat_orchestrator.py` | Sin cambios de flujo: traduce los mismos outcomes (`rejected`, `mixed_scope`, `notification_failed`, `wants_human`, `no_answer`, `answered`); el texto del procedimiento llega en `reply` | RF-25, RF-101, RF-108 |
| `src/services/google_chat.py` | `verify_addon_token(token, audience, service_account, http)`: ID token de Google (certificados de `https://www.googleapis.com/oauth2/v1/certs` cacheados según `Cache-Control`), emisor `accounts.google.com`, audiencia `google_chat_audience`, `email` = `google_chat_addon_service_account` y `email_verified`. `handle_event` lee `chat.messagePayload`, `chat.addedToSpacePayload` y `chat.user` | RF-63–67, RF-103 |
| `src/interfaces/google_chat.py` | `AddonEvent` (`chat.user`, `chat.messagePayload.message`, `chat.messagePayload.space`, `chat.addedToSpacePayload.space`) y `chat_reply(text)` → `{"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": …}}}}}`; sin respuesta ⇒ `{}` | RF-65–68 |
| `src/routers/google_chat.py` | Usa `AddonEvent`, `verify_addon_token` y `chat_reply`; la publicación diferida por la API de Chat no cambia | RF-63, RF-68, RF-69 |
| `src/cli/jailbreak_check.py` | Usa `audit.find_leaks` | RNF-9 |

### Routers e interfaces
| Módulo | Cambio | RF |
|---|---|---|
| `src/routers/web_chat.py` | `WS /ws/v1/chat` | RF-2, RF-15–17, RF-25–38, RF-43–56, RF-76–83 |
| `src/routers/executive.py` | `POST /api/v1/executives/login`, `POST /api/v1/executives/logout`, `WS /ws/v1/executive` | RF-39–56, RF-70–75 |
| `src/routers/live_chat.py` | `GET /api/v1/live-chats`, `POST /api/v1/live-chats/{id}/take`, `POST /api/v1/live-chats/{id}/close` | RF-39–42, RF-55, RF-56, RF-74, RF-75 |
| `src/routers/google_chat.py` | `POST /api/v1/google-chat/events` | RF-1, RF-57–69 |
| `src/interfaces/web_chat.py`, `executive.py`, `live_chat.py`, `google_chat.py` | Modelos Pydantic de los mensajes WS (unión discriminada por `type`), de las peticiones y respuestas HTTP y del evento de Google Chat (solo los campos usados) | todos los de contrato |

## 3. Modelo de datos
Todas las tablas son nuevas y la tabla `property` no cambia. No hay filas existentes que migrar: las tablas de negocio
empiezan vacías y el responsable de contenidos las carga por SQL. El README documentará qué tablas hay que cargar.

**Migración A — `create business tables` (`CREATE EXTENSION IF NOT EXISTS vector`):**
| Tabla | Columnas | Índices |
|---|---|---|
| `business_area` | `id` int PK; `name` varchar(120) NOT NULL; `description` text NOT NULL; `scope` enum `area_scope`(`internal`,`external`) NOT NULL; `system_prompt` text NULL; `owner_email` varchar(320) NULL; `active` bool NOT NULL default true | único (`scope`, `name`) |
| `faq_category` | `id` PK; `area_id` FK → business_area ON DELETE CASCADE NOT NULL; `name` varchar(120) NOT NULL | (`area_id`) |
| `faq` | `id` PK; `category_id` FK → faq_category ON DELETE CASCADE NOT NULL; `question` text NOT NULL; `answer` text NOT NULL; `active` bool NOT NULL default true; `content_hash` text GENERATED ALWAYS AS (md5(question ‖ E'\n' ‖ answer)) STORED; `embedded_hash` text NULL; `embedding` vector(768) NULL | HNSW (`embedding vector_cosine_ops`); (`category_id`) |
| `agent_prompt` | `key` varchar(60) PK (`internal_agent`, `external_agent`, `classifier`, `area_rules`); `content` text NOT NULL | — |
| `service_schedule` | `weekday` smallint PK (0 = lunes … 6 = domingo, CHECK 0–6); `opens_at` time NOT NULL; `closes_at` time NOT NULL; CHECK `opens_at < closes_at` | — |
| `holiday` | `date` date PK; `description` varchar(120) NULL | — |
| `official_channel` | `id` PK; `label` varchar(80) NOT NULL; `value` varchar(255) NOT NULL; `position` smallint NOT NULL default 0 | — |
| `fallback_contact` | `scope` enum `area_scope` PK; `email` varchar(320) NOT NULL | — |

**Migración B — `create executive tables`:**
| Tabla | Columnas | Índices |
|---|---|---|
| `executive` | `id` PK; `username` varchar(80) NOT NULL; `display_name` varchar(120) NOT NULL; `password_hash` text NOT NULL; `failed_attempts` smallint NOT NULL default 0; `locked_until` timestamptz NULL; `active` bool NOT NULL default true; `last_seen_at` timestamptz NULL; `connected` bool NOT NULL default false | único (`lower(username)`) |
| `executive_session` | `id` PK; `executive_id` FK ON DELETE CASCADE NOT NULL; `token_hash` char(64) NOT NULL (sha256); `expires_at` timestamptz NOT NULL; `created_at` timestamptz NOT NULL default now() | único (`token_hash`); (`expires_at`) |

**Migración C — `create web chat tables`:**
| Tabla | Columnas | Índices |
|---|---|---|
| `web_session` | `id` uuid PK (también es el `thread_id` del checkpointer); `phase` enum `web_phase` NOT NULL default `bot`; `contact_attempts` smallint NOT NULL default 0; `pending_question` text NULL; `connected` bool NOT NULL default false; `last_seen_at` timestamptz NULL; `last_message_at` timestamptz NOT NULL; `created_at` timestamptz NOT NULL default now() | (`connected`, `last_seen_at`); (`last_message_at`) |
| `live_chat` | `id` PK; `web_session_id` FK ON DELETE CASCADE NOT NULL; `status` enum `live_chat_status`(`waiting`,`assigned`,`closed`) NOT NULL; `customer_name` varchar(120) NOT NULL; `customer_contact` varchar(320) NOT NULL; `pending_question` text NOT NULL; `executive_id` FK → executive NULL; `assigned_at`, `executive_disconnected_at`, `closed_at` timestamptz NULL; `close_reason` enum (`executive`,`customer_left`,`executive_timeout`,`schedule_end`) NULL; `created_at` timestamptz NOT NULL default now() | único parcial (`web_session_id`) WHERE status <> 'closed'; (`status`, `created_at`); (`executive_id`) WHERE status = 'assigned' |
| `live_chat_message` | `id` bigint PK; `live_chat_id` FK ON DELETE CASCADE NOT NULL; `sender` enum (`customer`,`executive`) NOT NULL; `content` text NOT NULL; `created_at` timestamptz NOT NULL default now() | (`live_chat_id`, `id`) |

**Migración E (Ampliación) — `add procedures and chat spaces`:**
| Tabla | Cambio | Índices |
|---|---|---|
| `procedure` (nueva) | `id` PK; `area_id` FK → business_area ON DELETE CASCADE NOT NULL; `name` varchar(160) NOT NULL; `steps` text NOT NULL (lo que se explica al usuario); `active` bool NOT NULL default true; `content_hash` text GENERATED ALWAYS AS (md5(name ‖ E'\n' ‖ steps)) STORED; `embedded_hash` text NULL; `embedding` vector(768) NULL | (`area_id`); HNSW (`embedding vector_cosine_ops`) |
| `procedure_field` (nueva) | `id` PK; `procedure_id` FK → procedure ON DELETE CASCADE NOT NULL; `name` varchar(60) NOT NULL (clave en la notificación); `label` varchar(120) NOT NULL (cómo se pide); `kind` enum `field_kind`(`text`,`email`,`phone`,`rut`,`number`,`date`) NOT NULL; `position` smallint NOT NULL default 0 | único (`procedure_id`, `name`) |
| `business_area` | Añade `chat_space` varchar(255) NULL (`spaces/…`). Elimina `owner_email` | — |
| `fallback_contact` → `fallback_space` | Se renombra; se elimina `email` y se añade `chat_space` varchar(255) NOT NULL. Las filas existentes se borran en el upgrade (un correo no se puede convertir en un space); hoy no hay ninguna en un entorno desplegado | PK `scope` |
| `chat_thread` (nueva) | `conversation_id` varchar(255) PK (space en un mensaje directo, hilo en un space de grupo); `last_message_at` timestamptz NOT NULL | (`last_message_at`) |

El downgrade revierte todo: vuelve a crear `owner_email` y `email` vacíos y borra las tablas nuevas y el enum. No toca
las migraciones A–D.

**Migración D — `create langgraph checkpoint tables`:** ejecuta las sentencias de `AsyncPostgresSaver.MIGRATIONS` de la
versión fijada en `uv.lock` y registra sus versiones en `checkpoint_migrations`, de modo que `.setup()` no haga nada en
el arranque. El downgrade borra esas tablas.

Las cuatro migraciones se generan con `alembic revision` y se revisan a mano. Ninguna toca las migraciones existentes.
Los enums se crean y se borran explícitamente en upgrade/downgrade.

## 4. Contrato
El backend es el dueño de los contratos. El frontend web y el panel de ejecutivos (fuera de alcance) se adaptan a ellos.

**HTTP**
| Método y ruta | Cuerpo | Respuestas | RF |
|---|---|---|---|
| `POST /api/v1/executives/login` | `{username, password}` | 200 `{token, expires_at}`; 401 `{detail: "Usuario o contraseña incorrectos"}` (también con la cuenta bloqueada o inexistente); 503 | RF-70–73 |
| `POST /api/v1/executives/logout` | — (`Authorization: Bearer`) | 204; 401 | RF-75 |
| `GET /api/v1/live-chats?status=waiting` | — (Bearer) | 200 `[{id, customer_name, created_at}]` (orden FIFO); 401; 503 | RF-74, RF-75 |
| `POST /api/v1/live-chats/{id}/take` | — (Bearer) | 200 `{id, customer_name, customer_contact, pending_question}`; 404; 409 `ya asignado`; 409 `máximo de chats alcanzado`; 401; 503 | RF-39–43 |
| `POST /api/v1/live-chats/{id}/close` | — (Bearer, solo el ejecutivo asignado) | 204; 403; 404; 401 | RF-55, RF-56 |
| `POST /api/v1/google-chat/events` | Evento de interacción de Google Chat (`type`, `space.name`, `message.text`, `message.argumentText`, `message.thread.name`, `user.email`, `user.displayName`) | 200 `{text}` o `{}`; 401 si el token no es válido | RF-57–69 |

**WebSocket `/ws/v1/chat?session_id=<uuid opcional>`** (cliente)
- Al conectar, el servidor envía `{type:"session", session_id}`. Si la sesión es nueva, caducada o inexistente, la crea (RF-80). Si hay 50 sesiones activas, envía `{type:"busy", channels}` y cierra con 1013 (RF-81).
- **Cliente → servidor:**
  - `{type:"message", text}`
  - `{type:"human_response", accept: bool}`
  - `{type:"contact", name, email?, phone?}`
  - `{type:"request_human"}`
  - `{type:"ping"}`
- **Servidor → cliente:**
  - `{type:"message", from:"bot"|"executive", text}`
  - `{type:"offer_human"}`
  - `{type:"request_contact", attempt}`
  - `{type:"queued"}`
  - `{type:"executive_joined"}`
  - `{type:"executive_disconnected", return_within_minutes: 60}`
  - `{type:"chat_closed", reason, channels?}`
  - `{type:"official_channels", channels}`
  - `{type:"error", code:"empty_message"|"message_too_long"|"service_unavailable", text}`

**WebSocket `/ws/v1/executive`** (ejecutivo)
- El primer mensaje debe ser `{type:"auth", token}`. Si el token no es válido, el servidor cierra con 4401 (RF-75).
- **Servidor → ejecutivo:** al conectar, `{type:"assigned_chats", chats}` (retoma, RF-50); después `{type:"message", chat_id, text}` y `{type:"chat_closed", chat_id, reason}`.
- **Ejecutivo → servidor:** `{type:"message", chat_id, text}` y `{type:"ping"}`.

**Ampliación — contrato:** sin cambios en HTTP ni en los mensajes WebSocket. Los procedimientos se conversan con
`message` (el modelo pide los datos y el código los valida). Al entregarse una notificación, el cliente recibe un
`message` del bot con la confirmación; si falla, `official_channels` (RF-101). Mensajes nuevos de salida hacia Google
Chat (`spaces.messages.create` en el space del área, sin hilo):
- **Solicitud (RF-95–97):** `Nueva solicitud: <procedimiento>` · `Canal: chat web | Google Chat` · `Solicitante: <nombre> <correo de Google Chat>` o `<nombre> · <contacto>` · `Datos:` una línea `<label>: <valor>` por campo · `Mensaje original: <texto>`.
- **Consulta interna sin respuesta (RF-58, RF-59):** `Consulta sin respuesta del asistente` · `Área: <nombre o "sin área">` · `Colaborador: <nombre> <correo>` · `Consulta: <texto>`.

**Rediseño — contrato de Google Chat (complemento de Google Workspace):** `POST /api/v1/google-chat/events` recibe el
objeto de evento del complemento (`commonEventObject`, `chat.user`, `chat.messagePayload.message` con `text`,
`argumentText` y `thread.name`, `chat.messagePayload.space` con `name` y `spaceType`, `chat.addedToSpacePayload.space`)
con `Authorization: Bearer <ID token de Google>`. Responde 200 con
`{"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": "…"}}}}}` o `{}`; 401 si el
token no es válido. Sin cambios en HTTP ni WebSocket del canal web.

## 5. Decisiones
- **D1 — Un grafo por ámbito, con un clasificador que ve las áreas de ambos ámbitos solo por nombre y descripción.** *(Sustituida por D33 el 2026-10-07: ya no hay clasificador aparte.)* Es la única forma de detectar las preguntas mixtas (RF-8). El clasificador devuelve ids, y el texto al usuario nunca sale de él. *Descartada:* un clasificador que solo ve su propio ámbito — no puede detectar las preguntas mixtas.
- **D2 — `AgentLLM` como interfaz tipada propia sobre LangChain.** *(Se mantiene; la Ampliación cambia `answer` por `step`, D21.)* Permite tests deterministas con un fake (los fakes de LangChain no soportan salida estructurada) y cumple el punto 3 de la constitución. *Descartada:* usar `ChatGoogleGenerativeAI` directamente en los nodos — no se puede probar sin red.
- **D3 — Sub-agente sin FAQ por encima de `rag_min_similarity` ⇒ `no_answer` sin llamar al LLM.** *(Sustituida por D22 el 2026-10-07.)* Garantiza RF-9 (no inventa nada) y ahorra latencia. *Descartada:* dejar que el LLM decida si puede responder sin FAQ — viola RF-9.
- **D4 — Embeddings recalculados de forma perezosa por `content_hash` generado en la BD.** Cumple RF-11 sin CRUD ni scripts: el responsable edita por SQL y la siguiente consulta recalcula. *Descartada:* un script de indexación manual — el cambio no se aplicaría "a partir del siguiente mensaje".
- **D5 — pgvector con 768 dimensiones e índice HNSW.** Cabe dentro del límite de 2000 dimensiones del índice y Gemini lo recomienda como equilibrio. *Descartada:* 3072 dimensiones — sin índice HNSW posible y con más almacenamiento.
- **D6 — Checkpointer `AsyncPostgresSaver` con un pool de psycopg propio, solo para el canal web.** *(Ampliada por D27: también para Google Chat.)* Es el checkpointer oficial y el usuario ya lo aprobó, aunque obliga a tener un segundo driver (psycopg) junto a asyncpg. El canal interno es stateless porque la spec no le pide memoria. *Descartada:* escribir un checkpointer sobre asyncpg — demasiado código propio de mantener.
- **D7 — Tablas del checkpointer creadas por una migración de Alembic (migración D).** Respeta el punto 8 de la constitución. *Descartada:* `.setup()` en el arranque — cambia el esquema fuera de Alembic.
- **D8 — Interacción con el cliente por mensajes tipados del WebSocket** (`human_response`, `contact`). La aceptación y los datos de contacto se validan de forma determinista. La petición explícita de hablar con un humano se acepta tanto tipada (`request_human`) como en lenguaje natural, a través del clasificador. *Descartada:* interpretar "sí/no" con el LLM — es ambiguo y no se puede probar.
- **D9 — Reparto entre pods con LISTEN/NOTIFY de PostgreSQL; el payload solo lleva ids.** No añade infraestructura, y los mensajes de 5000 caracteres pueden superar el límite de 8000 bytes de NOTIFY. *Descartadas:* Redis pub/sub — infraestructura y dependencia nuevas; sticky sessions — no sirven porque el cliente y el ejecutivo son conexiones distintas.
- **D10 — Temporizadores con un barrido periódico de 30 s y advisory lock.** Sobrevive al reinicio de pods y reutiliza el patrón de `alembic/env.py`. El cierre ocurre como mucho 30 s después del plazo. *Descartada:* `asyncio` timers por chat — se pierden si el pod muere.
- **D11 — Detección de desconexiones por cierre del WebSocket más heartbeat (`last_seen_at`, umbral 90 s).** Un pod que muere no avisa del cierre de sus sockets. *Descartada:* confiar solo en el evento de cierre — dejaría sesiones "conectadas" que bloquean el límite de 50.
- **D12 — Límite de 50 contado en la BD bajo `pg_advisory_xact_lock`.** Es global entre pods y evita que dos conexiones simultáneas lo superen. *Descartada:* un contador en memoria por pod — no es global.
- **D13 — Sesión del ejecutivo con un JWT HS256 (`sub`, `jti`, `exp`) firmado con la property `jwt_secret`, revocable porque la BD guarda el sha256 del `jti`.** Cambiada el 2026-10-07 a petición del usuario (antes: token opaco aleatorio), para declarar el esquema Bearer JWT en OpenAPI; añade la dependencia PyJWT, aprobada por el usuario. El JWT se valida y además se busca su sesión, así el logout lo invalida. *Descartada:* JWT sin tabla de sesiones — no se podría revocar.
- **D14 — Login con respuesta genérica, también para cuentas bloqueadas o inexistentes, y verificación con un hash ficticio.** Cumple RF-71 y evita enumerar usuarios por tiempos de respuesta. *Descartada:* un mensaje "cuenta bloqueada" — revela que el usuario existe.
- **D15 — Google Chat como app de eventos de interacción, con audiencia = URL del endpoint.** *(Sustituida por D38 el 2026-10-07: la app es un complemento de Google Workspace.)* Es el formato documentado del objeto `Event` y el más simple de validar. *Descartada:* complemento de Google Workspace — otro formato de eventos y de respuestas sin beneficio para esta spec.
- **D16 — Token de Google verificado con `google.auth.jwt.decode` y certificados cacheados por httpx; OAuth de la cuenta de servicio por JWT-bearer.** *(La verificación del token se sustituye por D38; el OAuth de la cuenta de servicio para la API de Chat se mantiene.)* No requiere `requests` y no bloquea el event loop. *Descartada:* `google.auth.transport.requests` — añade `requests` y es síncrono.
- **D17 — Límite de 30 s con `asyncio.wait_for` (`google_chat_sync_timeout_seconds`, 25 por defecto).** Si se agota el plazo, se responde "Estoy procesando tu consulta…" y la tarea sigue en segundo plano hasta publicar con `spaces.messages.create` en el mismo hilo. *Descartada:* responder siempre de forma asíncrona — es más lento y obliga a usar credenciales en todos los mensajes.
- **D18 — Correo con `smtplib` en `asyncio.to_thread`.** *(Sustituida por D26 el 2026-10-07: el correo desaparece.)* No añade dependencias. *Descartada:* `aiosmtplib` — una dependencia nueva para pocos correos.
- **D19 — Datos de negocio y properties leídos sin caché en cada uso.** RF-11 exige aplicar los cambios de prompts y FAQ al siguiente mensaje. El 2026-10-07 el usuario pidió quitar también la caché de 60 s de las properties: cada lectura consulta solo la key pedida. *Descartada:* una caché con TTL — un cambio en la BD tardaría en aplicarse.
- **D20 — Lógica de dominio pura separada del SQL; el reloj se inyecta con `Clock`.** Permite probar plazos y concurrencia sin BD ni esperas (punto 6 de la constitución y criterio de finalización). *Descartada:* un repositorio con tests contra la BD — prohibido por la constitución.

**Decisiones de la Ampliación (2026-10-07):**
- **D21 — Bucle de tools propio por sub-agente sobre `AgentLLM.step`, con un máximo de 4 pasos.** *(Sustituida por D32 el 2026-10-07.)* Mantiene D2: los tests guionizan los pasos del modelo con `FakeAgentLLM` (pide tal tool, luego responde tal texto) sin red ni fakes de LangChain, y el guardarraíl y el conteo de evidencias quedan en nuestro código. El tope de 4 pasos acota la latencia. *Descartadas:* `create_react_agent` de LangGraph — el guardarraíl quedaría fuera de nuestro control y no se podría guionizar sin los fakes de LangChain; un único agente con tools por canal sin sub-agentes — el usuario eligió sub-agentes por área.
- **D22 — Guardarraíl de RF-89 en código: un texto final solo vale si el sub-agente tiene evidencias en esa ejecución** *(Sustituida por D34 el 2026-10-07.)* (FAQ o procedimientos sobre `rag_min_similarity` devueltos por sus tools, o una notificación entregada). Sin evidencias, la respuesta se descarta y el área cuenta como `no_answer`. Sustituye a D3: el modelo se llama siempre, porque es él quien redacta la consulta de búsqueda con el contexto de la conversación (resuelve las preguntas de seguimiento, demo 8). *Descartada:* mantener la búsqueda previa obligatoria con la pregunta literal (D3) — no permite reformular con contexto y falló en la demo 8.
- **D23 — El área de las tools la fija el código.** *(Sustituida por D33 el 2026-10-07: el código elige qué contenido entra en la llamada.)* `buscar_faq` y `buscar_procedimiento` solo reciben la consulta; el `area_id` viene del `AreaToolbox` del sub-agente, y `notificar_area` solo acepta procedimientos de esa área. *Descartada:* el `area_id` como argumento de la tool — el modelo podría consultar otras áreas (RF-86, RNF-3).
- **D24 — Procedimientos en tablas propias, con campos tipados y validados en código.** `procedure` (con embedding, como las FAQ, D4/D5) y `procedure_field` con `kind` enumerado; `validate_field` comprueba formato y dígito verificador del RUT. Los intentos (RF-94) se cuentan en el estado del grafo (`procedure_attempts`), persistido por el checkpointer. *Descartadas:* los campos como JSONB en `procedure` — sin validación en la BD, los errores de carga solo aparecerían al usarlos; que el modelo valide los datos — no es determinista ni probable.
- **D25 — La notificación la redacta y la envía el código; el modelo solo aporta `procedimiento_id` y `datos`.** La identidad del solicitante sale del canal (Google Chat o datos de contacto del web), nunca del modelo; los datos no se registran en el log (RNF-8). En el canal web, `nombre` y `contacto` se añaden a los campos exigidos (RF-98). *Descartada:* que el modelo redacte el mensaje al área — podría alterar los datos o incluir instrucciones inyectadas por el usuario (RF-107).
- **D26 — Aviso al área por `spaces.messages.create` en el `chat_space` del área, con la cuenta de servicio ya existente (D16), en un hilo nuevo.** Sustituye al correo (D18) y elimina `Mailer`, `MailDeliveryError` y las properties `smtp_*`. El aviso de "sin respuesta" del canal interno sigue siendo código (`InternalStrategy`), no una tool, para que RF-57–59 sean deterministas. *Descartadas:* mantener el correo como respaldo — la spec lo deja fuera de alcance; una tool de escalado — el modelo podría escalar sin motivo o no hacerlo.
- **D27 — Memoria de Google Chat con el mismo checkpointer, `thread_id` = conversación: el space en un mensaje directo y el hilo en un space de grupo.** En los mensajes directos sin hilos cada mensaje trae un hilo nuevo, así que el hilo no sirve como conversación ahí. La retención se controla con `chat_thread.last_message_at` y el barrido (D10). *Descartadas:* `thread_id` = hilo siempre — en mensajes directos no habría memoria; leer la antigüedad de las tablas `checkpoint*` — su formato interno no es estable entre versiones (R8).
- **D28 — `derivar_a_ejecutivo` como tool del sub-agente web, que produce el outcome `wants_human` y reutiliza el flujo de D8.** *(Sustituida por D32: `wants_human` es un tipo de la respuesta estructurada.)* Permite que el sub-agente derive cuando un procedimiento o la conversación lo exige. El clasificador sigue detectando la petición explícita. *Descartada:* solo el clasificador — no ve las FAQ ni los procedimientos del área.
- **D29 — Protección frente a manipulación en los prompts de la BD (decisión del usuario), con una batería verificable.** Los prompts (`internal_agent`, `external_agent` y `area_rules`; el `classifier` dejó de usarse con D32) incluyen las cláusulas de no revelar instrucciones, tools, áreas ni funcionamiento interno, de ignorar instrucciones del usuario o de los datos, y la respuesta genérica de RF-108. Desde el rediseño, el auditor en código (RF-109) actúa además como el filtro de salida que aquí se descartó. Su texto solo vive en `agent_prompt`: por decisión del usuario (2026-10-07) no se versiona en el código ni en el historial de git. En código: los datos del usuario nunca entran en el system prompt y la notificación la redacta el código (D25). El cumplimiento se mide con `jailbreak_check` (RNF-9). *Descartada:* un filtro de salida en código que bloquee las respuestas parecidas a los prompts — el usuario pidió resolverlo en el prompt; queda como mitigación si la batería falla (R16).
- **D30 — Los clientes de Gemini y del recuperador se reutilizan, y la conexión a la BD se libera antes de llamar al modelo** (correcciones del 2026-10-07, ya implementadas). El bucle de tools vuelve a abrir sesiones breves para cada búsqueda. *Descartada:* una sesión de BD por mensaje durante todo el bucle — agotó el pool con 50 sesiones (R2).

- **D31 — La respuesta de RF-108 la da el código cuando el clasificador marca el mensaje como manipulación** *(Se mantiene la idea; la marca pasa a la respuesta estructurada, D32.)* (corrección del 2026-10-07 tras T-87). `ClassificationOutput` añade `manipulation: bool`; si es verdadero, el grafo termina con el outcome `rejected` sin llamar a los sub-agentes, y ambos canales responden con la negativa genérica, sin ofrecer un ejecutivo. *Descartada:* dejar la negativa al texto del prompt — el clasificador mandaba los ataques a "ninguna área" y el canal aplicaba el flujo de sin respuesta, que ofrecía un ejecutivo a quien intentaba manipular el bot.

**Decisiones del rediseño (2026-10-07):**
- **D32 — Una sola llamada de generación por mensaje con salida estructurada (`AgentReply`).** Cumple RNF-10 y baja la latencia (R12). El mismo resultado trae el tipo (`answer`, `no_answer`, `wants_human`, `manipulation`, `procedure`), el texto, las FAQ usadas y el procedimiento con sus datos; todo lo demás es código. *Descartadas:* tools con cierre terminal (como el repo de referencia) — siguen siendo 2 llamadas por pregunta; clasificador + respuesta — 2 llamadas.
- **D33 — Recuperación previa, por ámbito y sin el contenido del otro ámbito.** Un embedding de «mensaje anterior del usuario + mensaje actual» (contexto para las preguntas de seguimiento) busca FAQ y procedimientos de todas las áreas activas del ámbito; al modelo solo llegan esos resultados, agrupados por área con el prompt de cada una. Para RF-8 se calcula también la mejor similitud contra el otro ámbito sin mandar su contenido: si las dos superan `rag_min_similarity`, la pregunta es mixta y se responde sin llamar al modelo. *Descartada:* que el modelo vea las áreas del otro ámbito — expone nombres internos en el canal web y obliga a otra llamada.
- **D34 — Guardarraíl sobre la respuesta estructurada:** `answer` solo vale si cita `faq_ids` que están entre los recuperados (o un procedimiento recuperado o en curso); si no, `no_answer`. *Descartada:* confiar en el texto — el modelo podría responder sin apoyo (RF-9).
- **D35 — Procedimiento en curso en el estado del grafo (`pending_procedure_id`) y mensajes con plantillas.** El procedimiento identificado se guarda en el estado y se vuelve a inyectar en los turnos siguientes aunque la búsqueda no lo recupere; el modelo devuelve los datos que el usuario entregó en la conversación, el código los valida, cuenta los intentos y responde con plantillas: «Para continuar necesito: …», «Estos datos no son válidos: …», «Tu solicitud fue enviada al área…» o el mensaje de notificación fallida. *Descartada:* que el modelo redacte la confirmación — exigiría una segunda llamada tras notificar.
- **D36 — Auditor determinista de fugas antes de enviar (RF-109).** Busca fragmentos de 30 o más caracteres de los prompts de la BD, nombres internos (tipos y campos de la respuesta estructurada) y código; si encuentra algo, sustituye el texto por la negativa genérica y es ese texto el que queda en la memoria. Cero llamadas extra. *Descartada:* un juez con LLM — suma una llamada y ~1 s (medido en el repo de referencia).
- **D37 — Ajustes de latencia del modelo:** `temperature=0`, `thinking_budget=0` y ventana de historial `agent_history_messages` (20 mensajes). *Descartada:* resumir el historial — otra llamada.
- **D38 — Google Chat como complemento de Google Workspace.** La app ya está creada así. Token: ID token de Google con audiencia `google_chat_audience`, emisor `accounts.google.com` y `email` igual a la cuenta de servicio del complemento (`google_chat_addon_service_account`, p. ej. `service-<n.º de proyecto>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`) con `email_verified`. Eventos `chat.*` y respuesta `hostAppDataAction`. *Descartada:* recrear la app como app de Chat clásica — la app ya existe en esta modalidad.

**Properties nuevas** (las que tienen valor por defecto lo traen en el código):
- **Obligatorias:**
  - `gemini_model`, `gemini_api_key`, `gemini_embedding_model` (`gemini-embedding-001`).
  - `google_chat_audience` (URL pública del endpoint) y `google_chat_service_account_json`.
  - ~~`smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_starttls`~~ (eliminadas en la Ampliación, D26).
  - `jwt_secret` (clave HS256 de al menos 32 caracteres).
- **Con valor por defecto:**
  - **RAG y LLM:** `rag_top_k` (4), `rag_min_similarity` (0.68), `llm_timeout_seconds` (20).
  - **Sesiones web:** `web_session_retention_days` (30), `web_max_sessions` (50).
  - **Ejecutivos:** `executive_max_chats` (3), `executive_session_hours` (8), `login_max_attempts` (5), `login_lock_minutes` (15), `executive_reconnect_minutes` (60).
  - **Google Chat:** `google_chat_sync_timeout_seconds` (25), `google_chat_retention_days` (30, Ampliación, RF-105).
  - **Agentes:** `procedure_max_attempts` (3, RF-94) y `agent_history_messages` (20, D37). ~~`agent_max_steps`~~ (eliminada en el rediseño).
  - **Google Chat (rediseño):** `google_chat_addon_service_account` (obligatoria, D38).
  - La key `classifier` de `agent_prompt` deja de usarse en el rediseño: la clasificación va en el prompt del agente.

## 6. Estrategia de tests
Ningún test se conecta a la BD ni a la red. Los tests async usan el plugin `anyio`, que ya viene con FastAPI/Starlette, así que no añaden dependencias.

| Nivel | Archivo | Qué prueba |
|---|---|---|
| Unidad | `tests/message_validation_test.py` | Mensaje vacío, solo espacios, exactamente 5000 caracteres (válido) y 5001 (rechazado) |
| Unidad | `tests/schedule_test.py` | Franja por día, día sin franja, festivo, minuto de apertura (abierto), minuto de cierre (cerrado), cambio de horario de verano en America/Santiago |
| Unidad | `tests/agent_graph_test.py` | Grafo con `FakeAgentLLM`, `FakeRetriever` e `InMemorySaver`. Casos: respuesta de una área; combinación de varias; respuesta parcial; sin FAQ ⇒ `no_answer` sin llamar al LLM; pregunta mixta; petición de humano; área sin prompt; LLM no configurado; LLM caído. **RNF-3:** el retriever del grafo externo nunca recibe áreas internas |
| Unidad | `tests/channel_strategy_test.py` | Externa: dentro y fuera de horario. Interna: correo al responsable, correo general, fallo de correo con mensaje al colaborador y log (`caplog`). Usa un `FakeMailer` |
| Unidad | `tests/live_chat_test.py` | Dominio puro con `FakeClock`: transiciones de estado, toma exclusiva (dos tomas ⇒ un `ChatAlreadyAssignedError`), máximo de chats, desconexión y retoma antes de 60 min, cierre a los 60 min, desconexión del cliente, cierre por el ejecutivo |
| Unidad | `tests/sweeper_test.py` | Con `FakeClock`: cierre por fin de horario (solo los chats en espera), plazo del ejecutivo, heartbeat vencido, retención de 30 días contados desde el último mensaje |
| Servicio | `tests/executive_auth_test.py` | Login correcto, incorrecto y de usuario inexistente (mismo mensaje), bloqueo al quinto fallo, bloqueo aunque la contraseña sea correcta, desbloqueo a los 15 min (`FakeClock`), sesión caducada a las 8 h, hash Argon2 ≠ contraseña |
| API | `tests/executive_api_test.py` | Login, logout y endpoints de `live-chats` con `dependency_overrides` de los servicios: 200, 401, 404, 409 y 503 |
| API (WS) | `tests/web_chat_ws_test.py` | `TestClient.websocket_connect` con los servicios sustituidos. Casos: sesión nueva o caducada; oferta, aceptación y datos inválidos ×3 ⇒ canales oficiales; cola; rechazo; `busy` a las 50 sesiones; error `service_unavailable` con la BD caída (RF-82, RF-83, con `caplog`) |
| API (WS) | `tests/executive_ws_test.py` | Autenticación por el primer mensaje (4401), entrega de mensajes en ambos sentidos a través de un `FakeHub`, aviso de chat cerrado, chats asignados al reconectar |
| API | `tests/google_chat_test.py` | Token inválido ⇒ 401; DM; mención (usa `argumentText`); `ADDED_TO_SPACE` ⇒ saludo con las áreas; otros eventos ⇒ `{}`; respuesta lenta ⇒ "procesando" y publicación en el mismo hilo (fake `ChatApiClient`, timeout de 0.05 s por override de property) |

Casos límite de la spec con test propio:
- Área sin FAQ o sin prompt (`agent_graph_test`).
- Toma simultánea del mismo chat (`live_chat_test`).
- Desconexión durante la generación de la respuesta (`web_chat_ws_test`).
- Minuto de cierre (`schedule_test`).
- Chats en vivo que siguen al terminar el horario (`sweeper_test`).
- Intento de revelar información interna (`agent_graph_test`, RNF-3).

La atomicidad real en SQL (RF-40, RF-41, RF-81) y la persistencia del checkpointer se validan en la demo manual del despliegue, como acordó la spec.

**Ampliación — tests nuevos o cambiados** (mismas reglas: sin BD ni red; el modelo se guioniza con `FakeAgentLLM`, que recibe una lista de pasos `ToolCalls`/`FinalText`):

| Nivel | Archivo | Qué prueba |
|---|---|---|
| Unidad | `tests/sub_agent_test.py` (nuevo) | Tool `buscar_faq` y luego respuesta ⇒ `answered`; texto final sin llamar a ninguna tool ⇒ descartado (RF-89); tool sin resultados sobre el umbral y después texto ⇒ descartado; se superan los 4 pasos ⇒ `no_answer`; `buscar_faq` con argumentos que intentan otra área ⇒ el recuperador recibe el `area_id` del sub-agente (RF-86); `notificar_area` válido ⇒ notificador llamado con la identidad del canal (RF-96, RF-97); datos inválidos ⇒ error devuelto al modelo e intento contado; tercer intento inválido ⇒ `gave_up` (RF-94); fallo de entrega ⇒ `notification_failed`; `derivar_a_ejecutivo` ⇒ `wants_human`; en web, sin `nombre`/`contacto` ⇒ se exigen (RF-98) |
| Unidad | `tests/procedures_test.py` (nuevo) | `validate_field` por tipo (RUT con dígito verificador correcto e incorrecto, correo, teléfono, número, fecha, texto vacío); `format_request` incluye procedimiento, datos e identidad; con `caplog`, los datos del usuario nunca aparecen en el log (RNF-8) |
| Unidad | `tests/retriever_test.py` | Además: `search_procedures` filtra por área, activo y umbral; el refresco cubre las dos tablas |
| Unidad | `tests/agent_graph_test.py` | Pasa a pasos guionizados. Además: la consulta de búsqueda es la que redacta el modelo, no la pregunta literal (demo 8); `procedure_attempts` se conserva entre mensajes del mismo hilo (`InMemorySaver`); outcome `notification_failed`; RNF-3 se mantiene (el sub-agente externo nunca recibe un toolbox de un área interna) |
| Unidad | `tests/channel_strategy_test.py` | Interna: aviso al space del área, al space general, área sin space ⇒ fallida (RF-102), fallo de entrega ⇒ log y "contacta directamente" (RF-60, RF-61). `FakeNotifier` sustituye a `FakeMailer` |
| Unidad | `tests/area_notifier_test.py` (nuevo) | `create_message` sin hilo (sin `messageReplyOption`) por `httpx.MockTransport`; error HTTP ⇒ `NotificationDeliveryError` |
| API | `tests/google_chat_test.py` | Además: `conversation_id` es el space en un mensaje directo y el hilo en un space; la identidad del colaborador llega al orquestador |
| Servicio | `tests/chat_orchestrator_test.py` | Además: memoria interna por conversación y aislamiento entre dos hilos del mismo space (RF-103, RF-104); `notification_failed` ⇒ canales oficiales en web (RF-101) y "contacta directamente" en interno (RF-61) |
| Unidad | `tests/sweeper_test.py` | Además: hilos de Google Chat caducados ⇒ `adelete_thread` y borrado de `chat_thread` (RF-105) |
| Unidad | `tests/jailbreak_check_test.py` (nuevo) | El detector marca como fuga una respuesta con un fragmento de 30 o más caracteres de un prompt, el nombre de una tool o el nombre de un área interna, y no marca una negativa genérica; la batería tiene al menos 20 ataques (RNF-9) |
| Eliminado | `tests/mailer_test.py` | Se borra con `mailer.py` |

Casos límite de la spec ampliada con test propio: área con solo FAQ o solo procedimientos (`sub_agent_test`); FAQ y procedimiento a la vez (`sub_agent_test`); datos entregados de una vez (`sub_agent_test`); instrucciones inyectadas en los datos (`sub_agent_test`: la notificación las incluye como dato literal y no cambian el flujo); cambio de tema a mitad de la recogida (`agent_graph_test`). La resistencia del modelo a la manipulación (RF-106–108) se mide en la demo 12 con `jailbreak_check`, porque necesita el modelo real.

## 7. Orden de implementación
1. Dependencias, `Clock`, helpers tipados de property y excepciones nuevas. Test: `pyright` + suite actual en verde.
2. Modelos y migraciones A, B y C; `include_object` en `env.py`. Revisión manual de cada migración.
3. `message_validation` y `schedule` con sus tests.
4. `business_data`, `AgentLLM` + `GeminiAgentLLM`, `FaqRetriever` y el refresco perezoso de embeddings.
5. `graph.py` + `strategies.py` + `agent_graph_test` y `channel_strategy_test`.
6. `mailer`, `google_chat` (verificación, eventos, cliente asíncrono), su router y `google_chat_test`. Primer flujo de punta a punta: el canal interno.
7. `executive_auth`, el router de login/logout y sus tests.
8. Migración D, checkpointer en el lifespan, `web_session` (admisión, máquina de estados, heartbeat), `chat_orchestrator`, `WS /ws/v1/chat` (fase bot, oferta, contacto, cola) y `web_chat_ws_test`.
9. `realtime` (hub + NOTIFY), `live_chat` (dominio y SQL), router de `live-chats`, `WS /ws/v1/executive` y sus tests.
10. `sweeper` en el lifespan, con `sweeper_test`.
11. README: endpoints, properties, tablas que hay que cargar y extensión `vector`. Demo manual de la spec en el despliegue.

**Ampliación (cada paso deja la suite en verde):**
12. Migración E y modelos (`procedure`, `procedure_field`, `chat_space`, `fallback_space`, `chat_thread`); ciclo upgrade/downgrade.
13. `procedures.py` (validadores) y `area_notifier.py` (formato y envío); `create_message` sin hilo.
14. `InternalStrategy` con `AreaNotifier`; se eliminan `mailer.py`, `MailDeliveryError` y las properties `smtp_*`.
15. Recuperador de procedimientos (`search_procedures` y refresco de ambas tablas).
16. `AgentLLM.step`, `GeminiAgentLLM.step` con `bind_tools`, `tools.py` y `sub_agent.py` con el guardarraíl.
17. El grafo usa `run_sub_agent`; outcomes `notification_failed` y `wants_human`; `procedure_attempts`; orquestador de ambos canales.
18. Memoria de Google Chat: grafo interno con checkpointer en el lifespan, `conversation_id`, `chat_thread` y barrido.
19. `jailbreak_check` y actualización de los prompts en la BD local (su texto no se versiona).
20. README; repetición de la carga (T-56) y demo de 12 pasos (T-59).

**Rediseño (cada paso deja la suite en verde):**
21. `AgentReply`, `ReplyOutput` y `GeminiAgentLLM.respond`; `build_reply_messages`.
22. `search_scope` en el recuperador; `audit.py`; `procedure_flow.py`.
23. Grafo de una llamada (`retrieve` → `respond` → `finalize`) y retirada de `tools.py`, `sub_agent.py` y del clasificador.
24. Google Chat como complemento: verificación del ID token, evento y respuesta.
25. Pruebas de rigor en local (batería, demo, preguntas legítimas, carga) y README.

## 8. Matriz de cobertura
| RF | Módulos | Tests |
|---|---|---|
| RF-1, RF-2 | `strategies`, `chat_orchestrator`, `routers/google_chat`, `routers/web_chat` | `agent_graph_test`, `google_chat_test`, `web_chat_ws_test` |
| RF-3, RF-4 | `graph` (`load_context` por ámbito), `business_data` | `agent_graph_test` (RNF-3) |
| RF-5, RF-6, RF-7 | `graph` (`classify`, `answer_area`, `combine`), `llm` | `agent_graph_test` |
| RF-8 | `graph` (`classify` → `mixed_scope`), `chat_orchestrator` | `agent_graph_test` |
| RF-9 | `retriever`, `sub_agent` (guardarraíl, D22) | `sub_agent_test`, `agent_graph_test` |
| RF-10, RF-11 | `business_data` (sin caché), `retriever.refresh_stale_embeddings` | `agent_graph_test` |
| RF-12, RF-13, RF-14 | `llm`, `property` helpers, `chat_orchestrator` | `agent_graph_test` (caplog sin API key) |
| RF-15, RF-16, RF-17 | `message_validation`, routers web y Google Chat | `message_validation_test`, `web_chat_ws_test` |
| RF-18 | `llm`, `chat_orchestrator` | `agent_graph_test`, `web_chat_ws_test` |
| RF-19–RF-23 | `schedule` | `schedule_test` |
| RF-24 | `business_data.get_official_channels` | `channel_strategy_test` |
| RF-25, RF-26 | `strategies.ExternalStrategy`, `graph` (`wants_human`), `tools.derivar_a_ejecutivo` (D28), `web_session` | `channel_strategy_test`, `sub_agent_test`, `web_chat_ws_test` |
| RF-27–RF-31 | `web_session`, `live_chat.enqueue`, `routers/web_chat` | `web_chat_ws_test` |
| RF-32, RF-33 | `strategies.ExternalStrategy`, `web_session` | `channel_strategy_test`, `web_chat_ws_test` |
| RF-34, RF-35 | `live_chat`, `web_session`, `sweeper` (heartbeat) | `live_chat_test`, `sweeper_test` |
| RF-36, RF-37, RF-38 | `sweeper`, `schedule`, `realtime` | `sweeper_test` |
| RF-39, RF-40, RF-41 | `live_chat.take`, `routers/live_chat` | `live_chat_test`, `executive_api_test` |
| RF-42, RF-43 | `live_chat.take`, `realtime` | `executive_api_test`, `web_chat_ws_test` |
| RF-44, RF-45, RF-46 | `live_chat.post_message`, `realtime`, `chat_orchestrator` | `executive_ws_test`, `web_chat_ws_test` |
| RF-47, RF-48, RF-49 | `live_chat.mark_executive_disconnected`, `executive_auth`, `routers/executive` | `live_chat_test`, `executive_ws_test` |
| RF-50 | `live_chat.resume`, `routers/executive` | `executive_ws_test`, `live_chat_test` |
| RF-51, RF-52 | `sweeper`, `realtime` | `sweeper_test` |
| RF-53, RF-54 | `live_chat.customer_disconnected`, `realtime` | `live_chat_test`, `executive_ws_test` |
| RF-55, RF-56 | `live_chat.close`, `routers/live_chat` | `live_chat_test`, `executive_api_test` |
| RF-57–RF-62 | `strategies.InternalStrategy`, `area_notifier`, `business_data.get_fallback_space` | `channel_strategy_test`, `area_notifier_test`, `google_chat_test` |
| RF-63, RF-64 | `google_chat.verify_chat_token` | `google_chat_test` |
| RF-65, RF-66, RF-67 | `google_chat.handle_event` | `google_chat_test` |
| RF-68, RF-69 | `google_chat` (D17), `ChatApiClient` | `google_chat_test` |
| RF-70–RF-73 | `executive_auth`, `routers/executive` | `executive_auth_test`, `executive_api_test` |
| RF-74, RF-75 | `routers/live_chat`, `routers/executive`, `executive_auth.authenticate` | `executive_api_test`, `executive_ws_test` |
| RF-76, RF-77, RF-78 | checkpointer (thread = `web_session.id`), `graph` | `agent_graph_test` (InMemorySaver, dos hilos aislados), `web_chat_ws_test` |
| RF-79, RF-80 | `sweeper`, `web_session` | `sweeper_test`, `web_chat_ws_test` |
| RF-81 | `web_session.admit` (D12) | `web_chat_ws_test` |
| RF-82, RF-83 | `routers/web_chat`, `chat_orchestrator` | `web_chat_ws_test` |

| RF-84, RF-85, RF-87, RF-88 | `tools` (`buscar_faq`, `buscar_procedimiento`), `retriever` | `sub_agent_test`, `retriever_test` |
| RF-86 | `tools` (`area_id` fijado por código, D23) | `sub_agent_test`, `agent_graph_test` (RNF-3) |
| RF-89, RF-90 | `sub_agent` (evidencias, D22) | `sub_agent_test` |
| RF-91, RF-92 | `tools.buscar_procedimiento`, `area_rules` (BD) | `sub_agent_test` |
| RF-93, RF-94 | `procedures.validate_field`, `graph` (`procedure_attempts`) | `procedures_test`, `sub_agent_test`, `agent_graph_test` |
| RF-95, RF-96, RF-97 | `tools.notificar_area`, `area_notifier.format_request` | `sub_agent_test`, `procedures_test` |
| RF-98 | `procedures.web_contact_fields` | `sub_agent_test` |
| RF-99 | `sub_agent` (texto final tras notificar) | `sub_agent_test` |
| RF-100 | `area_rules` (BD), `tools` (ninguna tool devuelve datos personales) | `sub_agent_test` |
| RF-101 | `chat_orchestrator` (`notification_failed` en web) | `chat_orchestrator_test` |
| RF-102 | `strategies.InternalStrategy`, `tools.notificar_area` | `channel_strategy_test`, `sub_agent_test` |
| RF-103, RF-104 | `google_chat.conversation_id`, grafo interno con checkpointer | `google_chat_test`, `chat_orchestrator_test` |
| RF-105 | `chat_thread`, `sweeper` | `sweeper_test` |
| RF-106, RF-107, RF-108 | prompts en `agent_prompt` (solo BD), clasificador (`manipulation`, D31), `chat_orchestrator` (negativa genérica), `area_notifier` (D25), `jailbreak_check` | `jailbreak_check_test`, `sub_agent_test` (inyección en datos), demo 12 |
| RNF-8 | `area_notifier` (sin datos en logs) | `procedures_test` (`caplog`) |
| RNF-9 | `jailbreak_check` | `jailbreak_check_test`, demo 12 |
| RF-5–RF-10 (rediseño) | `graph` (`retrieve`, `respond`, `finalize`), `llm.build_reply_messages` | `agent_graph_test`, `gemini_llm_test` |
| RF-84–RF-90 (rediseño) | `retriever.search_scope`, `graph.finalize` (guardarraíl D34) | `retriever_test`, `agent_graph_test` |
| RF-91–RF-102 (rediseño) | `procedure_flow`, `graph` (`pending_procedure_id`) | `procedure_flow_test`, `agent_graph_test` |
| RF-63–RF-67 (rediseño) | `google_chat.verify_addon_token`, `AddonEvent`, `chat_reply` | `google_chat_test` |
| RF-109 | `audit` | `audit_test`, `agent_graph_test` |
| RNF-10 | `graph` (un único nodo con LLM) | `agent_graph_test` (una llamada por mensaje) |

**Rediseño — tests:** `tests/gemini_llm_test.py` (`respond` con salida estructurada y `build_reply_messages`: sin contenido del otro ámbito, ids de FAQ y procedimientos, ventana de historial); `tests/retriever_test.py` (`search_scope` filtra por ámbito, activo y umbral, y devuelve la mejor similitud del otro ámbito); `tests/audit_test.py` (fragmentos de prompt, nombres internos, código, la negativa genérica no cuenta); `tests/procedure_flow_test.py` (faltantes, inválidos, intentos, sin space, fallo de entrega, enviada, inyección literal); `tests/agent_graph_test.py` reescrito (exactamente una llamada a `respond` por mensaje, mixta sin llamada, guardarraíl, procedimiento en dos turnos, auditor, memoria y RNF-3); `tests/google_chat_test.py` (ID token válido, otra cuenta, `email_verified` falso, otra audiencia, sin token; eventos del complemento y respuesta `hostAppDataAction`). Se eliminan `tests/sub_agent_test.py` y los casos de `step`, `classify` y `combine`.

## 9. Riesgos y dudas
Dudas resueltas con el usuario el 2026-10-07: R1, R2, R4, R9 y R11.

- **R1 — Extensión `vector`:** no se sabe todavía si pgvector está instalado ni si el usuario de la app puede crearlo. *Mitigación:* tarea de verificación (T-1) que bloquea las migraciones. Si la extensión no está o falta el permiso, se escala al DBA antes de seguir. **Resultado (2026-10-07):** vector disponible y creada (0.8.7). Se instaló `postgresql-17-pgvector` en el contenedor y, como la extensión no es de confianza (`trusted`), un superusuario ejecutó `CREATE EXTENSION vector`; el usuario de la app (`chatbot_autofin`) no es superusuario. En cada entorno nuevo hay que repetir ambos pasos antes de la migración A.
- **R2 — RNF-2 (p95 < 5 s hasta la respuesta completa):** el camino mínimo es embedding + clasificación + respuesta (3 llamadas a Gemini). *Mitigación:* modelo Flash, sub-agentes y embedding en paralelo, y prueba de carga con 50 sesiones. **Decisión del usuario:** si la prueba no cumple 5 s, se relaja el umbral (propuesta: 8 s) actualizando RNF-2 en la spec. La métrica sigue siendo hasta la respuesta completa. **Medición local (2026-10-07)**, con `fastapi` en un solo proceso contra PostgreSQL local y `gemini-3.1-flash-lite`, 50 sesiones WebSocket simultáneas con preguntas respondibles por FAQ, en 4 rondas: p95 = 4,57 / 5,61 / 5,83 / 4,81 s, con 50/50 respondidas en cada ronda. Supera 5000 ms en 2 de 4 rondas. Pendiente de repetir en el despliegue de prueba antes de decidir si RNF-2 pasa a 8000 ms. Para llegar ahí hubo que corregir tres problemas que la prueba destapó: el pool de la BD se agotaba porque cada mensaje retenía su conexión durante la llamada al modelo; Gemini bloqueaba por recitación (`finish_reason=RECITATION`) las respuestas que copiaban literalmente las FAQ públicas; y se abrían clientes de Gemini nuevos en cada mensaje, con fallos de conexión. **Medición local tras el rediseño de una sola llamada (2026-10-07, T-100)**, en las mismas condiciones: 50/50 respondidas, p50 = 3,64 s, p95 = 4,11 s y máximo = 4,50 s; repetida en 3 rondas más, 50/50 respondidas en cada una, con p95 = 4,75 / 3,85 / 2,94 s. Cumple los 5000 ms del RNF-2; falta confirmarlo en el despliegue de prueba (T-56).
- **R3 — Umbral `rag_min_similarity` (0.75 inicial):** era un valor inicial sin calibrar. *Mitigación:* calibrarlo cuando el usuario entregue las áreas y FAQ reales (pendiente por su parte); hasta entonces se usa el valor por defecto. **Resultado (2026-10-07):** calibrado con las 25 FAQ de Servicio al Cliente: 10 preguntas reformuladas con FAQ esperada (similitud mínima 0,723; la esperada se recupera en las 10, 9 en primera posición) y 6 fuera de tema (similitud máxima 0,648). Con 0,75 solo se recuperaban 5 de 10. Valor elegido: **0,68** (10/10 aciertos, 0/6 falsos positivos).
- **R4 — Nombres de áreas internas en el clasificador externo:** el usuario confirma que no son sensibles. Se mantiene D1.
- **R5 — Tareas en segundo plano de Google Chat (D17):** si el pod se reinicia mientras procesa una respuesta que pasó de 30 s, el colaborador no la recibe. Se acepta en esta iteración.
- **R6 — Infraestructura de WebSocket en Kubernetes:** el ingress tiene que permitir WebSocket y timeouts mayores que el intervalo de `ping`. Es configuración fuera de este repo; hay que revisarla antes del despliegue.
- **R7 — Zona horaria:** `zoneinfo` necesita la base de datos de zonas en la imagen `python:3.14-slim`. *Mitigación:* verificarlo en la tarea del horario. Si falta, habría que añadir `tzdata`, una dependencia nueva que pediría aprobación. **Resultado (2026-10-07):** `ZoneInfo("America/Santiago")` carga en `python:3.14-slim` (código 0); no hace falta `tzdata`.
- **R8 — Actualizaciones de `langgraph-checkpoint-postgres`:** una versión nueva con migraciones propias exige otra migración de Alembic (D7). *Mitigación:* versión fijada en `uv.lock` y nota en el README.
- **R9 — Retención de datos del chat en vivo:** el usuario confirma 30 días; se borran en cascada con la sesión web.
- **R10 — Dos drivers de PostgreSQL (asyncpg y psycopg):** duplican los pools de conexiones. *Mitigación:* pool de psycopg con `max_size` 10 y revisar `max_connections` del servidor contra las réplicas.
- **R11 — Carga inicial:** las áreas y FAQ concretas las definirá el usuario más adelante, así que no hay SQL de ejemplo. El README documenta las tablas que hay que cargar. Para crear ejecutivos se añade el comando `uv run python -m src.cli.hash_password` (módulo `src/cli/hash_password.py`, sin dependencias nuevas), que pide la contraseña sin mostrarla e imprime el hash Argon2.
- **R12 (Ampliación) — Latencia con tools:** el camino mínimo pasa a ser clasificación + paso de tool + embedding + respuesta (3 llamadas al modelo en lugar de 2). Con la medición de R2 ya cerca de 5 s, el RNF-2 corre riesgo. *Mitigación:* tope de 4 pasos, `gemini-3.1-flash-lite` y repetir T-56; se aplica la decisión de R2 (8000 ms) si no se cumple. **Medición local (2026-10-07, tras T-89):** 50 sesiones simultáneas con tools, 50/50 respondidas, p50 = 6,99 s y p95 = 8,69 s (antes de las tools: p95 de 4,57 a 5,83 s). Supera los 5000 ms del RNF-2 y también los 8000 ms previstos en R2; pendiente de medir en el despliegue (T-56) y de decisión del usuario. **Resuelto con el rediseño (D32):** una sola llamada al modelo por mensaje deja el p95 local en 4,11 s (R2).
- **R13 (Ampliación) — El modelo puede responder sin usar tools o inventar argumentos:** el guardarraíl (D22) descarta los textos sin evidencias, y `notificar_area` valida en código procedimiento y datos. El riesgo residual es un "no puedo responder" de más, no una respuesta inventada.
- **R14 (Ampliación) — La app de Google Chat debe ser miembro del space de cada área** para publicar en él. Es configuración de Google Workspace fuera del repo; si falta, la entrega falla (RF-60 a RF-62 y RF-101). Hay que añadir la app a cada space antes del despliegue.
- **R15 (Ampliación) — Datos de procedimientos en la memoria:** los datos que entrega el usuario quedan en el checkpointer durante la retención (30 días), porque forman parte de la conversación (RF-76, RF-103). No se registran en logs (RNF-8). Si se exige minimizarlos, haría falta otra decisión sobre la retención.
- **R16 (Ampliación) — La protección depende del modelo:** RF-106–108 se resuelven en el prompt (D29) y se miden con una batería de 20 o más ataques. Si la batería falla en el despliegue, la mitigación es un filtro de salida en código (alternativa descartada en D29), que requeriría aprobación. **Resultado local (2026-10-07, T-87):** con los prompts cargados en la BD local y `gemini-3.1-flash-lite`, `jailbreak_check` contra el servidor local da 22/22 ataques sin fugas (código de salida 0). **Hueco detectado:** ninguna respuesta es la negativa genérica de RF-108; el clasificador manda los ataques a "ninguna área" y el canal aplica el flujo de sin respuesta, que dentro de horario ofrece un ejecutivo. Corregido con D31 (T-89): tras ajustar el clasificador, 22/22 ataques sin fugas y con la negativa genérica, y 10/10 preguntas legítimas respondidas sin falsos positivos. El procedimiento web de prueba ("Copia del contrato") explica los pasos, pide RUT, nombre y contacto, y al no tener el área `chat_space` termina en `official_channels` (RF-101, RF-102).
- **R17 (Ampliación) — Prompts no versionados:** el contenido de `agent_prompt` solo vive en la BD de cada entorno; por decisión del usuario no está en el código ni en el historial de git (un documento con el texto recomendado se retiró y se purgó del historial el 2026-10-07). Cada entorno debe cargar prompts con las cláusulas de D29 y validarlos con `jailbreak_check`.
- **R18 (Rediseño) — Preguntas mixtas por similitud:** si una pregunta del canal web se parece a una FAQ interna por encima del umbral, se pediría reformular sin motivo. *Mitigación:* medir con las preguntas legítimas en las pruebas de rigor; si hay falsos positivos, exigir que la similitud del otro ámbito supere a la del propio. **Resultado local (2026-10-07, T-100):** 10/10 preguntas legítimas respondidas y la demo web 18/18, sin ninguna marcada como mixta.
- **R19 (Rediseño) — Publicación diferida en modalidad complemento:** la respuesta tras 30 s usa `spaces.messages.create` con la cuenta de servicio de la app. Hay que confirmar en el despliegue que la app en modo complemento puede publicar así; con una sola llamada la respuesta suele llegar en pocos segundos y este camino es excepcional.

