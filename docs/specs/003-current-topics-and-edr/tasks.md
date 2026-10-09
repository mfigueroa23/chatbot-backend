# Tareas 003 — Temas vigentes, nombre del colaborador y EDR en Google Docs

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 9/10 hechas

"Verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test se conecta a la BD, a
Drive, a la API de Chat, a Jira ni a Gemini (RNF-3).

## Fase 1 — Temas vigentes y nombre
- [x] **T-1 — Bloque «este mensaje»** · RF-1 a RF-3 · `current_turn` en `route_messages` y `synthesize_messages`;
  `TOPICS_CHANGE` reescrito. Hecho cuando: `prompts_test` comprueba los temas, «ninguno» y que el historial guardado no
  tiene el bloque.
- [x] **T-2 — Nombre del colaborador** · RF-4 a RF-6 · `requester_name_of`, `answer(requester_name=)`,
  `AgentContext.requester_name` y `person` en `route` y `synthesize`. Hecho cuando: `google_chat_test` y
  `assistant_test` comprueban que el nombre llega y que no sale del bloque.

## Fase 2 — EDR
- [x] **T-3 — Modelo, migración y semillas** · RF-12, RF-19 · `EdrDocumentRecord`; migración con la tabla, el prompt
  `edr_writer` y las 2 properties. Hecho cuando: `upgrade`, `downgrade -1` y `upgrade` funcionan en la BD local.
  Aplicada con `upgrade head` en la base remota (2026-10-09); el `downgrade` se revisó con `--sql`, sin correrlo.
- [x] **T-4 — Documento y plantilla** · RF-9, RF-10, RF-18 · `EdrDocument`, `edr_config` y `render_edr_html` (sandbox).
  Hecho cuando: `edr_document_test` cubre base64 inválido, autoescape, sandbox y `StrictUndefined`.
- [x] **T-5 — Drive y mensajes de Chat** · RF-10, RF-11 · `DriveClient` y `ChatMessenger`. Hecho cuando: los tests con
  `MockTransport` comprueban la subida multiparte, el PATCH y el mensaje en el hilo o en el DM.
- [x] **T-6 — Trabajo del EDR** · RF-8 a RF-14, RF-20 · `run_edr_job` y `PgEdrRepository`. Hecho cuando: `edr_job_test`
  cubre crear, actualizar el mismo Doc, la corrección del JSON, una falla de Drive y el enlace en el historial.
- [x] **T-7 — Herramientas y contexto** · RF-7, RF-13, RF-15 a RF-17 · `generar_edr` y `leer_edr`; `ToolContext` con
  `conversation_id`, `chat_key` y `message`. Hecho cuando: `edr_tools_test` cubre agendar, el trabajo en curso, el web
  y la falta de configuración.
- [x] **T-8 — Área Proyectos** · RF-7 · `TOOLS` y `SYSTEM_PROMPT` del CLI. Hecho cuando: `load_projects_area_test`
  sigue verde.

## Fase 3 — Cierre
- [ ] **T-9 — README y despliegue** · copia de las properties, CLI de Proyectos y demo manual (spec, criterios de
  finalización). Hecho: README, migración en la base remota, copia de las 2 properties (idénticas a las de
  `chatbot_autofin`) y CLI de Proyectos (4 herramientas, 21 FAQ; se mantienen 2 colaboradores y el tablero DAIA).
  Falta: desplegar y la demo en Google Chat.
- [x] **T-10 — Versión 2.2.0** · `version = "2.2.0"` en `pyproject.toml` y `uv lock`, en un commit
  `chore(release): Version 2.2.0`. Hecho cuando: `pyproject.toml` dice `2.2.0` y la suite está verde.
