# Plan 001 — Asistente virtual con agentes por canal y sub-agentes por área (2.0.0)

Spec: [spec.md](spec.md). Rama `release/2.0.0`, que parte del tag 1.0.0: `/health`, la tabla `property` con caché de
60 s (que este plan elimina, D18), `SessionDep`, `DatabaseUnavailableError` y `PropertyNotFoundError`. Este plan no
incluye código, solo la estructura, los contratos y las decisiones.

## 1. Arquitectura

```
Cliente ── POST /api/v1/chat ──────────────┐                         ┌── Sub-agente área A ─┐
                                            ├─ assistant ─ grafo ─────┤        (paralelo)   ├─ redactar ─ respuesta
Colaborador ── POST /api/v1/google-chat ───┘   (servicio) (coordinador) └── Sub-agente área B ─┘
                                                 │                │
                                    conversation (historial)   knowledge (áreas, prompts, FAQ + pgvector)
```

Cada mensaje sigue el patrón coordinador de la spec, con un solo nivel:

1. **`route`**: el coordinador hace 1 llamada al modelo. Analiza la consulta con el historial y el catálogo de su
   canal, y decide si responde él directamente (saludo, tema ajeno, «qué puedo consultar») o divide la consulta en
   subtareas por área.
2. **`retrieve`** (sin modelo): genera en un solo lote los embeddings de las subtareas, sincroniza los embeddings
   pendientes de las áreas elegidas y busca las FAQ de cada área.
3. **`sub_agent`**: N sub-agentes en paralelo (`Send` de LangGraph). Cada uno hace 1 llamada, o hasta
   `sub_agent_max_steps` si su área tiene herramientas.
4. **`synthesize`**: el coordinador hace 1 llamada más para redactar la respuesta con los resultados.

Respuesta directa: 1 llamada. Consulta a las áreas: 2 + N llamadas (RNF-6).

## 2. Módulos

Siguen las capas de la constitución (punto 2): routers → services → models; agentes en `src/agents/` con interfaces
tipadas (punto 3).

| Archivo | Responsabilidad | RF |
|---|---|---|
| `src/routers/web_chat.py` | `POST /api/v1/chat`: valida el cuerpo, llama a `assistant.answer` y traduce `DatabaseUnavailableError` a 503 | RF-1, RF-18, RF-34 |
| `src/routers/google_chat.py` | `POST /api/v1/google-chat/events`: verifica el token, convierte el evento y responde con el formato del complemento de Workspace | RF-2, RF-34, RF-35, RF-36, RF-37 |
| `src/interfaces/web_chat.py` | `ChatRequest {session_id: UUID \| None, message: str}` y `ChatResponse {session_id: UUID, reply: str}` | RF-18 |
| `src/interfaces/google_chat.py` | Modelos Pydantic del evento del complemento (mensaje, `argumentText`, space, hilo, `addedToSpacePayload`) y de su respuesta | RF-36, RF-37 |
| `src/services/assistant.py` | Orquesta un mensaje: validar → `load_properties` (una consulta) → conversación e historial → catálogo → grafo con `asyncio.timeout` → guardar el turno. Traduce los fallos del modelo y la configuración faltante al mensaje de servicio no disponible | RF-1, RF-2, RF-19, RF-23, RF-25, RF-26, RF-33 |
| `src/services/message_validation.py` | Mensaje vacío (RF-31) o de más de 5000 caracteres (RF-32), con los textos fijos para el usuario | RF-31, RF-32 |
| `src/services/conversation.py` | Obtener o crear la conversación (web por `session_id`, Chat por clave de hilo), últimos N mensajes, agregar un turno, borrar las expiradas | RF-18, RF-19, RF-20, RF-21 |
| `src/services/knowledge.py` | Leer en cada mensaje las áreas, las categorías, los prompts (`agent_prompt` y `system_prompt`) y las herramientas, y armar el catálogo del canal con la función pura `build_catalog` (filtra por canal y `active`); buscar FAQ por área (pgvector); sincronizar los embeddings pendientes, que elige la función pura `pending_faqs` | RF-3, RF-4, RF-8, RF-16, RF-22, RF-23, RF-24, RNF-2 |
| `src/services/google_chat.py` | Verificar el ID token (emisor de Google, audiencia y cuenta de servicio del complemento), calcular la clave de la conversación (hilo en un space, space en un DM) y leer el texto (`argumentText` en spaces) | RF-35, RF-36 |
| `src/services/property.py` (cambia) | **Se elimina la caché**: desaparecen `_cache`, `_loaded_at` y `CACHE_TTL_SECONDS`. `get_property(session, key)` hace un `SELECT` por clave en cada llamada (lo sigue usando `/health`). Nuevo `load_properties(session) -> Properties`: una sola consulta trae todas las properties como foto inmutable del mensaje, con getters tipados `required(key)` y `get_int(key, default)`. Los errores de BD siguen siendo `DatabaseUnavailableError` | RF-23, RF-25, RF-26 |
| `src/services/retention.py` | Tarea del `lifespan` que cada hora lee `conversation_retention_days` (sin caché) y borra las conversaciones sin mensajes desde hace esos días | RF-21, RF-23 |
| `src/agents/llm.py` | Interfaces tipadas (`Protocol`): `CoordinatorModel` (`route`, `synthesize`), `SubAgentModel`, `Embedder`; dataclasses `Catalog`, `AreaInfo`, `Subtask`, `FaqHit`, `AreaResult` | RF-5, RF-12 (contratos) |
| `src/agents/gemini.py` | Implementación con `langchain-google-genai`: salida estructurada para `route`, *tool calling* para el sub-agente, texto para `synthesize`, embeddings con dimensión fija; convierte cualquier error del proveedor en `LlmUnavailableError` | RF-25, RF-33 |
| `src/agents/prompts.py` | Arma los mensajes de cada paso: prompt del coordinador del canal + catálogo; reglas comunes + prompt del área + FAQ marcadas como información; resultados marcados como información para `synthesize` | RF-16, RF-22, RF-38, RF-39 |
| `src/agents/coordinator.py` | Nodos `route` y `synthesize`. `route` sanea la decisión: descarta `area_id` ajenos al canal o inactivos, quita duplicados y aplica `max_areas_per_message` | RF-3, RF-5, RF-6, RF-12, RF-13, RF-14, RF-16, RF-17, RF-40 |
| `src/agents/sub_agent.py` | Especialista de un área: recibe solo `Subtask` + sus FAQ + sus herramientas y termina con la herramienta `responder(encontrado, contenido)`; un fallo o *timeout* devuelve `AreaResult(found=False)` | RF-8, RF-9, RF-10, RF-11, RF-15, RF-28, RF-30 |
| `src/agents/graph.py` | `StateGraph`: `route` → (`END` si es directa) → `retrieve` → `Send` a `sub_agent` × N → `synthesize`; estado con *reducer* de lista para los resultados | RF-5, RF-6, RF-7, RF-11, RF-12 |
| `src/agents/tools.py` | Registro `TOOLS: dict[str, AreaTool]` (nombre, descripción, esquema Pydantic, `async run`) y `tools_for(area)`, que ignora los nombres desconocidos con un *warning*; sin herramientas concretas | RF-27, RF-28, RF-29 |
| `src/models/*.py` | ORM de la sección 3 | RF-4, RF-8, RF-18, RF-22, RF-24 |
| `src/utils/exceptions/llm.py` | `LlmUnavailableError` | RF-33 |
| `src/utils/exceptions/google_chat.py` | `InvalidGoogleTokenError` | RF-35 |
| `main.py` | Registra los routers nuevos y arranca o detiene la tarea de retención en el `lifespan` | RF-21 |

## 3. Modelo de datos

Una migración nueva, `create_assistant_tables`, sobre `3cedeabf6f74`, revisada a mano (constitución, punto 8). Se aplica
en la base nueva de la 2.0.0 (RNF-5) y requiere la extensión `vector` en el servidor.

```
business_area                          faq_category                      faq
─────────────                          ────────────                      ───
id            int PK                   id        int PK                  id             int PK
name          varchar(120) UNIQUE      area_id   FK → business_area      category_id    FK → faq_category (CASCADE), idx
description   text                               (CASCADE), idx          question       text
scope         area_scope               name      varchar(120)            answer         text
              (internal|external)      UNIQUE (area_id, name)            active         bool = true
system_prompt text                                                       content_hash   text GENERATED md5(question‖'\n'‖answer) STORED
tools         text[] = '{}'                                              embedded_hash  text NULL
active        bool = true                                                embedding      vector(768) NULL

agent_prompt                 conversation                                message
────────────                 ────────────                                ───────
key      varchar(60) PK      id               uuid PK                    id               bigint PK
content  text                channel          channel (web|google_chat)  conversation_id  FK → conversation (CASCADE)
                             external_key     varchar(255) UNIQUE NULL   role             message_role (user|assistant)
                             last_message_at  timestamptz, idx           content          text
                             created_at       timestamptz = now()        created_at       timestamptz = now()
                                                                         idx (conversation_id, id)
```

| Tabla | Para qué | RF |
|---|---|---|
| `business_area` | Un sub-agente por fila activa; `scope` separa los canales; `tools` asigna herramientas del registro | RF-3, RF-4, RF-22, RF-28 |
| `faq_category` | Agrupa las FAQ y alimenta el catálogo de «qué puedo consultar» | RF-16 |
| `faq` | Contenido del RAG. Una FAQ está pendiente de embedding cuando `embedded_hash` es distinto de `content_hash` | RF-8, RF-24 |
| `agent_prompt` | Claves `external_coordinator`, `internal_coordinator`, `sub_agent_rules` e `internal_welcome` | RF-22, RF-37 |
| `conversation` | Sesión web (`id` = `session_id`) o conversación de Chat (`external_key` = hilo o DM) | RF-18, RF-20, RF-21 |
| `message` | Solo el mensaje del usuario y la respuesta final; las subtareas no se guardan | RF-19 |

La migración también siembra las properties no secretas con sus valores por defecto (sección 5) y los prompts iniciales
(D9). Las API keys y la cuenta de servicio se cargan a mano, según SECURITY.md.

## 4. Contratos

**Chat web.** `POST /api/v1/chat`
- Petición: `{"session_id": "uuid | null", "message": "texto"}`.
- `200`: `{"session_id": "uuid", "reply": "texto"}`. Cuando la sesión no existe o no viene, se crea una y se devuelve
  su id (RF-18). Las respuestas por mensaje vacío, mensaje largo o modelo caído también son `200`, con el texto en
  `reply` (RF-31, RF-32, RF-33).
- `503`: `{"detail": "Servicio no disponible"}` si la base de datos no responde (RF-34).
- `422`: solo si el JSON está mal formado. El largo del mensaje no lo valida Pydantic, para poder responder RF-32 con
  un texto.

**Google Chat.** `POST /api/v1/google-chat/events`, con el formato de evento y respuesta del complemento de Workspace
que ya funciona en la 1.x.
- `Authorization: Bearer <ID token>`. Si el token no es válido, no es de Google o no es de la cuenta de servicio del
  complemento, responde `401` (RF-35).
- Mensaje → la respuesta síncrona va en `createMessageAction`, y Chat la publica en el hilo del mensaje (RF-36).
  Clave de conversación: el hilo en un space y el space en un mensaje directo, porque en un DM cada mensaje abre un
  hilo nuevo.
- Agregado a un space o DM → responde el texto de `internal_welcome`, sin llamar al modelo (RF-37).

## 5. Properties

| Key | Uso | Por defecto | RF |
|---|---|---|---|
| `gemini_api_key` | API key (secreta, se carga a mano) | — (obligatoria) | RF-25, RF-26 |
| `coordinator_model` | Modelo de `route` y `synthesize` | — (obligatoria) | RF-25, RF-26 |
| `sub_agent_model` | Modelo de los sub-agentes | — (obligatoria) | RF-25, RF-26 |
| `embedding_model` | Modelo de embeddings (salida de 768 dimensiones) | — (obligatoria) | RF-24, RF-25 |
| `max_areas_per_message` | Tope de subtareas por mensaje | `3` | RF-6 |
| `faqs_per_search` | FAQ por subtarea | `5` | RF-8 |
| `history_messages` | Mensajes de contexto para el coordinador | `10` | RF-19 |
| `conversation_retention_days` | Días sin mensajes antes de borrar la conversación | `30` | RF-21 |
| `response_timeout_seconds` | Tiempo máximo del grafo completo; debe ser menor que 30 | `20` | RF-33, RNF-1 |
| `sub_agent_timeout_seconds` | Tiempo máximo de cada sub-agente; si se excede, la subtarea queda sin información | `6` | RF-15, RNF-1 |
| `sub_agent_max_steps` | Llamadas de un sub-agente con herramientas antes de forzar `responder` | `3` | RF-28, RNF-6 |
| `google_chat_audience` | URL pública del endpoint de eventos | — | RF-35 |
| `google_chat_addon_service_account` | Cuenta de servicio que firma los eventos | — | RF-35 |

Sin caché (D18): cada mensaje lee todas las properties con una sola consulta (`load_properties`) y usa esa foto en
todos sus pasos. Un cambio en la tabla se aplica desde el siguiente mensaje (RF-23). El verificador de Google Chat y
la tarea de retención también leen en cada uso.

## 6. Decisiones

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| D1 | **Grafo explícito de LangGraph** (`route` → `retrieve` → `Send` → `synthesize`) | Coordinador ReAct que llama a los sub-agentes como herramientas, o `langgraph-supervisor` | Con un grafo fijo el número de llamadas es 2 + N (RNF-6) y la latencia está acotada (RNF-1). En un bucle ReAct el modelo decide cuántas vueltas da, y `langgraph-supervisor` es otra dependencia más. El patrón se cumple igual, porque el enrutamiento lo decide el modelo en `route` |
| D2 | **LangGraph** como orquestador | `asyncio.gather` en código propio, sin LangGraph | Lo pide el diagrama. Además `Send` resuelve el paralelo (RF-7) y deja el camino abierto a MCP y a varios niveles más adelante. Con código propio sería más corto hoy, pero habría que rehacerlo al crecer |
| D3 | **`route` decide y responde en la misma llamada**: salida estructurada `{tipo: areas\|directa, subtareas: [{area_id, consulta}], respuesta}`, con el catálogo (áreas y categorías del canal) en su prompt | Un clasificador y después otra llamada para responder | El saludo, el tema ajeno y «qué puedo consultar» cuestan 1 llamada (RNF-6, RF-16, RF-17). El catálogo ya es necesario para enrutar, así que no cuesta nada extra |
| D4 | **El código sanea la decisión de `route`**: solo `area_id` activos del canal, sin duplicados y con tope | Confiar en lo que devuelve el modelo | Un id inventado o de otro canal nunca llega a un sub-agente (RF-3, RF-6, RF-40). Esto se puede probar sin el modelo |
| D5 | **Aislamiento estructural entre canales**: el grafo externo nunca carga áreas, FAQ ni prompts internos | Un auditor de la respuesta que busque nombres internos, como en la 1.x | Lo que no entra al contexto no puede filtrarse (RF-40). El auditor de la 1.x dio falsos positivos (fix del 2026-10-09 sobre los 50 caracteres) y suma complejidad |
| D6 | **Recuperación en el código** (nodo `retrieve`, un solo lote de embeddings y búsquedas secuenciales en la sesión de la petición) antes del fan-out | Búsqueda como herramienta de cada sub-agente, o una sesión por sub-agente | Ahorra una vuelta al modelo por área (RNF-1). Además, `AsyncSession` no admite consultas concurrentes, así que con N sub-agentes en paralelo cada uno necesitaría su propia sesión. Los sub-agentes quedan como funciones puras de LLM, fáciles de probar |
| D7 | **El sub-agente termina con la herramienta `responder(encontrado, contenido)`** (*tool choice* obligatorio) | Texto libre con una marca de «sin información», o una llamada extra de salida estructurada | El mismo mecanismo sirve con y sin herramientas, y `encontrado` le da a `synthesize` una señal fiable para RF-10, RF-13 y RF-14 sin gastar una llamada más |
| D8 | **Historial en tablas propias** (`conversation`, `message`) | Checkpointer `langgraph-checkpoint-postgres` | Evita `psycopg` (el stack es asyncpg) y tablas fuera de Alembic con blobs opacos (37 mil filas en la 1.x). La retención es un `DELETE` simple (RF-21) |
| D9 | **Prompts iniciales sembrados por la migración** y editables en la BD | Prompts solo en la BD, sin versionar (1.x) | La base nueva (RNF-5) queda funcional y reproducible desde `alembic upgrade head`. Las ediciones posteriores viven en la BD (RF-22, RF-23) |
| D10 | **Embeddings sincronizados al buscar**, solo en las áreas enrutadas (hash del contenido frente a `embedded_hash`) | Tarea periódica, CLI manual o trigger en la BD | Garantiza RF-24 («antes de usarla») sin pasos manuales. Una tarea periódica deja una ventana con la FAQ vieja, y un trigger no puede llamar a Gemini. El primer mensaje después de una edición paga unos 300 ms |
| D11 | **Sin índice vectorial** (búsqueda exacta por coseno, filtrada por área) | HNSW | Con cientos de FAQ la búsqueda exacta tarda milisegundos. HNSW con filtro por área puede omitir resultados. Se revisa si pasan de unas 10 mil |
| D12 | **Google Chat síncrono** con `response_timeout_seconds` < 30 | Respuesta diferida con la API de Chat, como en la 1.x | RNF-1 exige 10 s, así que no hace falta diferir. La respuesta diferida necesita el JSON de una cuenta de servicio con `chat.bot` y un cliente más |
| D13 | **Bienvenida fija** (`internal_welcome`) al agregar el asistente | Generarla con el modelo, como en la 1.x | 0 llamadas, siempre igual y editable por el responsable de contenidos (RF-37) |
| D14 | **Fallos del modelo con `200` y texto en `reply`**; solo la BD responde `503` | `503` también cuando falla el modelo | El front solo muestra `reply`, y la constitución (punto 9) reserva el 503 para la BD |
| D15 | **Retención como tarea del `lifespan`** cada hora | `CronJob` de Kubernetes, o limpiar en cada mensaje | Sin manifiestos ni cambios de CI (que requieren aprobación) y sin sumar latencia al mensaje. Con varias réplicas el `DELETE` es idempotente |
| D16 | **`langchain-google-genai`** | SDK `google-genai` directo | LangGraph ya trae `langchain-core`, y el wrapper da salida estructurada, *tool calling* y embeddings con una sola interfaz |
| D17 | **Sin razonamiento extendido**: *thinking budget* 0 en `route` y en los sub-agentes, como constante en el código | Dejar el valor por defecto del modelo | El razonamiento suma segundos por llamada, y en el peor caso hay tres pasos seguidos (RNF-1) |
| D18 | **Sin caché de `property`**: una consulta por mensaje que trae todas las claves (`load_properties`) | Mantener la caché de 60 s de la 1.0.0, o invalidarla con `LISTEN/NOTIFY` | Con caché, un cambio tarda hasta 60 s y cada réplica de Kubernetes ve un valor distinto durante ese tiempo, lo que contradice RF-23. `LISTEN/NOTIFY` agrega una conexión dedicada y triggers. Una consulta sobre una tabla de unas 20 filas cuesta alrededor de 1 ms, y leer una sola foto evita que un mensaje mezcle valores viejos y nuevos a mitad del grafo |

## 7. Presupuesto de latencia (RNF-1, p95 ≤ 10 s)

| Paso | Estimado |
|---|---|
| Carga de properties (1 consulta), conversación, catálogo y prompts (BD) | ≤ 0,2 s |
| `route` (salida estructurada, sin *thinking*) | 1,5–2,5 s |
| `retrieve` (un lote de embeddings y N búsquedas) | 0,3–0,5 s |
| `sub_agent` × N en paralelo (tope de `sub_agent_timeout_seconds` = 6 s) | 1,5–3 s |
| `synthesize` | 1,5–3 s |
| **Total** | **≈ 5–9 s** |

`assistant.py` registra la duración de cada paso en el log, sin el texto del mensaje (RNF-3), para medir el p95 en la
demo.

## 8. Dependencias que requieren aprobación (constitución, punto 1)

| Paquete | Para qué |
|---|---|
| `langgraph` | Grafo del coordinador y `Send` (D1, D2) |
| `langchain-google-genai` | Gemini: chat, salida estructurada, herramientas y embeddings (D16) |
| `pgvector` | Tipo `Vector` de SQLAlchemy y búsqueda por coseno |
| `google-auth` | Verificación del ID token de Google Chat (RF-35) |

`httpx`, para descargar los certificados de Google, ya viene con `fastapi[standard]`. No hacen falta dependencias de
desarrollo nuevas.

## 9. Estrategia de tests

Reglas: archivos `*_test.py` en `tests/`, sin BD, sin Google y sin Gemini (constitución, punto 6, y RNF-4).

**Dobles** (`tests/fakes.py`):
- `FakeCoordinatorModel` / `FakeSubAgentModel` / `FakeEmbedder`: respuestas guionadas, registran cada llamada con sus
  mensajes, y pueden fallar o demorarse a propósito.
- `FakeKnowledge` / `FakeConversationStore`: en memoria, implementan los mismos `Protocol` que los servicios con SQL.
- Para los routers: `app.dependency_overrides[get_session]` y overrides del verificador de token y del servicio
  `assistant`.

**Qué no cubren los tests unitarios:** el SQL de `knowledge.py` y `conversation.py`, y el comportamiento real de Gemini
frente a manipulaciones. Se verifican con `alembic upgrade head` en la base nueva y con la demo manual de los criterios
de finalización. Las funciones puras que usan esos módulos (cálculo de la fecha de corte, clave de conversación,
armado de prompts) sí tienen test.

| Archivo de test | Qué verifica | RF / RNF |
|---|---|---|
| `message_validation_test.py` | Vacío, solo espacios, 5000 y 5001 caracteres; sin llamar al modelo | RF-31, RF-32 |
| `coordinator_test.py` | El saneamiento descarta ids de otro canal, inactivos e inventados; quita duplicados y aplica el tope; la respuesta directa no crea subtareas; el catálogo del prompt solo tiene áreas y categorías del canal; `synthesize` recibe los resultados con `found` | RF-3, RF-5, RF-6, RF-12, RF-13, RF-14, RF-16, RF-17, RF-40 |
| `sub_agent_test.py` | Recibe solo su subtarea, su prompt y sus FAQ, sin historial; `responder(encontrado=False)` produce `found=False`; una herramienta que falla devuelve un aviso genérico al modelo; tope de pasos; *timeout* y excepción dan `found=False` | RF-8, RF-9, RF-10, RF-11, RF-15, RF-30, RNF-7 |
| `tools_test.py` | `tools_for` entrega solo las herramientas asignadas; un nombre desconocido se ignora con un *warning* (`caplog`) | RF-27, RF-28, RF-29 |
| `graph_test.py` | Canal externo con áreas externas e interno con internas; un área nueva en el catálogo falso funciona sin código; dos subtareas corren en paralelo (dos sub-agentes que se esperan mutuamente con `asyncio.Event` terminan); un sub-agente caído no impide la respuesta; conteo de llamadas: 1 para directa y 2 + N para áreas | RF-1, RF-2, RF-4, RF-7, RF-11, RF-12, RF-15, RNF-2, RNF-6 |
| `prompts_test.py` | Los prompts salen del catálogo cargado de la BD; el texto del usuario, las FAQ y los resultados van marcados como información y nunca dentro de las instrucciones | RF-22, RF-38, RF-39 |
| `assistant_test.py` | Sesión inexistente crea una nueva; el historial se limita a N y no mezcla conversaciones; un cambio en el catálogo falso entre dos mensajes se aplica en el segundo; la sincronización de embeddings ocurre antes de buscar; falta de modelo o API key da servicio no disponible y un log sin el valor de la key; error o *timeout* del modelo da servicio no disponible; `caplog` sin el texto del usuario | RF-18, RF-19, RF-20, RF-23, RF-24, RF-25, RF-26, RF-33, RNF-3 |
| `property_test.py` | Con una sesión falsa que cuenta las ejecuciones: dos llamadas a `get_property` hacen dos consultas y la segunda ve el valor cambiado (sin caché); `load_properties` hace una sola consulta; `required` lanza `PropertyNotFoundError`; `get_int` usa el valor por defecto si falta o no es entero; un error de la sesión da `DatabaseUnavailableError` | RF-23, RF-25, RF-26 |
| `knowledge_test.py` | `build_catalog` excluye las áreas de otro canal y las inactivas y agrupa las categorías; `pending_faqs` elige solo las FAQ nuevas o editadas y las re-embebe en un lote | RF-3, RF-4, RF-16, RF-24, RNF-2 |
| `gemini_test.py` | Con un `BaseChatModel` de prueba: los errores del proveedor se convierten en `LlmUnavailableError`, se parsea `RoutingDecision` y se extrae la llamada a `responder` | RF-25, RF-33 |
| `retention_test.py` | La fecha de corte sale de `conversation_retention_days`; la tarea llama a borrar con ese corte y sobrevive a un error de BD | RF-21 |
| `web_chat_test.py` | Contrato de `POST /api/v1/chat` (con y sin `session_id`); `DatabaseUnavailableError` da `503`; un mensaje largo da `200` con aviso | RF-1, RF-18, RF-32, RF-34 |
| `google_chat_test.py` | Sin token, con emisor o cuenta ajenos da `401`; la clave es el hilo en un space y el space en un DM; en un space se usa `argumentText`; agregar al space devuelve la bienvenida sin modelo; la respuesta tiene el formato del complemento | RF-2, RF-35, RF-36, RF-37 |
| `health_test.py` (existente) | Sin cambios | — |

RNF-1 (latencia) no se puede probar con dobles. Se mide en la demo con los tiempos por paso del log.

## 10. Riesgos

- **Latencia en el límite:** si el p95 de la demo supera 10 s, se ajusta primero sin código: un modelo más rápido para
  `route` y los sub-agentes, menos `faqs_per_search` y menos `history_messages`.
- **Extensión `vector`:** la base nueva necesita `CREATE EXTENSION vector`, que puede requerir un usuario con
  privilegios en el servidor.
- **Dimensión del embedding fija (768):** cambiar a un modelo con otra dimensión requiere una migración y recalcular
  todas las FAQ.
- **Manipulación del modelo (RF-38, RF-39):** los tests solo verifican que la entrada no confiable va marcada. El
  rechazo real depende de los prompts y se revisa en la demo.
