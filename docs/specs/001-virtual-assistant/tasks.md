# Tareas 001 — Asistente virtual con agentes por canal y sub-agentes por área (2.0.0)

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 30/30 hechas
Cada tarea dura menos de 30 min y deja los tests en verde. Se hacen en orden; `[P]` indica que puede ir en paralelo con
la anterior. "Verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test se conecta a la
BD, a Google ni a Gemini (constitución, punto 6): se usan los dobles de `tests/fakes.py` y
`app.dependency_overrides`.

## Fase 1 — Base
- [x] **T-1 — Agregar las dependencias aprobadas** · (habilita RF-1 a RF-40) · ~10 min
  `uv add langgraph langchain-google-genai pgvector google-auth`. Requiere la aprobación de la sección 8 del plan.
  Hecho cuando: `uv run python -c "import langgraph, langchain_google_genai, pgvector, google.auth"` termina con 0 y la
  suite sigue verde.
- [x] **T-2 — Quitar la caché de `property`** · RF-23, RF-25, RF-26 · ~25 min [P]
  En `src/services/property.py`: quitar `_cache`, `_loaded_at` y `CACHE_TTL_SECONDS`. `get_property` pasa a hacer un
  `SELECT` por clave, y se agregan `load_properties(session) -> Properties` con `required(key)` y
  `get_int(key, default)` (D18).
  Hecho cuando: `uv run pytest -q tests/property_test.py` pasa (dos llamadas hacen dos consultas y la segunda ve el
  valor cambiado; `load_properties` hace una sola consulta; clave faltante; valor no entero; BD caída) y
  `grep -n "_cache\|CACHE_TTL" src/services/property.py` no devuelve nada.

## Fase 2 — Modelo de datos
- [x] **T-3 — Crear los modelos de contenido** · RF-3, RF-4, RF-8, RF-16, RF-22, RF-24, RF-28 · ~25 min
  En `src/models/`: `BusinessArea` (enum `AreaScope`, `tools text[]`, `active`), `FaqCategory`, `Faq` (`content_hash`
  generado, `embedded_hash` y `embedding Vector(768)`) y `AgentPrompt`. La constante `EMBEDDING_DIMENSIONS = 768`.
  Hecho cuando: `uv run pyright` da 0 errores y
  `uv run python -c "import src.models.business_area, src.models.faq_category, src.models.faq, src.models.agent_prompt"`
  termina con 0.
- [x] **T-4 — Crear los modelos de conversación** · RF-18, RF-19, RF-20, RF-21 · ~15 min [P]
  `Conversation` (enum `Channel`, `external_key` único, `last_message_at` indexado) y `Message` (enum `MessageRole`,
  índice `(conversation_id, id)`, `CASCADE`).
  Hecho cuando: `uv run pyright` da 0 errores y
  `uv run python -c "import src.models.conversation, src.models.message"` termina con 0.
- [x] **T-5 — Crear la migración del esquema** · RF-3, RF-4, RF-8, RF-18, RF-22, RF-24 · ~25 min (depende de T-3 y T-4)
  `uv run alembic revision --autogenerate -m "create assistant tables"`, revisada a mano: `CREATE EXTENSION IF NOT
  EXISTS vector`, los enums, la columna generada `content_hash`, los índices y `server_default` de `tools` y `active`.
  En el `downgrade` se borran las tablas y los enums, pero no la extensión.
  Hecho cuando: contra una BD local vacía, `uv run alembic upgrade head`, `uv run alembic downgrade -1` y otra vez
  `uv run alembic upgrade head` terminan sin error.
- [x] **T-6 — Sembrar las properties y los prompts iniciales** · RF-22, RF-25, RF-37 · ~25 min
  Migración `seed assistant defaults`: las properties no secretas de la sección 5 del plan con sus valores por
  defecto, y `agent_prompt` con `external_coordinator`, `internal_coordinator`, `sub_agent_rules` e `internal_welcome`
  (D9), incluidas las reglas de seguridad de RF-38 y RF-39. Sin API keys ni cuentas de servicio.
  Hecho cuando: tras `uv run alembic upgrade head` en local,
  `SELECT count(*) FROM property WHERE key IN ('max_areas_per_message','faqs_per_search','history_messages','conversation_retention_days','response_timeout_seconds','sub_agent_timeout_seconds','sub_agent_max_steps')`
  devuelve 7, `SELECT count(*) FROM agent_prompt` devuelve 4 y el `downgrade -1` borra solo esas filas.

## Fase 3 — Contratos y piezas puras
- [x] **T-7 — Validar el mensaje del usuario** · RF-31, RF-32 · ~15 min
  `src/services/message_validation.py` con los textos fijos en español para mensaje vacío y mensaje largo.
  Hecho cuando: `uv run pytest -q tests/message_validation_test.py` pasa con vacío, solo espacios, 5000 caracteres
  (válido) y 5001 caracteres (rechazado).
- [x] **T-8 — Definir las interfaces de los agentes y sus dobles** · RF-5, RF-12, RF-33 · ~25 min [P]
  `src/agents/llm.py`: `Protocol` `CoordinatorModel`, `SubAgentModel` y `Embedder`; dataclasses `Catalog`, `AreaInfo`,
  `Subtask`, `FaqHit`, `AreaResult`, `RoutingDecision`. `src/utils/exceptions/llm.py` (`LlmUnavailableError`) y
  `src/utils/exceptions/google_chat.py` (`InvalidGoogleTokenError`). `tests/fakes.py` con los modelos y el embedder
  guionados, que registran cada llamada y pueden fallar o demorarse.
  Hecho cuando: `uv run pyright` da 0 errores con los dobles tipados contra los `Protocol` (sin `cast`).
- [x] **T-9 — Crear el registro de herramientas** · RF-27, RF-28, RF-29 · ~20 min
  `src/agents/tools.py`: `AreaTool` (nombre, descripción, esquema Pydantic, `async run`), `TOOLS` vacío y
  `tools_for(area, registry)`.
  Hecho cuando: `uv run pytest -q tests/tools_test.py` pasa con un registro de prueba: entrega solo las asignadas e
  ignora un nombre desconocido con un *warning* verificado con `caplog`.
- [x] **T-10 — Armar los prompts de cada paso** · RF-16, RF-22, RF-38, RF-39 · ~25 min
  `src/agents/prompts.py`: mensajes de `route` (prompt del canal y catálogo de áreas con sus categorías), del
  sub-agente (reglas comunes, prompt del área y FAQ marcadas como información) y de `synthesize` (resultados marcados
  como información).
  Hecho cuando: `uv run pytest -q tests/prompts_test.py` pasa: los prompts salen del `Catalog`, el texto del usuario va
  solo en el `HumanMessage` y las FAQ y los resultados van dentro del bloque de información, nunca en las
  instrucciones.

## Fase 4 — Agentes
- [x] **T-11 — Coordinador: decidir y sanear las subtareas** · RF-3, RF-5, RF-6, RF-16, RF-17, RF-40 · ~25 min
  Nodo `route` en `src/agents/coordinator.py`, que llama a `CoordinatorModel.route` y sanea la decisión (D3, D4).
  Hecho cuando: `uv run pytest -q tests/coordinator_test.py -k route` pasa: descarta ids de otro canal, inactivos e
  inventados; quita duplicados; aplica `max_areas_per_message`; una respuesta directa no crea subtareas.
- [x] **T-12 — Coordinador: redactar la respuesta** · RF-12, RF-13, RF-14 · ~20 min
  Nodo `synthesize`, que recibe la pregunta, el historial y los `AreaResult` con `found`.
  Hecho cuando: `uv run pytest -q tests/coordinator_test.py -k synthesize` pasa con todas las áreas con información,
  una sin información y ninguna con información; en todos los casos el modelo falso recibe los `found` correctos.
- [x] **T-13 — Sub-agente con `responder`** · RF-8, RF-9, RF-10, RF-11, RF-28, RF-30, RNF-7 · ~30 min
  `src/agents/sub_agent.py`: una llamada con la herramienta `responder(encontrado, contenido)` obligatoria y, si el
  área tiene herramientas, un bucle de hasta `sub_agent_max_steps` (D7).
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k "not timeout"` pasa: el modelo recibe solo su subtarea,
  su prompt y sus FAQ, sin historial; `encontrado=False` produce `found=False`; una herramienta que falla devuelve un
  aviso genérico; al llegar al tope de pasos se fuerza `responder`.
- [x] **T-14 — Sub-agente: fallo y tiempo máximo** · RF-15 · ~15 min
  `asyncio.timeout(sub_agent_timeout_seconds)`; una excepción o el *timeout* devuelven `AreaResult(found=False)` y un
  log sin el texto del mensaje.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k timeout` pasa con un modelo falso que se demora y otro que
  lanza una excepción.
- [x] **T-15 — Grafo del coordinador** · RF-1, RF-2, RF-4, RF-7, RF-11, RF-12, RF-15, RNF-2, RNF-6 · ~30 min
  `src/agents/graph.py`: `StateGraph` `route` → (`END` si es directa) → `retrieve` → `Send` × N → `synthesize`, con
  *reducer* de lista para los resultados. Las dependencias (modelos, `KnowledgeSource`, registro de herramientas y
  límites) se pasan en el contexto del grafo.
  Hecho cuando: `uv run pytest -q tests/graph_test.py` pasa: respuesta directa con 1 llamada; dos áreas con 2 + 2
  llamadas; dos sub-agentes que se esperan mutuamente con `asyncio.Event` terminan (prueba que van en paralelo); un
  sub-agente caído no impide la respuesta; un área agregada al catálogo falso funciona sin código.

## Fase 5 — Servicios con BD y Gemini
- [x] **T-16 — Cargar el catálogo del canal** · RF-3, RF-4, RF-16, RF-22, RF-23 · ~25 min
  `load_catalog(session, scope)` en `src/services/knowledge.py`: lee sin caché las áreas, las categorías y
  `agent_prompt` (pocas filas) y delega en la función pura `build_catalog(areas, categories, prompts, scope)`, que
  filtra por canal y por `active` y agrupa las categorías por área.
  Hecho cuando: `uv run pytest -q tests/knowledge_test.py -k catalog` pasa: excluye las áreas de otro canal y las
  inactivas, agrupa las categorías y toma el prompt del coordinador del canal.
- [x] **T-17 — Buscar FAQ y sincronizar embeddings** · RF-8, RF-24 · ~25 min
  `search_faqs(session, area_id, embedding, k)` (coseno, FAQ activas del área) y `sync_embeddings(session, area_ids,
  embedder)` (`embedded_hash` distinto de `content_hash`, un solo lote). La función pura `pending_faqs` decide qué se
  re-embebe.
  Hecho cuando: `uv run pytest -q tests/knowledge_test.py -k pending` pasa con FAQ nueva, editada y sin cambios (solo
  las dos primeras se re-embeben, en un solo lote del `FakeEmbedder`). El SQL se verifica en T-27.
- [x] **T-18 — Implementación de Gemini** · RF-25, RF-33 · ~30 min [P]
  `src/agents/gemini.py`: `route` con salida estructurada, sub-agente con *tool choice* obligatorio, `synthesize` con
  texto, embeddings de 768 dimensiones y *thinking budget* 0 en `route` y en los sub-agentes (D17). Cualquier error del
  proveedor se convierte en `LlmUnavailableError`.
  Hecho cuando: `uv run pytest -q tests/gemini_test.py` pasa con un `BaseChatModel` de prueba: el mapeo de errores, el
  parseo de `RoutingDecision` y la extracción de `responder` funcionan, y `uv run pyright` da 0 errores.
- [x] **T-19 — Guardar y leer las conversaciones** · RF-18, RF-19, RF-20, RF-21 · ~25 min
  `src/services/conversation.py`: `get_or_create_web(session_id | None)`, `get_or_create_chat(key)`, `history(n)`,
  `append_turn` y `delete_expired(cutoff)`, detrás del `Protocol` `ConversationStore`; `FakeConversationStore` en
  `tests/fakes.py`.
  Hecho cuando: `uv run pyright` da 0 errores con la implementación SQL y `FakeConversationStore` tipadas contra
  `ConversationStore` (sin `cast`). El SQL se verifica con la BD local en T-21.
- [x] **T-20 — Orquestar un mensaje** · RF-18, RF-19, RF-20, RF-23, RF-24, RF-25, RF-26, RF-33, RNF-3 · ~30 min
  `src/services/assistant.py`: `answer(session, channel, key, text)`. Valida, carga `load_properties`, la conversación
  y el historial, carga el catálogo, ejecuta el grafo con `asyncio.timeout(response_timeout_seconds)`, guarda el turno
  y registra la duración de cada paso sin el texto.
  Hecho cuando: `uv run pytest -q tests/assistant_test.py` pasa: sesión inexistente crea otra; el historial se limita a
  `history_messages` y no mezcla conversaciones; un cambio del catálogo falso entre dos mensajes se aplica en el
  segundo; si faltan el modelo o la key responde servicio no disponible y
  el log no contiene la key; error o *timeout* del modelo responde servicio no disponible; `caplog` no contiene el
  texto del usuario. Además `uv run pytest -q tests/knowledge_test.py -k sync` pasa: los embeddings pendientes se
  generan y guardan antes de buscar (RF-24).

## Fase 6 — Canales
- [x] **T-21 — Endpoint del chat web** · RF-1, RF-18, RF-32, RF-34 · ~25 min
  `src/interfaces/web_chat.py` y `src/routers/web_chat.py` (`POST /api/v1/chat`), registrado en `main.py`.
  Hecho cuando: `uv run pytest -q tests/web_chat_test.py` pasa (sin `session_id` devuelve uno nuevo; con uno existente
  lo mantiene; un mensaje largo da `200` con aviso; `DatabaseUnavailableError` da `503`) y, en local,
  `curl -X POST localhost:8000/api/v1/chat -H 'Content-Type: application/json' -d '{"message":"hola"}'` devuelve
  `session_id` y `reply`, y un segundo `curl` con ese `session_id` deja 4 filas en `message` para la conversación.
- [x] **T-22 — Verificar el token y la conversación de Google Chat** · RF-35, RF-36 · ~25 min [P]
  `src/services/google_chat.py`: `verify_addon_token` (certificados de Google con `httpx`, emisor, audiencia y cuenta
  de servicio leídas de `property` sin caché), `conversation_key(event)` y `message_text(event)`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k "token or key or text"` pasa: sin token, emisor ajeno y
  cuenta ajena lanzan `InvalidGoogleTokenError`; la clave es el hilo en un space y el space en un DM; en un space se
  usa `argumentText`.
- [x] **T-23 — Endpoint de eventos de Google Chat** · RF-2, RF-35, RF-36, RF-37 · ~25 min
  `src/interfaces/google_chat.py` y `src/routers/google_chat.py` (`POST /api/v1/google-chat/events`): `401` si el token
  es inválido, bienvenida fija al agregar al asistente, y respuesta en `createMessageAction`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k endpoint` pasa con el verificador sobrescrito: `401`;
  agregar al space devuelve `internal_welcome` sin llamar al modelo; un mensaje devuelve la respuesta en el formato del
  complemento.
- [x] **T-24 — Borrar las conversaciones vencidas** · RF-21, RF-23 · ~20 min
  `src/services/retention.py`: tarea cada hora que lee `conversation_retention_days` y llama a `delete_expired`;
  arranca y se cancela en el `lifespan` de `main.py`.
  Hecho cuando: `uv run pytest -q tests/retention_test.py` pasa (la fecha de corte sale de la property; un error de BD
  se registra y la tarea sigue) y `TestClient(app)` arranca y se cierra sin dejar tareas pendientes.

## Fase 7 — Cierre
- [x] **T-25 — Documentar en el README** · RF-18, RF-25, RF-35 · ~20 min
  Endpoints, properties (incluido que no hay caché), tablas, cómo dar de alta un área con sus FAQ y su prompt, y cómo
  asignar herramientas.
  Hecho cuando: cada endpoint de `main.py` y cada property que lee `src/` aparece en el README
  (`grep` de las claves de la sección 5 del plan en `README.md` las encuentra todas).
- [x] **T-26 — Crear la base de la 2.0.0** · RNF-5 · ~25 min
  BD nueva separada en el servidor (nombre por confirmar con el usuario), `CREATE EXTENSION vector` con un usuario con
  privilegios y `uv run alembic upgrade head`. Requiere la confirmación del usuario antes de tocar el servidor remoto.
  Hecho cuando: `SELECT version_num FROM alembic_version` en la BD nueva devuelve la última revisión y la BD de la 1.x
  sigue en `d80964432e58`.
  Hecho en local (2026-10-09, decisión del usuario): `asistente_virtual` en el contenedor `pgvector/pgvector:pg17`,
  creada por el usuario; la extensión `vector` la creó el superusuario `postgres`. El servidor remoto no se tocó.
- [x] **T-27 — Cargar el contenido y los secretos** · RF-22, RF-25 · ~25 min
  Áreas, categorías, FAQ y prompts de la demo; `gemini_api_key`, los modelos y las properties de Google Chat cargados a
  mano, según SECURITY.md.
  Hecho cuando: el primer `POST /api/v1/chat` contra la BD nueva responde con una FAQ y todas las FAQ quedan con
  `embedded_hash = content_hash`.
  Hecho en local (2026-10-09): key, modelos (`gemini-3.1-flash-lite`, `gemini-embedding-001`), «Servicio al Cliente» y
  «Ayuda General» copiados de la 1.x local (37 FAQ). El primer mensaje respondió con la FAQ de pagos en 7,2 s y embebió
  solo las FAQ del área consultada (D10); las de un área se embeben la primera vez que se la consulta.
- [x] **T-28 — Demo manual y latencia** · RF-1 a RF-40, RNF-1 · ~30 min
  Los guiones de los criterios de finalización de la spec: en el web, una FAQ, dos áreas, sin información, «¿qué
  puedo consultar?» y un intento de ver el prompt; en Google Chat, una FAQ en un space (en el hilo) y una pregunta de
  seguimiento.
  Hecho cuando: todos los guiones dan el resultado esperado y, en los logs de duración, el p95 de 20 mensajes es de
  10 s o menos.
  Hecho en local (2026-10-09): 22 mensajes, mediana 4,5 s, p95 7,5 s, máximo 7,6 s. Web por HTTP: FAQ, seguimiento,
  dos áreas (con un área externa temporal), sin información, catálogo, intento de ver el prompt y pregunta interna,
  todos correctos. Canal interno en proceso (`answer` con la BD y Gemini reales): FAQ y seguimiento en el mismo hilo.
  Pendiente al desplegar: la misma prueba con la app real de Google Chat (necesita URL pública).
- [x] **T-29 — Versión 2.0.0** · — · ~5 min
  `version = "2.0.0"` en `pyproject.toml` y `uv lock`, en un commit `chore(release): Version 2.0.0`.
  Hecho cuando: `uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"`
  imprime `2.0.0` y la suite está verde.

## Fase 8 — Ajustes tras la demo
- [x] **T-30 — Coordinador conversacional y canal sin áreas** · RF-16, RF-17, RF-41, RNF-8 · ~30 min
  `src/agents/prompts.py`: catálogo como «temas con los que puedes ayudar» sin citarlo, `EMPTY_CATALOG` cuando el canal
  no tiene áreas y respuesta directa «como una IA»; migración `conversational coordinator prompts` con el tono nuevo de
  los coordinadores (usted siempre en el web, sin plantillas, sin atribuirse trámites ni prometer avisos), que solo
  reemplaza prompts sin editar (D19).
  Hecho cuando: `uv run pytest -q tests/prompts_test.py` pasa (sin áreas recibe `EMPTY_CATALOG` y no aparece
  «Catálogo»); `upgrade`, `downgrade -1` y `upgrade` funcionan y un prompt editado no se pisa; en vivo, sin áreas
  internas «¿en qué me puedes ayudar?» no inventa temas ni habla de áreas o catálogos, y el web responde de usted y
  sin la lista de temas al final.
