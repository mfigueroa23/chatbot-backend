# Plan 005 — Archivos adjuntos, consulta de Jira y EDR en Google Chat

**Spec:** `docs/specs/005-attachments-jira-edr/spec.md` · **Estado:** aprobado (2026-10-08)
Se reutiliza el coordinador de la spec 004 (coordinador → agente interno → agentes de área), el control posterior, el
webhook de Google Chat con respuesta diferida y la cuenta de servicio de Chat. Se añaden la lectura de adjuntos antes del
grafo, herramientas de Jira y EDR para las áreas que las tengan habilitadas (Proyectos) y tres tablas de datos.

## 1. Resumen
- **Archivos (RF-1 a RF-11):** al recibir un mensaje de Google Chat con adjuntos, el orquestador los descarga (API de
  media de Chat para los subidos, API de Drive para los enlazados), comprueba tamaño y formato y los convierte en texto:
  imágenes y PDF los transcribe Gemini en una llamada multimodal; Word, Excel y PowerPoint se extraen en código; los de
  texto se decodifican. El texto entra en el mensaje del usuario marcado como contenido de archivo, así queda en la
  memoria de la conversación y el coordinador lo ve como información.
- **Jira (RF-12 a RF-17):** cliente REST de solo lectura; herramientas `buscar_tickets` y `leer_ticket` en el agente del
  área Proyectos, con la lista de tableros permitidos aplicada en código.
- **EDR (RF-18 a RF-25):** herramientas `leer_edr` y `guardar_edr` en el mismo agente de área; el EDR se valida contra
  el esquema de `agente-ti`, se renderiza a HTML con una plantilla del repo y se sube a Drive como Google Doc; el
  documento de cada conversación se recuerda en una tabla.
- **Acceso (RF-26 a RF-29):** lista de colaboradores habilitados y de tableros permitidos en tablas propias; las
  herramientas comprueban el correo de Google Chat del solicitante.
- **Seguridad (RF-30 a RF-32):** los textos de archivos y los resultados de Jira cuentan como evidencia del control
  posterior; el web no tiene adjuntos ni áreas con herramientas.

## 2. Módulos

### Archivos compartidos
| Módulo | Cambio | RF |
|---|---|---|
| `src/interfaces/google_chat.py` | `ChatAttachment` (`content_name`, `content_type`, `source`, `attachment_data_ref.resource_name`, `drive_data_ref.drive_file_id`) y `ChatMessage.attachment: list[ChatAttachment]` | RF-1, RF-3 |
| `src/services/chat_api_client.py` | `ChatApiClient.download_media(resource_name) -> bytes` (`GET /v1/media/{resource}?alt=media`, scope `chat.bot`); el token se pide por scope para reutilizar la misma cuenta de servicio con Drive | RF-1 |
| `src/services/drive_client.py` (nuevo) | `DriveClient` sobre `httpx` con la cuenta de servicio y scope `drive`: `file_metadata(id)` (nombre, mimeType, tamaño), `download(id)`, `export(id, mime)` para Docs/Sheets/Slides nativos, `create_document_from_html(name, folder, html)` y `replace_document_html(id, html)`; un 403/404 lanza `DriveFileNotAccessibleError` | RF-1, RF-7, RF-21, RF-23 |
| `src/services/attachments.py` (nuevo) | `read_attachments(attachments, clients, llm, limits) -> list[AttachmentText]`: tamaño (`attachment_max_mb`, 20), formato legible, descarga, extracción y truncado a `attachment_max_chars` (60000); devuelve por archivo el texto o el motivo de no lectura (`too_large`, `unsupported`, `not_accessible`, `failed`, `truncated`) | RF-1 a RF-9 |
| `src/services/document_extractor.py` (nuevo) | `extract_docx`, `extract_xlsx`, `extract_pptx` (texto por párrafo, hoja y diapositiva) y `decode_text` | RF-1 |
| `src/agents/llm.py` | `GeminiAgentLLM.transcribe(data, mime_type) -> str`: llamada multimodal que transcribe una imagen o un PDF (texto, tablas y descripción de lo que muestra) | RF-1, RF-2 |
| `src/services/google_chat.py` | `handle_event` pasa los adjuntos al orquestador; con un mensaje solo de archivos el texto es vacío pero se procesa | RF-1, RF-3 |
| `src/services/chat_orchestrator.py` | `handle_internal_message(..., attachments=[])` lee los adjuntos antes del grafo y arma el mensaje del usuario: su texto y un bloque por archivo (`[Archivo «nombre»: …]` o el motivo de no lectura); el mensaje vacío solo se rechaza si tampoco trae archivos | RF-1 a RF-10 |
| `src/agents/graph.py` | La evidencia del control posterior incluye los bloques de archivo del historial de la conversación | RF-31 |

### Jira y EDR
| Módulo | Cambio | RF |
|---|---|---|
| `src/services/jira_client.py` (nuevo) | `JiraClient` REST v3 sobre `httpx` con correo y token de API (`jira_base_url`, `jira_email`, `jira_api_token`): `search(jql, max)` (`/rest/api/3/search/jql`), `get_issue(key)` y `children(key)`; solo métodos `GET`/búsqueda; `adf_to_text` para las descripciones | RF-12, RF-13, RF-14, RF-17 |
| `src/services/project_access.py` (nuevo) | `is_enabled(session, email)`, `allowed_boards(session)` y `scoped_jql(jql, boards)` (`project in (...) AND (jql)`, rechaza JQL que intente salir del paréntesis) | RF-13, RF-16, RF-26 a RF-29 |
| `src/services/edr.py` (nuevo) | `EdrDocument` (Pydantic, esquema de `agente-ti` con `[PENDIENTE DEFINIR]` por defecto), `render_edr_html(edr)` con plantilla Jinja2 en `src/templates/edr.html`, `save_edr(session, conversation_id, edr, drive)` y `get_edr(session, conversation_id)` | RF-18 a RF-24 |
| `src/agents/tools.py` | `AreaToolbox` añade, si el área tiene la herramienta habilitada en `business_area.tools`: `buscar_tickets(jql)`, `leer_ticket(clave)` (con épica, subtareas e hijos), `leer_edr()` y `guardar_edr(edr)`. Cada una comprueba primero que el solicitante esté habilitado; sin acceso devuelve «función no habilitada para este colaborador» sin llamar a Jira ni a Drive | RF-12 a RF-26 |
| `src/agents/sub_agent.py` | `AreaAnswer.documents`: textos de Jira y del EDR guardado, para la evidencia | RF-31 |
| `src/agents/coordinator.py` | Resultado de `consultar_areas` con el enlace del EDR cuando el área lo guardó; `delivered` no cambia (guardar un EDR no es avisar a nadie) | RF-22, RF-24 |
| `src/models/` (nuevos) | `JiraBoard`, `ProjectCollaborator`, `EdrDocumentRecord`; `BusinessArea.tools` | RF-23, RF-26 a RF-28 |
| `README.md` | Adjuntos, Jira, EDR, tablas y properties nuevas | — |

## 3. Modelo de datos
Migración de esquema nueva y revisada a mano (constitución, punto 8):
- **`jira_board`**: `id` serial PK, `key` varchar(20) NOT NULL UNIQUE (p. ej. `DAIA`), `active` boolean NOT NULL DEFAULT
  true. Tableros permitidos.
- **`project_collaborator`**: `id` serial PK, `email` varchar(255) NOT NULL UNIQUE (comparación en minúsculas),
  `active` boolean NOT NULL DEFAULT true. Colaboradores habilitados.
- **`edr_document`**: `id` serial PK, `conversation_id` varchar(255) NOT NULL (índice), `drive_file_id` varchar(255)
  NOT NULL, `web_link` text NOT NULL, `title` text NOT NULL, `content` jsonb NOT NULL (el último EDR guardado),
  `created_at`/`updated_at` timestamptz NOT NULL. Una fila por EDR; el activo de la conversación es el más reciente.
- **`business_area.tools`**: `text[]` NOT NULL DEFAULT `'{}'`. Las filas existentes quedan sin herramientas; Proyectos
  recibe `{jira,edr}` en la carga de datos del despliegue.
- **Properties nuevas:** `jira_base_url`, `jira_email`, `jira_api_token` (secreto, ver SECURITY.md), `edr_drive_folder_id`
  (carpeta de una unidad compartida), `attachment_max_mb` (20), `attachment_max_chars` (60000), `jira_max_results` (20).
- **Checkpointer:** sin cambios; los bloques de archivo viajan en el `HumanMessage`.

## 4. Contrato
- **Google Chat `/api/v1/google-chat/events`:** se leen los campos `message.attachment` del evento (de Google); la
  respuesta no cambia de forma.
- **WebSocket `/ws/v1/chat`:** sin cambios (RF-11).

## 5. Decisiones
- **D1 — Jira por REST con token de API, no por MCP.** El MCP remoto de Atlassian (Rovo) autentica por OAuth con
  consentimiento interactivo de cada usuario y expone herramientas de escritura que habría que filtrar; un bot de
  servidor necesita una credencial propia y la lista de tableros se aplica mejor en código. REST usa `httpx`, que ya está.
  *Descartada:* MCP con `langchain-mcp-adapters` — dependencias nuevas (`mcp`, adaptadores), OAuth por usuario y
  solo-lectura no garantizada en código. **Decisión del usuario (2026-10-08): REST con token de API.**
- **D2 — Los archivos se convierten en texto una vez, al recibirlos.** El texto queda en la memoria y sirve en los
  mensajes siguientes (RF-4) sin volver a descargar ni guardar binarios en el checkpointer. *Descartada:* pasar las
  imágenes o PDF al modelo en cada turno — infla el historial y repite la llamada multimodal.
- **D3 — PDF e imágenes los transcribe Gemini; Office se extrae en código.** Gemini lee PDF e imágenes de forma nativa
  hasta 20 MB por petición (el mismo tope de la spec); no lee .docx/.xlsx/.pptx. *Descartada:* `markitdown` —
  arrastra `onnxruntime` (motivo de `agente-ti`); *descartada:* `pypdf` — no hace falta contar páginas con el tope de 20 MB.
- **D4 — Jira y EDR como herramientas del agente del área Proyectos, habilitadas por área.** Mantiene el patrón de la
  spec 004: el coordinador no conoce Jira; el agente interno deriva en Proyectos y el especialista consulta y redacta.
  *Descartada:* herramientas del coordinador — rompería RF-6 de la spec 004 y llevaría contenido de Jira a su contexto.
- **D5 — Acceso por tablas propias.** Colaboradores y tableros son datos de negocio (constitución, punto 4). *Descartada:*
  una property con una lista separada por comas — mezcla datos de negocio con configuración técnica.
- **D6 — EDR renderizado a HTML y subido a Drive como Google Doc.** Es el camino probado en `agente-ti`; la plantilla
  queda versionada y el contenido se guarda en `edr_document.content` para editarlo. *Descartada:* la API de Google Docs
  con `batchUpdate` — mucho más código para tablas y listas; *descartada:* copiar una plantilla de Drive — la estructura
  quedaría fuera del repo.
  **Ajuste (2026-10-08, decisión del usuario):** la plantilla puede venir de la property `edr_template_base64` (HTML en
  base64) para cambiar el formato sin desplegar; sin ella se usa `src/templates/edr.html`, que es la de `agente-ti`.
  Se renderiza con `SandboxedEnvironment` porque el texto viene de la BD. *Descartada:* una tabla propia para
  plantillas — cambia el esquema para un único valor de configuración.
- **D7 — Drive con la cuenta de servicio de Chat y una carpeta de unidad compartida.** Una cuenta de servicio no tiene
  cuota propia para crear documentos fuera de una unidad compartida. *Descartada:* OAuth de una cuenta de Workspace
  propia (como `agente-ti`) — otra credencial y refresco de token.
- **D8 — Datos de archivos y Jira como evidencia (RF-31).** Se suman a `evidence` del control posterior: los bloques de
  archivo de la conversación y `AreaAnswer.documents` del mensaje. *Descartada:* desactivar el detector de datos
  personales en el canal interno — dejaría pasar datos inventados.

## 6. Estrategia de tests
Sin red ni BD: `respx` no está; los clientes reciben un `httpx.AsyncClient` con `MockTransport` (como `area_notifier_test`).
- **Unidad — `tests/document_extractor_test.py`:** .docx/.xlsx/.pptx generados en memoria y texto con distintas codificaciones.
- **Unidad — `tests/attachments_test.py`:** tamaño (RF-5), formato (RF-6), Drive sin acceso (RF-7), fallo (RF-8),
  truncado (RF-9), imagen y PDF por transcripción (RF-1, RF-2), varios archivos (RF-3).
- **Unidad — `tests/jira_client_test.py` y `tests/project_access_test.py`:** búsqueda con JQL acotado, JQL que intenta
  salir del paréntesis, ticket de tablero no permitido (RF-16), Jira caído (RF-17), solo métodos de lectura (RF-14),
  colaborador no habilitado (RF-26), comparación de correo sin mayúsculas.
- **Unidad — `tests/edr_test.py`:** pendientes por defecto (RF-20), HTML con todas las secciones, crear y actualizar el
  mismo documento (RF-21, RF-23), fallo de Drive (RF-24).
- **Agentes — `tests/sub_agent_test.py`:** herramientas solo en áreas habilitadas; acceso denegado sin llamar a Jira;
  `documents` en la respuesta.
- **Grafo — `tests/agent_graph_test.py`:** dato personal de un archivo o de Jira permitido (RF-31); contenido de archivo
  que pide ignorar reglas (RF-10); el web sin herramientas (RF-32).
- **Servicio — `tests/chat_orchestrator_test.py` y `tests/google_chat_test.py`:** mensaje solo con archivo; bloques de
  archivo en la memoria (RF-4); evento con adjunto subido y de Drive.

## 7. Orden de implementación
1. Migración y modelos (`jira_board`, `project_collaborator`, `edr_document`, `business_area.tools`).
2. Extractores de documentos y `GeminiAgentLLM.transcribe`.
3. Descarga de media de Chat y `DriveClient` (lectura).
4. `read_attachments` y su uso en el orquestador y en `handle_event`.
5. `JiraClient` y `project_access`.
6. Herramientas de Jira en `AreaToolbox`.
7. `EdrDocument`, plantilla HTML, `DriveClient` (escritura) y herramientas de EDR.
8. Evidencia de archivos y Jira en el control posterior.
9. README, `uv run pyright`, `uv run pytest`, versión.
10. Despliegue: properties, Proyectos con `{jira,edr}`, listas de acceso, prompts y demo.

## 8. Matriz de cobertura
| RF | Módulos | Tests |
|---|---|---|
| RF-1 | `attachments`, `document_extractor`, `llm.transcribe`, `chat_orchestrator` | `attachments_test`, `document_extractor_test` |
| RF-2 | `llm.transcribe`, `attachments` | `attachments_test` |
| RF-3 | `attachments`, `google_chat` | `attachments_test`, `google_chat_test` |
| RF-4 | `chat_orchestrator` (bloques en el mensaje, D2) | `chat_orchestrator_test` |
| RF-5 | `attachments` | `attachments_test` |
| RF-6 | `attachments` | `attachments_test` |
| RF-7 | `drive_client`, `attachments` | `attachments_test` |
| RF-8 | `attachments` | `attachments_test` |
| RF-9 | `attachments` | `attachments_test` |
| RF-10 | `chat_orchestrator` (bloque marcado), prompts | `agent_graph_test` |
| RF-11 | WebSocket sin cambios | `web_chat_ws_test` |
| RF-12 | `jira_client`, `tools` | `jira_client_test`, `sub_agent_test` |
| RF-13 | `project_access.scoped_jql` | `project_access_test` |
| RF-14 | `jira_client` (solo lectura) | `jira_client_test` |
| RF-15 | prompts del coordinador y de Proyectos | demo |
| RF-16 | `project_access`, `tools` | `project_access_test`, `sub_agent_test` |
| RF-17 | `jira_client`, `tools` | `jira_client_test` |
| RF-18 | `tools.guardar_edr`, prompt de Proyectos | `sub_agent_test`, demo |
| RF-19 | `tools.leer_ticket`, prompt de Proyectos | `sub_agent_test` |
| RF-20 | `edr.EdrDocument` | `edr_test` |
| RF-21 | `edr.save_edr`, `drive_client` | `edr_test` |
| RF-22 | `coordinator` (enlace), `tools` | `edr_test`, `sub_agent_test` |
| RF-23 | `edr.save_edr` (mismo documento) | `edr_test` |
| RF-24 | `edr`, control posterior (spec 004) | `edr_test`, `agent_graph_test` |
| RF-25 | prompt de Proyectos | demo |
| RF-26 | `project_access`, `tools` | `project_access_test`, `sub_agent_test` |
| RF-27 | modelos y servicios sin caché | `project_access_test` |
| RF-28 | `project_access` (sin caché) | `project_access_test` |
| RF-29 | `tools` (correo del `Requester`) | `sub_agent_test` |
| RF-30 | `graph.respond` (sin cambios) | `agent_graph_test` |
| RF-31 | `graph.respond`, `AreaAnswer.documents` (D8) | `agent_graph_test` |
| RF-32 | `tools` (solo áreas con herramientas; el web no tiene) | `agent_graph_test` |
| RNF-1 | router de Google Chat (respuesta diferida existente) | `google_chat_test` |
| RNF-2 | properties, logs sin secretos | `jira_client_test` |
| RNF-3 | `MockTransport` y dobles | todos |

## 9. Riesgos y dudas
- **R1 — MCP pedido por el usuario (D1).** **Decisión del usuario (2026-10-08):** REST con token de API de una cuenta
  de Jira de solo lectura; MCP descartado por OAuth por usuario y herramientas de escritura.
- **R2 — Dependencias nuevas (constitución, punto 1).** `python-docx`, `openpyxl` y `python-pptx` (MIT/BSD, sin
  dependencias de sistema). **Aprobadas por el usuario (2026-10-08).** Jinja2 ya viene con `fastapi[standard]`.
- **R3 — Cambio de esquema (AGENTS.md).** Tres tablas y una columna (sección 3). **Aprobado por el usuario (2026-10-08).**
- **R4 — Unidad compartida y cuentas.** La cuenta de servicio debe ser miembro de la unidad compartida de los EDR y de
  los archivos de Drive que se lean; la app de Chat debe estar en los spaces donde se suban archivos. Configuración de
  Google Workspace.
- **R5 — Latencia y memoria.** Un PDF de 20 MB suma una llamada multimodal y ocupa memoria del pod (512 MiB); la
  respuesta diferida cubre más de 30 s (RNF-1), pero varios archivos grandes a la vez pueden presionar la memoria.
- **R6 — Token de Jira.** Se guarda en `property` en texto plano (constitución, punto 12, SECURITY.md); conviene una
  cuenta de Jira de solo lectura dedicada al asistente.
