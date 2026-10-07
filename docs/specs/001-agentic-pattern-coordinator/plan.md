# Plan 001 — Asistente virtual con patrón agéntico coordinador

**Spec:** `docs/specs/001-agentic-pattern-coordinator/spec.md` · **Estado:** borrador (2026-10-07)
Se reutilizan la capa router → service → model, `SessionDep`, `get_property` (con su caché de 60 s), las excepciones
de `src/utils/exceptions/`, el advisory lock de `alembic/env.py` y el patrón de tests con `dependency_overrides`. Se
añaden una capa de agentes (`src/agents/`), comunicación en tiempo real (WebSocket + LISTEN/NOTIFY de PostgreSQL) y
un barrido periódico de tareas temporales.

## 1. Resumen
- **Agentes (RF-1–18):** un grafo LangGraph por ámbito (interno/externo). Un nodo clasificador elige las áreas, un sub-agente por área responde solo con las FAQ recuperadas por RAG (pgvector + embeddings de Gemini) y un nodo combina las respuestas. La estrategia del canal (patrón strategy) decide qué hacer cuando no hay respuesta.
- **Horario (RF-19–24):** función pura sobre las tablas de horario y festivos, evaluada en America/Santiago.
- **Canal web (RF-25–38, RF-76–83):** WebSocket del cliente con protocolo tipado. Una máquina de estados de la sesión (bot → oferta → datos de contacto → en cola → en vivo) y la memoria de la conversación en el checkpointer de PostgreSQL.
- **Chat en vivo (RF-39–56):** WebSocket del ejecutivo. Mensajes persistidos y repartidos entre pods con LISTEN/NOTIFY. Asignación atómica en SQL.
- **Canal interno (RF-57–69):** endpoint HTTP de Google Chat con verificación del token, respuesta síncrona o asíncrona según el límite de 30 s, y correo por SMTP.
- **Ejecutivos (RF-70–75):** login con Argon2, token opaco de sesión y bloqueo por intentos fallidos.
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
| `src/agents/llm.py` | `AgentLLM` (Protocol tipado): `classify(question, areas) -> Classification`, `answer(area, question, faqs, history) -> AreaAnswer`, `combine(parts) -> str`. `GeminiAgentLLM` lo implementa con `ChatGoogleGenerativeAI` y salida estructurada; lee `gemini_model` y `gemini_api_key` y lanza `LlmNotConfiguredError` si faltan. Los errores y timeouts de Gemini se convierten en `LlmUnavailableError` | RF-5, RF-6, RF-9, RF-12–14, RF-18 |
| `src/agents/retriever.py` | `FaqRetriever.search(area_id, question, k) -> list[FaqHit]`: calcula el embedding de la consulta (`gemini-embedding-001`, 768 dimensiones, `RETRIEVAL_QUERY`) y busca por distancia coseno filtrando por área y por `rag_min_similarity`. `refresh_stale_embeddings(area_ids)` recalcula las FAQ cuyo `content_hash` ≠ `embedded_hash` antes de buscar | RF-9, RF-11 |
| `src/agents/graph.py` | `build_graph(scope, llm, retriever, checkpointer)`. Estado: `messages`, `scope`, `candidate_areas`, `classification`, `area_answers`, `outcome`. Nodos: `load_context` (lee áreas y prompts del ámbito desde la BD en cada mensaje), `classify`, `answer_area` (fan-out con `Send`, uno por área), `combine`. `outcome` ∈ `answered` / `partial` / `no_answer` / `mixed_scope` / `wants_human` | RF-1–11 |
| `src/agents/strategies.py` | `ChannelStrategy` (Protocol): `scope`, `prompt_key` y `async on_no_answer(ctx) -> ChannelReply`. Implementaciones `ExternalStrategy` (horario → oferta de humano o canales oficiales) e `InternalStrategy` (correo al responsable o al correo general) | RF-1, RF-2, RF-25, RF-32, RF-57–61 |

### Servicios
| Módulo | Cambio | RF |
|---|---|---|
| `src/services/message_validation.py` | `validate_user_message(text) -> str`: recorta espacios exteriores y lanza `EmptyMessageError` o `MessageTooLongError` (> 5000) | RF-15–17 |
| `src/services/schedule.py` | `is_open(now, slots, holidays) -> bool` (pura; franja `[opens_at, closes_at)` en America/Santiago) y `load_schedule(session)` | RF-19–24 |
| `src/services/business_data.py` | Lectores sin caché: `get_areas(session, scope)`, `get_agent_prompt(session, key)`, `get_official_channels(session)`, `get_fallback_email(session, scope)` | RF-10, RF-11, RF-24, RF-44, RF-59, RF-62 |
| `src/services/mailer.py` | `Mailer.send(to, subject, body)` con `smtplib` en `asyncio.to_thread` y properties `smtp_*`; lanza `MailDeliveryError` | RF-58–61 |
| `src/services/google_chat.py` | `verify_chat_token(authorization)` (certificados de `chat@system.gserviceaccount.com` cacheados según `Cache-Control`, `google.auth.jwt.decode` con audiencia `google_chat_audience`); `handle_event(event)`; `ChatApiClient.create_message(space, thread, text)` (token OAuth de la cuenta de servicio vía JWT-bearer, firmado con `google.auth.crypt`, por httpx) | RF-63–69 |
| `src/services/executive_auth.py` | `login(username, password) -> SessionToken`, `authenticate(token) -> Executive`, `logout(token)`. Argon2 con comparación de tiempo constante, hash ficticio para usuarios inexistentes, contador de fallos y `locked_until` | RF-70–75 |
| `src/services/web_session.py` | Máquina de estados de la sesión web (`phase`: `bot`, `offering_human`, `collecting_contact`, `queued`, `live`). `admit(session_id)` aplica el límite de 50 bajo un advisory lock de transacción. Incluye heartbeat y `touch_last_message` | RF-25–33, RF-76–81 |
| `src/services/live_chat.py` | `enqueue`, `list_waiting`, `take(chat_id, executive_id)` (UPDATE … WHERE status='waiting' RETURNING, más el conteo de chats del ejecutivo con su fila bloqueada `FOR UPDATE`), `post_message`, `close`, `mark_executive_disconnected`, `resume`, `customer_disconnected` | RF-34–56 |
| `src/services/realtime.py` | `ConnectionHub` por pod: registro de los WebSocket de clientes y ejecutivos, y `publish(event)` → `pg_notify('chatbot_events', json)` con identificadores (nunca contenido). Listener asyncpg que reenvía cada evento al socket local que corresponda | RF-30, RF-31, RF-37, RF-43–56 |
| `src/services/sweeper.py` | `run_sweep(now)` cada 30 s, solo en el pod que obtiene `pg_try_advisory_lock`. Hace cinco cosas: cierra los chats en espera cuando termina el horario; cierra los chats asignados con el ejecutivo desconectado más de 60 min; marca como desconectados las sesiones y los ejecutivos sin heartbeat desde hace 90 s; borra las sesiones web caducadas y su hilo del checkpointer (`adelete_thread`) | RF-35–38, RF-47–53, RF-79, RF-81 |
| `src/services/chat_orchestrator.py` | Une el grafo, la estrategia y la máquina de estados: `handle_web_message(session_id, text)` y `handle_internal_message(event)`. Traduce `LlmNotConfiguredError`, `LlmUnavailableError` y `DatabaseUnavailableError` en mensajes de servicio no disponible | RF-1, RF-2, RF-7, RF-8, RF-13, RF-18, RF-26, RF-82, RF-83 |

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
| `agent_prompt` | `key` varchar(60) PK (`internal_agent`, `external_agent`, `classifier`); `content` text NOT NULL | — |
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

## 5. Decisiones
- **D1 — Un grafo por ámbito, con un clasificador que ve las áreas de ambos ámbitos solo por nombre y descripción.** Es la única forma de detectar las preguntas mixtas (RF-8). El clasificador devuelve ids, y el texto al usuario nunca sale de él. *Descartada:* un clasificador que solo ve su propio ámbito — no puede detectar las preguntas mixtas.
- **D2 — `AgentLLM` como interfaz tipada propia sobre LangChain.** Permite tests deterministas con un fake (los fakes de LangChain no soportan salida estructurada) y cumple el punto 3 de la constitución. *Descartada:* usar `ChatGoogleGenerativeAI` directamente en los nodos — no se puede probar sin red.
- **D3 — Sub-agente sin FAQ por encima de `rag_min_similarity` ⇒ `no_answer` sin llamar al LLM.** Garantiza RF-9 (no inventa nada) y ahorra latencia. *Descartada:* dejar que el LLM decida si puede responder sin FAQ — viola RF-9.
- **D4 — Embeddings recalculados de forma perezosa por `content_hash` generado en la BD.** Cumple RF-11 sin CRUD ni scripts: el responsable edita por SQL y la siguiente consulta recalcula. *Descartada:* un script de indexación manual — el cambio no se aplicaría "a partir del siguiente mensaje".
- **D5 — pgvector con 768 dimensiones e índice HNSW.** Cabe dentro del límite de 2000 dimensiones del índice y Gemini lo recomienda como equilibrio. *Descartada:* 3072 dimensiones — sin índice HNSW posible y con más almacenamiento.
- **D6 — Checkpointer `AsyncPostgresSaver` con un pool de psycopg propio, solo para el canal web.** Es el checkpointer oficial y el usuario ya lo aprobó, aunque obliga a tener un segundo driver (psycopg) junto a asyncpg. El canal interno es stateless porque la spec no le pide memoria. *Descartada:* escribir un checkpointer sobre asyncpg — demasiado código propio de mantener.
- **D7 — Tablas del checkpointer creadas por una migración de Alembic (migración D).** Respeta el punto 8 de la constitución. *Descartada:* `.setup()` en el arranque — cambia el esquema fuera de Alembic.
- **D8 — Interacción con el cliente por mensajes tipados del WebSocket** (`human_response`, `contact`). La aceptación y los datos de contacto se validan de forma determinista. La petición explícita de hablar con un humano se acepta tanto tipada (`request_human`) como en lenguaje natural, a través del clasificador. *Descartada:* interpretar "sí/no" con el LLM — es ambiguo y no se puede probar.
- **D9 — Reparto entre pods con LISTEN/NOTIFY de PostgreSQL; el payload solo lleva ids.** No añade infraestructura, y los mensajes de 5000 caracteres pueden superar el límite de 8000 bytes de NOTIFY. *Descartadas:* Redis pub/sub — infraestructura y dependencia nuevas; sticky sessions — no sirven porque el cliente y el ejecutivo son conexiones distintas.
- **D10 — Temporizadores con un barrido periódico de 30 s y advisory lock.** Sobrevive al reinicio de pods y reutiliza el patrón de `alembic/env.py`. El cierre ocurre como mucho 30 s después del plazo. *Descartada:* `asyncio` timers por chat — se pierden si el pod muere.
- **D11 — Detección de desconexiones por cierre del WebSocket más heartbeat (`last_seen_at`, umbral 90 s).** Un pod que muere no avisa del cierre de sus sockets. *Descartada:* confiar solo en el evento de cierre — dejaría sesiones "conectadas" que bloquean el límite de 50.
- **D12 — Límite de 50 contado en la BD bajo `pg_advisory_xact_lock`.** Es global entre pods y evita que dos conexiones simultáneas lo superen. *Descartada:* un contador en memoria por pod — no es global.
- **D13 — Sesión del ejecutivo con un token opaco aleatorio de 32 bytes, guardado como sha256.** Se puede revocar (logout) y no necesita otra librería. *Descartada:* JWT — exige una dependencia más y no se revoca sin tabla.
- **D14 — Login con respuesta genérica, también para cuentas bloqueadas o inexistentes, y verificación con un hash ficticio.** Cumple RF-71 y evita enumerar usuarios por tiempos de respuesta. *Descartada:* un mensaje "cuenta bloqueada" — revela que el usuario existe.
- **D15 — Google Chat como app de eventos de interacción, con audiencia = URL del endpoint.** Es el formato documentado del objeto `Event` y el más simple de validar. *Descartada:* complemento de Google Workspace — otro formato de eventos y de respuestas sin beneficio para esta spec.
- **D16 — Token de Google verificado con `google.auth.jwt.decode` y certificados cacheados por httpx; OAuth de la cuenta de servicio por JWT-bearer.** No requiere `requests` y no bloquea el event loop. *Descartada:* `google.auth.transport.requests` — añade `requests` y es síncrono.
- **D17 — Límite de 30 s con `asyncio.wait_for` (`google_chat_sync_timeout_seconds`, 25 por defecto).** Si se agota el plazo, se responde "Estoy procesando tu consulta…" y la tarea sigue en segundo plano hasta publicar con `spaces.messages.create` en el mismo hilo. *Descartada:* responder siempre de forma asíncrona — es más lento y obliga a usar credenciales en todos los mensajes.
- **D18 — Correo con `smtplib` en `asyncio.to_thread`.** No añade dependencias. *Descartada:* `aiosmtplib` — una dependencia nueva para pocos correos.
- **D19 — Datos de negocio leídos sin caché en cada mensaje; las properties mantienen la caché de 60 s.** RF-11 exige aplicar los cambios de prompts y FAQ al siguiente mensaje, y las properties son configuración técnica. *Descartada:* una caché con TTL para los prompts — viola RF-11.
- **D20 — Lógica de dominio pura separada del SQL; el reloj se inyecta con `Clock`.** Permite probar plazos y concurrencia sin BD ni esperas (punto 6 de la constitución y criterio de finalización). *Descartada:* un repositorio con tests contra la BD — prohibido por la constitución.

**Properties nuevas** (las que tienen valor por defecto lo traen en el código):
- **Obligatorias:**
  - `gemini_model`, `gemini_api_key`, `gemini_embedding_model` (`gemini-embedding-001`).
  - `google_chat_audience` (URL pública del endpoint) y `google_chat_service_account_json`.
  - `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_starttls`.
- **Con valor por defecto:**
  - **RAG y LLM:** `rag_top_k` (4), `rag_min_similarity` (0.75), `llm_timeout_seconds` (20).
  - **Sesiones web:** `web_session_retention_days` (30), `web_max_sessions` (50).
  - **Ejecutivos:** `executive_max_chats` (3), `executive_session_hours` (8), `login_max_attempts` (5), `login_lock_minutes` (15), `executive_reconnect_minutes` (60).
  - **Google Chat:** `google_chat_sync_timeout_seconds` (25).

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

## 8. Matriz de cobertura
| RF | Módulos | Tests |
|---|---|---|
| RF-1, RF-2 | `strategies`, `chat_orchestrator`, `routers/google_chat`, `routers/web_chat` | `agent_graph_test`, `google_chat_test`, `web_chat_ws_test` |
| RF-3, RF-4 | `graph` (`load_context` por ámbito), `business_data` | `agent_graph_test` (RNF-3) |
| RF-5, RF-6, RF-7 | `graph` (`classify`, `answer_area`, `combine`), `llm` | `agent_graph_test` |
| RF-8 | `graph` (`classify` → `mixed_scope`), `chat_orchestrator` | `agent_graph_test` |
| RF-9 | `retriever`, `graph` (D3) | `agent_graph_test` |
| RF-10, RF-11 | `business_data` (sin caché), `retriever.refresh_stale_embeddings` | `agent_graph_test` |
| RF-12, RF-13, RF-14 | `llm`, `property` helpers, `chat_orchestrator` | `agent_graph_test` (caplog sin API key) |
| RF-15, RF-16, RF-17 | `message_validation`, routers web y Google Chat | `message_validation_test`, `web_chat_ws_test` |
| RF-18 | `llm`, `chat_orchestrator` | `agent_graph_test`, `web_chat_ws_test` |
| RF-19–RF-23 | `schedule` | `schedule_test` |
| RF-24 | `business_data.get_official_channels` | `channel_strategy_test` |
| RF-25, RF-26 | `strategies.ExternalStrategy`, `graph` (`wants_human`), `web_session` | `channel_strategy_test`, `web_chat_ws_test` |
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
| RF-57–RF-62 | `strategies.InternalStrategy`, `mailer`, `business_data` | `channel_strategy_test`, `google_chat_test` |
| RF-63, RF-64 | `google_chat.verify_chat_token` | `google_chat_test` |
| RF-65, RF-66, RF-67 | `google_chat.handle_event` | `google_chat_test` |
| RF-68, RF-69 | `google_chat` (D17), `ChatApiClient` | `google_chat_test` |
| RF-70–RF-73 | `executive_auth`, `routers/executive` | `executive_auth_test`, `executive_api_test` |
| RF-74, RF-75 | `routers/live_chat`, `routers/executive`, `executive_auth.authenticate` | `executive_api_test`, `executive_ws_test` |
| RF-76, RF-77, RF-78 | checkpointer (thread = `web_session.id`), `graph` | `agent_graph_test` (InMemorySaver, dos hilos aislados), `web_chat_ws_test` |
| RF-79, RF-80 | `sweeper`, `web_session` | `sweeper_test`, `web_chat_ws_test` |
| RF-81 | `web_session.admit` (D12) | `web_chat_ws_test` |
| RF-82, RF-83 | `routers/web_chat`, `chat_orchestrator` | `web_chat_ws_test` |

## 9. Riesgos y dudas
Dudas resueltas con el usuario el 2026-10-07: R1, R2, R4, R9 y R11.

- **R1 — Extensión `vector`:** no se sabe todavía si pgvector está instalado ni si el usuario de la app puede crearlo. *Mitigación:* tarea de verificación (T-1) que bloquea las migraciones. Si la extensión no está o falta el permiso, se escala al DBA antes de seguir.
- **R2 — RNF-2 (p95 < 5 s hasta la respuesta completa):** el camino mínimo es embedding + clasificación + respuesta (3 llamadas a Gemini). *Mitigación:* modelo Flash, sub-agentes y embedding en paralelo, y prueba de carga con 50 sesiones. **Decisión del usuario:** si la prueba no cumple 5 s, se relaja el umbral (propuesta: 8 s) actualizando RNF-2 en la spec. La métrica sigue siendo hasta la respuesta completa.
- **R3 — Umbral `rag_min_similarity` (0.75):** es un valor inicial sin calibrar. *Mitigación:* calibrarlo cuando el usuario entregue las áreas y FAQ reales (pendiente por su parte); hasta entonces se usa el valor por defecto.
- **R4 — Nombres de áreas internas en el clasificador externo:** el usuario confirma que no son sensibles. Se mantiene D1.
- **R5 — Tareas en segundo plano de Google Chat (D17):** si el pod se reinicia mientras procesa una respuesta que pasó de 30 s, el colaborador no la recibe. Se acepta en esta iteración.
- **R6 — Infraestructura de WebSocket en Kubernetes:** el ingress tiene que permitir WebSocket y timeouts mayores que el intervalo de `ping`. Es configuración fuera de este repo; hay que revisarla antes del despliegue.
- **R7 — Zona horaria:** `zoneinfo` necesita la base de datos de zonas en la imagen `python:3.14-slim`. *Mitigación:* verificarlo en la tarea del horario. Si falta, habría que añadir `tzdata`, una dependencia nueva que pediría aprobación.
- **R8 — Actualizaciones de `langgraph-checkpoint-postgres`:** una versión nueva con migraciones propias exige otra migración de Alembic (D7). *Mitigación:* versión fijada en `uv.lock` y nota en el README.
- **R9 — Retención de datos del chat en vivo:** el usuario confirma 30 días; se borran en cascada con la sesión web.
- **R10 — Dos drivers de PostgreSQL (asyncpg y psycopg):** duplican los pools de conexiones. *Mitigación:* pool de psycopg con `max_size` 10 y revisar `max_connections` del servidor contra las réplicas.
- **R11 — Carga inicial:** las áreas y FAQ concretas las definirá el usuario más adelante, así que no hay SQL de ejemplo. El README documenta las tablas que hay que cargar. Para crear ejecutivos se añade el comando `uv run python -m src.cli.hash_password` (módulo `src/cli/hash_password.py`, sin dependencias nuevas), que pide la contraseña sin mostrarla e imprime el hash Argon2.
