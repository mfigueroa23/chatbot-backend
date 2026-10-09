# Plan 003 — Temas vigentes, nombre del colaborador y EDR en Google Docs

Spec: [spec.md](spec.md). Parte de la 2.1.0 en `main` (spec 002). Este plan no incluye código.

## 1. Qué cambia en el flujo

```
Google Chat ─ evento (correo, nombre, adjuntos) ─ assistant ─ grafo
   route / synthesize: [system] + historial + [pregunta + <informacion fuente="este mensaje">]      RF-1..RF-6
   sub_agent Proyectos ─ generar_edr ─ agenda run_edr_job y responde al momento                     RF-7, RF-15
                                         │  (segundo plano, sesión propia, tope edr_job_timeout_seconds)
                                         ├─ historial + mensaje actual + EDR actual + épica (leer_ticket)
                                         ├─ modelo → JSON → EdrDocument (1 corrección si es inválido)
                                         ├─ plantilla (property) → HTML → Drive (crea o reemplaza)  RF-10, RF-12
                                         ├─ edr_document (fila)                                     RF-12, RF-13
                                         └─ enlace al historial + mensaje en el hilo (API de Chat)  RF-11, RF-14
```

## 2. Decisiones

- **D1 — Temas junto a la pregunta.** El catálogo ya se lee en cada mensaje (spec 001, RF-23), pero el modelo se
  ancla en lo que dijo antes en el historial. `current_turn` agrega a la última pregunta un bloque «este mensaje»
  con los nombres de los temas vigentes y, en Google Chat, el nombre de quien escribe. Lo que se guarda en el
  historial sigue siendo `question`, así que el bloque no queda en él (RF-3).
- **D2 — El nombre entra como información.** El nombre visible lo escribe cada persona en su cuenta y podría traer
  texto que parezca instrucción. Por eso va dentro del bloque de información y no en el system.
- **D3 — EDR asíncrono dentro del proceso.** `generar_edr` revisa la configuración, agenda con `asyncio.create_task`
  (guardando la referencia) y responde al momento. No se usa una cola: hay un solo pod, y un reinicio pierde el trabajo
  (RNF-6). `RUNNING` (por conversación) impide dos trabajos a la vez en la misma conversación (RF-15).
- **D4 — El trabajo ve la conversación, no el sub-agente.** El sub-agente sigue sin historial (spec 001, RNF-7). El
  trabajo, que es código, lee el historial con su propia sesión. El mensaje actual todavía no está guardado cuando
  empieza, así que viaja en `ToolContext.message` y se agrega si no es el último del historial.
- **D5 — JSON validado en código.** Gemini no admite `$ref` ni `default` en esquemas anidados. El modelo devuelve el
  EDR como JSON en texto, como en la 1.x; se valida con `EdrDocument` y, si falla, se le devuelve el error una sola vez
  (RNF-5).
- **D6 — Épica con la misma herramienta.** La épica se lee con la herramienta `leer_ticket`. Así se reutilizan el
  control de tableros permitidos y el bloque de información (spec 002, RF-19, RF-24).
- **D7 — Drive y Chat con la cuenta de servicio.** Se usa la misma `google_chat_service_account_json`, con el scope de
  Drive para el Doc y `chat.bot` para publicar en el hilo. El hilo sale de `conversation.external_key`, que vale
  `spaces/X/threads/Y` en un space o `spaces/X` en un DM.
- **D8 — Plantilla solo en `property`.** `edr_template_base64` se copia de `chatbot_autofin`. Si falta o no es base64
  válido, `generar_edr` no agenda nada y lo dice (RF-18). Se renderiza con Jinja2 `SandboxedEnvironment` y autoescape,
  porque la plantilla viene de la BD.

## 3. Módulos

```
src/agents/prompts.py              current_turn, TOPICS_CHANGE, PERSON_NAME, NO_PROMISES; edr_messages
src/agents/llm.py                  EdrWriter (contrato)
src/agents/gemini.py               GeminiEdrWriter, gemini_edr_writer(properties)
src/agents/tools/edr.py            generar_edr, leer_edr, RUNNING, background
src/agents/tools/registry.py       ToolContext + conversation_id, chat_key, message
src/models/edr_document.py         EdrDocumentRecord
src/services/edr/document.py       EdrDocument, edr_config, render_edr_html, pending_sections
src/services/edr/store.py          EdrRepository, PgEdrRepository
src/services/edr/job.py            EdrRequest, EdrJobDeps, run_edr_job
src/services/google/drive.py       DriveClient (crear y reemplazar Doc desde HTML)
src/services/google/chat_messages.py  ChatMessenger.post(chat_key, text)
src/utils/exceptions/edr.py        EdrNotConfiguredError, InvalidEdrError
```

## 4. Datos

- Tabla `edr_document`: `id`, `conversation_id` (uuid, FK a `conversation` con `ON DELETE CASCADE`, con índice),
  `drive_file_id`, `web_link`, `title`, `content` (JSONB), `created_at` y `updated_at`. Al borrar una conversación
  vencida se borra su fila; el Doc queda en Drive.
- Prompt `edr_writer` en `agent_prompt`: rol y criterios de redacción. La mecánica (formato JSON y campos) va en código.
- Properties: `edr_job_timeout_seconds` (180) y `edr_history_messages` (30), sembradas.
  - `edr_template_base64` y `edr_drive_folder_id` se copian de la base anterior.
  - `edr_model` es opcional; si no está, se usa `sub_agent_model`.

## 5. Despliegue

1. Migración (`alembic upgrade head` en el contenedor, como hoy).
2. Copiar `edr_template_base64` y `edr_drive_folder_id` de `chatbot_autofin.property` a `asistente_virtual.property`
   (upsert, sin mostrar valores).
3. `uv run python -m src.cli.load_projects_area --boards DAIA --members …` para asignar `generar_edr` y `leer_edr`.

## 6. Riesgos

- La API de Chat con la cuenta de servicio de la app debe aceptar crear mensajes. Si no lo hace, el enlace igual queda
  en el historial y `leer_edr` lo entrega. Se confirma en la demo.
- EDR largos pueden superar 180 s. La property se ajusta sin desplegar.
