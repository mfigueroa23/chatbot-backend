# Tareas 002 — Herramientas y MCP por área, archivos en Google Chat y el área Proyectos consultando Jira

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 21/34 hechas

Cada tarea dura menos de 30 min y deja los tests en verde. Se hacen en orden; `[P]` indica que puede ir en paralelo con
la anterior. "Verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test se conecta a la
BD, a Jira, a un servidor MCP remoto, a Google ni a Gemini (constitución, punto 6, y RNF-4): se usan `httpx.MockTransport`,
un servidor `FastMCP` en memoria y los dobles de `tests/fakes.py`. Las piezas nuevas entran sin cambiar el
comportamiento de la 2.0.0 hasta que se conectan en el grafo o en `assistant`.

## Fase 1 — Base y reorganización (D16)
- [x] **T-1 — Agregar las dependencias aprobadas** · (habilita RF-9 a RF-15 y RF-31) · ~10 min
  `uv add mcp python-docx openpyxl python-pptx`. Requiere la aprobación de la sección 8 del plan.
  Hecho cuando: `uv run python -c "import mcp, docx, openpyxl, pptx"` termina con 0 y la suite sigue verde.
- [x] **T-2 — Mover el registro de herramientas a `src/agents/tools/`** · (D16) · ~15 min
  `src/agents/tools.py` → `src/agents/tools/registry.py`, sin cambiar el comportamiento; se actualizan los imports de
  `graph.py`, `sub_agent.py`, `gemini.py`, `llm.py` y los tests.
  Hecho cuando: `test ! -e src/agents/tools.py` y la suite sigue verde con los mismos tests.
- [x] **T-3 — Separar Google en `src/services/google/`** · (D16) · ~15 min [P]
  `src/services/google_chat.py` → `google/chat_auth.py` (`verify_addon_token`, certificados) y
  `google/chat_events.py` (`conversation_key`, `message_text`); se actualizan `routers/dependencies.py`,
  `routers/google_chat.py` y el `monkeypatch` de `google_chat_test.py`.
  Hecho cuando: `test ! -e src/services/google_chat.py` y `uv run pytest -q tests/google_chat_test.py` pasa sin
  cambios en sus aserciones.

## Fase 2 — Modelo de datos
- [x] **T-4 — Crear los modelos de acceso, Jira y MCP** · RF-4, RF-9, RF-23, RNF-5 · ~20 min
  `AreaMember` (PK `area_id` + `email`), `JiraBoard` (`key`, `active`), `McpServer` (`name` único, `url`,
  `credential_key`, `allowed_tools text[]`, `active`) y `BusinessArea.mcp_servers text[]`.
  Hecho cuando: `uv run pyright` da 0 errores y
  `uv run python -c "import src.models.area_member, src.models.jira_board, src.models.mcp_server"` termina con 0.
- [x] **T-5 — Migración del esquema** · RF-4, RF-9, RF-23 · ~20 min
  `uv run alembic revision --autogenerate -m "add tools access mcp and jira boards"`, revisada a mano
  (`server_default` de los arrays y de `active`, `CASCADE`, sin tocar la extensión).
  Hecho cuando: contra la BD local, `upgrade head`, `downgrade -1` y `upgrade head` terminan sin error y las 3 tablas
  quedan con dueño `chatbot_autofin`.
- [x] **T-6 — Sembrar las properties nuevas** · RF-13, RF-18, RF-22, RF-37, RF-40, RNF-7, RNF-8 · ~15 min
  Migración `seed tools and files defaults` con `jira_max_results`, `jira_timeout_seconds`, `mcp_timeout_seconds`,
  `file_max_mb`, `file_max_chars` y `file_response_timeout_seconds` (`ON CONFLICT DO NOTHING`; sin secretos).
  Hecho cuando: tras `upgrade head`, `SELECT count(*) FROM property WHERE key IN (…)` devuelve 6 y `downgrade -1`
  borra solo esas filas.

## Fase 3 — Contrato de herramientas, identidad y acceso
- [x] **T-7 — `AreaTool` con JSON Schema y `ToolContext`** · RF-2, RF-10 · ~30 min
  `AreaTool(name, description, parameters, run(args, context))`, `ToolContext(requester, properties, session_factory)`
  y `code_tool(name, description, schema, fn)`, que valida con Pydantic. `sub_agent.run_tool` y `gemini.tool_specs` se
  adaptan.
  Hecho cuando: `uv run pytest -q tests/tools_test.py tests/sub_agent_test.py tests/gemini_test.py` pasa: el JSON
  Schema sale del modelo, los argumentos inválidos dan `TOOL_FAILED` y `run` recibe el `ToolContext` con el correo.
- [x] **T-8 — Reglas de acceso** · RF-3, RF-4, RF-5, RF-6, RF-7 · ~20 min [P]
  `src/agents/tools/access.py`: `can_use_tools(area, requester)` y `restricted_note(area, names)`.
  Hecho cuando: `uv run pytest -q tests/access_test.py` pasa: área sin lista → todos; con lista → solo los listados,
  sin distinguir mayúsculas; anónimo nunca en un área con lista; la nota nombra las funciones retiradas.
- [x] **T-9 — Identidad del colaborador** · RF-1, RF-3, RF-42 · ~25 min
  `ChatUser` en el evento, `chat_events.requester_of` (correo en minúsculas), el router pasa `requester` a `answer`, y
  `AgentContext` lo recibe. El web pasa `None`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py tests/web_chat_test.py tests/assistant_test.py -k requester`
  pasa: el correo del evento llega al contexto del grafo y el web llega como anónimo y sin adjuntos.
- [x] **T-10 — Catálogo con miembros y servidores MCP** · RF-8, RF-9, RF-14 · ~25 min
  `AreaInfo.members` (`None` si el área no tiene lista) y `AreaInfo.mcp_servers`; `Catalog.mcp_servers` con los activos.
  `load_catalog` lee `area_member` y `mcp_server` sin caché y `build_catalog` los arma.
  Hecho cuando: `uv run pytest -q tests/knowledge_test.py -k "members or mcp"` pasa: solo servidores activos y
  asignados, miembros en minúsculas y `None` sin lista.
- [x] **T-11 — Herramientas por sub-agente según el acceso** · RF-4, RF-5, RF-6, RF-7, RF-10 · ~25 min
  `sub_agent_node` arma la lista (registro del área) solo si `can_use_tools`; si no, agrega `restricted_note` al prompt
  del sub-agente. `AgentContext` suma `properties` y `session_factory`.
  Hecho cuando: `uv run pytest -q tests/graph_test.py -k access` pasa: un usuario habilitado recibe las herramientas
  del área; uno no habilitado no las recibe, ve la nota y sigue recibiendo las FAQ; un cambio de miembros entre dos
  mensajes se aplica en el segundo.

## Fase 4 — Búsqueda de FAQ y ambigüedad
- [x] **T-12 — Búsqueda acotada a un área con sesión propia** · RF-26 · ~20 min
  `KnowledgeSource.search_area(area_id, query, k)` y `PgKnowledge.search_area`, que abre y cierra su sesión con el
  `session_factory`; `FakeKnowledge.search_area` en los dobles.
  Hecho cuando: `uv run pytest -q tests/knowledge_test.py -k search_area` pasa con una fábrica de sesiones falsa: abre
  una sesión por búsqueda, filtra por el `area_id` recibido y no resincroniza embeddings.
- [x] **T-13 — Herramienta `buscar_faq` para todos los sub-agentes** · RF-25, RF-26, RF-27, RF-30, RNF-6 · ~20 min
  `src/agents/tools/faq_search.py`; `sub_agent_node` la agrega siempre; el prompt del sub-agente dice cuándo usarla.
  Hecho cuando: `uv run pytest -q tests/faq_search_test.py` y `uv run pytest -q tests/graph_test.py -k buscar_faq`
  pasan: busca solo en su
  área, la reciben habilitados y no habilitados, y cuenta en `sub_agent_max_steps`.
- [x] **T-14 — Interpretaciones y pregunta de aclaración** · RF-28, RF-29 · ~25 min
  `Answer.interpretaciones`, `AreaResult.options`, `responder` con el campo nuevo en `tool_specs`, `describe_results`
  las muestra y `SYNTHESIZE_STEP` pide preguntar a cuál se refiere.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py tests/prompts_test.py tests/gemini_test.py -k interpretaciones`
  pasa: las opciones llegan al bloque de resultados y la instrucción de aclarar está en el prompt de `synthesize`.

## Fase 5 — Jira en solo lectura
- [x] **T-15 — Acotar el JQL a los tableros permitidos** · RF-18, RF-19 · ~15 min
  `src/services/jira/scope.py`: `board_of(key)` y `scoped_jql(jql, boards)` (portados de la 1.x).
  Hecho cuando: `uv run pytest -q tests/jira_client_test.py -k scope` pasa: quita `ORDER BY` y lo repone, rechaza
  paréntesis desbalanceados, antepone `project in (…)` y `board_of` devuelve `None` para claves inválidas.
- [x] **T-16 — Cliente de Jira de solo lectura** · RF-17, RF-20, RF-22 · ~25 min [P]
  `src/services/jira/client.py` (`search`, `get_issue`, `children`, `adf_to_text`) y `JiraUnavailableError`.
  Hecho cuando: `uv run pytest -q tests/jira_client_test.py -k client` pasa con `MockTransport`: arma bien las rutas
  `/rest/api/3/…`, 404 → `None`, 5xx y timeout → `JiraUnavailableError`, y el transporte falla si recibe un método
  distinto de GET.
- [x] **T-17 — Herramienta `leer_ticket`** · RF-17, RF-19, RF-22, RF-23, RF-24, RNF-2 · ~25 min
  `src/services/jira/boards.py` y `src/agents/tools/jira.py`: tablero revisado antes de llamar a Jira, credenciales
  desde `ToolContext.properties` y descripción marcada como información.
  Hecho cuando: `uv run pytest -q tests/jira_tools_test.py -k leer` pasa: estado, tipo, responsable, descripción,
  subtareas e hijos; tablero no permitido sin llamar a Jira y con el mismo texto que un inexistente; Jira caído sin
  detalle; el token no aparece en `caplog`.
- [x] **T-18 — Herramienta `buscar_tickets` y registro** · RF-18, RF-20, RF-21 · ~20 min
  `buscar_tickets(jql)` acotada con `scoped_jql`; `TOOLS` registra `buscar_tickets` y `leer_ticket`.
  Hecho cuando: `uv run pytest -q tests/jira_tools_test.py -k "buscar or registro"` pasa: la búsqueda llega a Jira con
  `project in (…)`, JQL inválido → «no pude buscar», y el registro no tiene herramientas que escriban en Jira.

## Fase 6 — Servidores MCP
- [x] **T-19 — Cliente MCP** · RF-9, RF-12, RF-13 · ~25 min
  `src/services/mcp/client.py` (`McpClient`: sesión *streamable HTTP*, credencial como header, `list_tools` y
  `call_tool` con timeout) y `McpUnavailableError`. La sesión se inyecta para poder usar el servidor en memoria.
  Hecho cuando: `uv run pytest -q tests/mcp_test.py -k client` pasa con un `FastMCP` en memoria: lista y llama
  herramientas; un servidor que falla o se demora da `McpUnavailableError`; la credencial no aparece en `caplog`.
- [x] **T-20 — `McpToolset`: solo herramientas permitidas** · RF-10, RF-11, RF-13, RF-15 · ~25 min
  `src/agents/tools/mcp.py`: filtra por `allowed_tools`, adapta a `AreaTool` (con el JSON Schema del servidor), omite
  servidores caídos y marca el resultado como información.
  Hecho cuando: `uv run pytest -q tests/mcp_test.py -k toolset` pasa: la herramienta de escritura no permitida no
  llega; con `allowed_tools` vacío no aporta ninguna; un servidor caído se omite con un *warning* y el otro sigue.
- [x] **T-21 — MCP en el grafo** · RF-10, RF-12, RF-14 · ~20 min
  `sub_agent_node` abre el `McpToolset` del área (si el usuario puede usar herramientas), lo cierra al terminar y toma
  la credencial de `properties[credential_key]`.
  Hecho cuando: `uv run pytest -q tests/graph_test.py -k mcp` pasa: el sub-agente recibe registro + MCP + `buscar_faq`;
  las sesiones se cierran aunque el sub-agente falle; un servidor desactivado entre dos mensajes ya no se usa.

## Fase 7 — Archivos en Google Chat
- [ ] **T-22 — Formatos y extractores** · RF-31, RF-38 · ~25 min
  `src/services/files/formats.py` y `extractors.py` (Word, Excel, PowerPoint y texto, portados de la 1.x).
  Hecho cuando: `uv run pytest -q tests/attachments_test.py -k "formats or extract"` pasa con archivos generados en
  memoria y texto en UTF-8 y Latin-1; un formato no admitido se reconoce como tal.
- [ ] **T-23 — Descarga de adjuntos de Chat con tope** · RF-37, RNF-8 · ~25 min [P]
  `src/services/google/service_account.py` (token `chat.bot`) y `chat_media.py` (*stream* con corte en `max_bytes`);
  `AttachmentTooLargeError`.
  Hecho cuando: `uv run pytest -q tests/chat_media_test.py` pasa con `MockTransport`: pide el token con el scope
  correcto, descarga completa por debajo del tope, corta y lanza `AttachmentTooLargeError` por encima, y el JSON de
  la cuenta no aparece en `caplog`.
- [ ] **T-24 — Transcribir imágenes y PDF** · RF-31, RF-32 · ~20 min [P]
  `Transcriber` en `llm.py`, `GeminiTranscriber` en `gemini.py` (mensaje multimodal en base64 con `sub_agent_model`) y
  `FakeTranscriber`.
  Hecho cuando: `uv run pytest -q tests/gemini_test.py -k transcribe` pasa con `RunnableLambda`: imagen y PDF van como
  bloques multimodales con su `mime_type` y un error del proveedor da `LlmUnavailableError`.
- [ ] **T-25 — Leer los adjuntos de un mensaje** · RF-31, RF-32, RF-33, RF-37, RF-38, RF-39, RF-40, RF-41, RNF-9 · ~25 min
  `src/services/files/attachments.py`: `read_attachments` (en paralelo, un resultado por archivo) y `files_block`.
  Hecho cuando: `uv run pytest -q tests/attachments_test.py -k read` pasa: cada formato, más de 20 MB → `too_large`,
  formato no admitido, un fallo no detiene a los demás, truncado con aviso, varios archivos, el bloque va marcado como
  información y el contenido no aparece en `caplog`.
- [ ] **T-26 — Adjuntos del evento de Google Chat** · RF-31, RF-38 · ~20 min
  `ChatAttachment` en `interfaces/google_chat.py`, `chat_events.attachments_of` (subidos → descargables; Drive → no
  admitidos) y el router los pasa a `answer`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k adjuntos` pasa: un evento con una foto subida y un
  enlace de Drive llega a `answer` con dos adjuntos y el de Drive marcado como no admitido.
- [ ] **T-27 — Archivos en la orquestación** · RF-34, RF-35, RNF-7 · ~25 min
  `answer(..., attachments)`: lee los archivos antes del grafo, `validate_user_message(text, has_files)`, guarda el
  bloque en el mensaje del usuario y usa `file_response_timeout_seconds`.
  Hecho cuando: `uv run pytest -q tests/assistant_test.py tests/message_validation_test.py -k archivos` pasa: un
  mensaje solo con archivos es válido; el bloque queda en el historial y llega en el mensaje siguiente; con archivos
  rige el tope de 27 s; sin archivos, el de siempre.
- [ ] **T-28 — Prompts con archivos** · RF-34, RF-36, RF-41 · ~15 min
  `ROUTE_STEP`: si hay archivos, incluir en la subtarea el fragmento relevante y, si solo hay archivos, responder
  directo resumiendo y preguntando qué necesita.
  Hecho cuando: `uv run pytest -q tests/prompts_test.py -k archivos` pasa: con un bloque de archivos, el prompt de
  `route` contiene las dos instrucciones y el contenido sigue dentro del bloque de información.

## Fase 8 — Datos, documentación y demos
- [ ] **T-29 — Documentar en el README** · RF-9, RF-12, RF-23, RNF-5, RNF-8 · ~20 min
  Tablas nuevas (alta de un miembro, un tablero y un servidor MCP con SQL de ejemplo), properties nuevas, herramientas
  de Proyectos, formatos de archivo y la estructura de paquetes.
  Hecho cuando: cada property que lee `src/` y cada tabla nueva aparecen en el README (`grep` de cada clave y cada
  tabla las encuentra).
- [ ] **T-30 — Cargar el área Proyectos en local** · RF-16, RF-21, RF-23 · ~25 min
  Script de carga: área interna «Proyectos» (prompt de solo lectura), FAQ de la guía de secciones del EDR,
  `tools = {buscar_tickets, leer_ticket}`, tableros, miembros y credenciales de Jira (con confirmación del usuario).
  Hecho cuando: en la BD local el catálogo interno muestra Proyectos con sus categorías, y en proceso «¿qué va en
  validaciones de cartera?» responde con la FAQ.
- [ ] **T-31 — Demo local: Jira, MCP y ambigüedad** · RF-9 a RF-15, RF-17 a RF-22, RF-25 a RF-29, RNF-1 · ~30 min
  En proceso con Gemini y Jira reales: épica, búsqueda, tablero no permitido, «cierra el ticket» y la misma consulta
  como no habilitado; un `FastMCP` de prueba por HTTP asignado a un área (permitida y no permitida); en el web, una
  pregunta ambigua.
  Hecho cuando: todos los guiones dan el resultado esperado y el p95 de la demo de la spec 001 sigue en 10 s o menos.
- [ ] **T-32 — Cargar la base remota** · RF-16, RF-23, RNF-3 · ~20 min
  Migraciones y script de carga contra la BD remota de la 2.0.0, y credenciales de Jira y de la cuenta de servicio de
  Chat en `property`; la cuenta de Jira es de solo lectura (RNF-3). Requiere la confirmación del usuario antes de
  escribir en el servidor remoto.
  Hecho cuando: `alembic current` remoto está en la última revisión y el catálogo interno remoto muestra Proyectos
  con sus herramientas, tableros y miembros.
- [ ] **T-33 — Demo en Google Chat** · RF-1, RF-7, RF-17 a RF-22, RF-31 a RF-40, RNF-7 · ~30 min
  Con la app real, después del despliegue: los guiones de Jira de la spec y los de archivos (foto, PDF, Word, más de
  20 MB, formato no admitido y una pregunta de seguimiento sobre un archivo ya leído).
  Hecho cuando: todos los guiones dan el resultado esperado y ningún mensaje con archivos pasa de 27 s en los logs de
  duración.
- [ ] **T-34 — Versión 2.1.0** · — · ~5 min
  `version = "2.1.0"` en `pyproject.toml` y `uv lock`, en un commit `chore(release): Version 2.1.0`.
  Hecho cuando: `pyproject.toml` dice `2.1.0` y la suite está verde.
