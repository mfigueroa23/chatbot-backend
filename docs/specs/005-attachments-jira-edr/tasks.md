# Tareas 005 — Archivos adjuntos, consulta de Jira y EDR en Google Chat (chatbot-backend)

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 13/22 hechas
Cada tarea dura menos de 30 min y deja los tests en verde. Se hacen en orden; `[P]` = puede ir en paralelo con la anterior.
"Verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test se conecta a la BD, a Google
ni a Jira: los clientes HTTP reciben un `httpx.MockTransport`. Cada pieza nueva entra con parámetros por defecto que no
cambian el comportamiento vigente hasta que se conecta.

## Fase 1 — Datos y dependencias
- [x] **T-1 — Añadir las librerías de Office** · (habilita RF-1) · ~10 min
  `uv add python-docx openpyxl python-pptx` (aprobadas en R2 del plan).
  Hecho cuando: `uv run python -c "import docx, openpyxl, pptx"` termina con 0 y la suite sigue verde.
- [x] **T-2 — Crear los modelos de acceso y de EDR** · RF-23, RF-27 · ~20 min
  `JiraBoard`, `ProjectCollaborator` y `EdrDocumentRecord` en `src/models/`; `BusinessArea.tools` (`text[]`, por defecto vacío).
  Hecho cuando: `uv run pyright` da 0 errores y `uv run python -c "import src.models.jira_board, src.models.project_collaborator, src.models.edr_document"` termina con 0.
- [x] **T-3 — Crear la migración del esquema** · RF-23, RF-27 · ~20 min
  `uv run alembic revision --autogenerate -m "add jira access and edr documents"`, revisada a mano (índice de `conversation_id`, `server_default` de `tools`).
  Hecho cuando: en local `uv run alembic upgrade head`, `downgrade -1` y otra vez `upgrade head` terminan sin error.

## Fase 2 — Extracción de contenido
- [x] **T-4 — Extraer texto de Word, Excel, PowerPoint y texto plano** · RF-1 · ~25 min
  `src/services/document_extractor.py`: `extract_docx`, `extract_xlsx`, `extract_pptx`, `decode_text`.
  Hecho cuando: `uv run pytest -q tests/document_extractor_test.py` pasa con archivos generados en memoria y texto en UTF-8 y Latin-1.
- [x] **T-5 — Transcribir imágenes y PDF con el modelo** · RF-1, RF-2 · ~20 min [P]
  `GeminiAgentLLM.transcribe(data, mime_type)` en `src/agents/llm.py` (mensaje multimodal); `FakeAgentLLM.transcribe` guionizado.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k transcribe` pasa con imagen, PDF y error del proveedor.

## Fase 3 — Clientes de Google
- [x] **T-6 — Descargar adjuntos de Google Chat** · RF-1 · ~20 min
  `ChatApiClient.download_media(resource_name)` y token por scope en `src/services/chat_api_client.py`.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k download_media` pasa con descarga correcta y error HTTP.
- [x] **T-7 — Leer archivos de Drive** · RF-1, RF-7 · ~25 min
  `src/services/drive_client.py`: `file_metadata`, `download`, `export` y `DriveFileNotAccessibleError` ante 403/404.
  Hecho cuando: `uv run pytest -q tests/drive_client_test.py -k lectura` pasa con archivo normal, documento nativo exportado y sin acceso.

## Fase 4 — Adjuntos en la conversación
- [x] **T-8 — Leer los adjuntos de un mensaje** · RF-1 a RF-9 · ~30 min (depende de T-4 a T-7)
  `read_attachments` en `src/services/attachments.py`: tamaño, formato, descarga según origen, extracción o transcripción y truncado; un resultado por archivo.
  Hecho cuando: `uv run pytest -q tests/attachments_test.py` pasa con cada formato, más de 20 MB, formato no admitido, Drive sin acceso, fallo de lectura, truncado y varios archivos.
- [x] **T-9 — Recibir los adjuntos del evento de Google Chat** · RF-1, RF-3 · ~20 min
  `ChatAttachment` y `ChatMessage.attachment` en `src/interfaces/google_chat.py`; `handle_event` los pasa al orquestador.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k adjunto` pasa con un adjunto subido, uno de Drive y un mensaje solo con archivo.
- [x] **T-10 — Llevar el contenido de los archivos al mensaje del usuario** · RF-1, RF-4, RF-8, RF-10 · ~25 min
  `handle_internal_message(..., attachments=[])` lee los adjuntos y arma un bloque por archivo en el mensaje; un mensaje vacío con archivos se procesa.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k archivo` pasa con bloque en el mensaje, motivo de no lectura, memoria del hilo y mensaje vacío con archivo.

## Fase 5 — Jira (solo lectura)
- [x] **T-11 — Crear el cliente de Jira de solo lectura** · RF-12, RF-14, RF-17 · ~30 min
  `src/services/jira_client.py`: `search`, `get_issue`, `children`, `adf_to_text`; credenciales por property; sin métodos de escritura.
  Hecho cuando: `uv run pytest -q tests/jira_client_test.py` pasa con búsqueda, ticket con subtareas, descripción ADF, Jira caído y sin el token en los logs.
- [x] **T-12 — Aplicar el acceso por colaborador y tablero** · RF-13, RF-16, RF-26 a RF-29 · ~25 min [P]
  `src/services/project_access.py`: `is_enabled`, `allowed_boards`, `scoped_jql` (rechaza JQL que intente salir del paréntesis).
  Hecho cuando: `uv run pytest -q tests/project_access_test.py` pasa con correo en mayúsculas, inactivo, JQL acotado y JQL malicioso.
- [x] **T-13 — Dar las herramientas de Jira al área habilitada** · RF-12, RF-13, RF-15, RF-16, RF-26, RF-29, RF-32 · ~30 min (depende de T-11, T-12)
  `AreaInfo.tools`, `load_catalog` lo lee; `AreaToolbox` añade `buscar_tickets` y `leer_ticket` solo si el área tiene `jira`, con acceso comprobado antes de llamar a Jira.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k jira` pasa con área sin herramienta, colaborador no habilitado (sin llamada a Jira), tablero no permitido y épica con subtareas.

## Fase 6 — EDR
- [ ] **T-14 — Definir el EDR y su HTML** · RF-18, RF-20 · ~30 min
  `EdrDocument` en `src/services/edr.py` (esquema de `agente-ti`, `[PENDIENTE DEFINIR]` por defecto) y `render_edr_html` con `src/templates/edr.html`.
  Hecho cuando: `uv run pytest -q tests/edr_test.py -k "pendiente or html"` pasa con todas las secciones en el HTML y los pendientes marcados.
- [ ] **T-15 — Escribir Google Docs en Drive** · RF-21, RF-23 · ~20 min (depende de T-7)
  `DriveClient.create_document_from_html` y `replace_document_html` (subida multiparte que convierte a Google Doc).
  Hecho cuando: `uv run pytest -q tests/drive_client_test.py -k escritura` pasa con creación (id y enlace) y reemplazo.
- [ ] **T-16 — Guardar y recuperar el EDR de la conversación** · RF-21, RF-23, RF-24 · ~25 min
  `save_edr` y `get_edr` en `src/services/edr.py` sobre `edr_document`: crea el primero, actualiza el mismo después.
  Hecho cuando: `uv run pytest -q tests/edr_test.py -k guardar` pasa con creación, actualización del mismo documento y fallo de Drive sin fila nueva.
- [ ] **T-17 — Dar las herramientas de EDR al área habilitada** · RF-18, RF-19, RF-22, RF-25, RF-26 · ~30 min
  `leer_edr` y `guardar_edr` en `AreaToolbox` si el área tiene `edr`; el enlace vuelve en el resultado de `consultar_areas`.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k edr` y `uv run pytest -q tests/coordinator_test.py -k edr` pasan con guardado, enlace, colaborador no habilitado y fallo de Drive.

## Fase 7 — Control posterior
- [ ] **T-18 — Contar archivos y Jira como evidencia** · RF-10, RF-30, RF-31, RF-32 · ~25 min
  `AreaAnswer.documents` y bloques de archivo del historial en la evidencia de `review`; el web sigue sin herramientas.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "evidencia_archivo or evidencia_jira or archivo_instrucciones or web_sin_herramientas"` pasa.

## Fase 8 — Cierre
- [ ] **T-19 — Actualizar el README** · RF-27 · ~20 min
  Adjuntos, Jira, EDR, tablas `jira_board`/`project_collaborator`/`edr_document`, `business_area.tools` y properties nuevas.
  Hecho cuando: `grep -c "jira_board\|project_collaborator\|edr_drive_folder_id\|attachment_max_mb" README.md` da al menos 4.
- [ ] **T-20 — Verificación completa y versión 1.5.0** · todos · ~15 min
  `uv run pyright`, `uv run pytest`; versión 1.5.0 en `pyproject.toml`/`uv.lock` (incluye el fix 1.4.1, aún sin publicar).
  Hecho cuando: pyright da 0 errores, pytest no tiene fallos y `grep '^version = "1.5.0"' pyproject.toml` encuentra la línea.

## Fase 9 — Despliegue
- [ ] **T-21 — Configurar Jira, Drive, acceso y prompts** · RF-27 · ~30 min
  Con autorización y respaldo: properties de Jira y `edr_drive_folder_id`, Proyectos con `{jira,edr}`, colaboradores y tableros, y prompts del coordinador y de Proyectos que mencionen archivos, Jira y EDR.
  Hecho cuando: las properties existen, Proyectos tiene `{jira,edr}` y las listas tienen al menos un colaborador y un tablero.
- [ ] **T-22 — Ejecutar la demo manual** · RF-1 a RF-32 · ~30 min
  Los mensajes de los criterios de finalización de la spec en Google Chat, más `jailbreak_check --scope internal`.
  Hecho cuando: cada mensaje da el resultado esperado y `jailbreak_check --scope internal` termina con 0.

## Cobertura
| RF | Tareas |
|---|---|
| RF-1 | T-1, T-4, T-5, T-6, T-7, T-8, T-9, T-10, T-22 |
| RF-2 | T-5, T-8 |
| RF-3 | T-8, T-9 |
| RF-4 | T-10 |
| RF-5 | T-8 |
| RF-6 | T-8 |
| RF-7 | T-7, T-8 |
| RF-8 | T-8, T-10 |
| RF-9 | T-8 |
| RF-10 | T-10, T-18 |
| RF-11 | T-22 (WebSocket sin cambios) |
| RF-12 | T-11, T-13 |
| RF-13 | T-12, T-13 |
| RF-14 | T-11 |
| RF-15 | T-13, T-21 |
| RF-16 | T-12, T-13 |
| RF-17 | T-11 |
| RF-18 | T-14, T-17 |
| RF-19 | T-17 |
| RF-20 | T-14 |
| RF-21 | T-15, T-16 |
| RF-22 | T-17 |
| RF-23 | T-2, T-3, T-15, T-16 |
| RF-24 | T-16 |
| RF-25 | T-17, T-21 |
| RF-26 | T-12, T-13, T-17 |
| RF-27 | T-2, T-3, T-12, T-19, T-21 |
| RF-28 | T-12 |
| RF-29 | T-12, T-13 |
| RF-30 | T-18 |
| RF-31 | T-18 |
| RF-32 | T-13, T-18 |
| RNF-1 | T-22 (respuesta diferida existente) |
| RNF-2 | T-11 |
| RNF-3 | T-4 a T-18 |

| Módulo del plan | Tareas |
|---|---|
| dependencias | T-1 |
| `src/models/`, migración | T-2, T-3 |
| `src/services/document_extractor.py` | T-4 |
| `src/agents/llm.py` (`transcribe`) | T-5 |
| `src/services/chat_api_client.py` | T-6 |
| `src/services/drive_client.py` | T-7, T-15 |
| `src/services/attachments.py` | T-8 |
| `src/interfaces/google_chat.py`, `src/services/google_chat.py` | T-9 |
| `src/services/chat_orchestrator.py` | T-10 |
| `src/services/jira_client.py` | T-11 |
| `src/services/project_access.py` | T-12 |
| `src/agents/tools.py`, `src/agents/graph.py` (`load_catalog`) | T-13, T-17 |
| `src/services/edr.py`, `src/templates/edr.html` | T-14, T-16 |
| `src/agents/coordinator.py` | T-17 |
| `src/agents/sub_agent.py`, `src/agents/graph.py` (evidencia) | T-18 |
| `README.md` | T-19 |
