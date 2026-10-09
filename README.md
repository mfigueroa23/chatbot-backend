# chatbot-backend

Backend del asistente virtual, construido con FastAPI, SQLAlchemy (async), PostgreSQL con pgvector, LangGraph y Gemini.

El asistente sigue el [patrón de coordinador](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system?hl=es-419#coordinator-pattern):

- **Agente externo** (chat web, clientes) y **agente interno** (Google Chat, colaboradores): cada uno es un coordinador
  que solo conoce las áreas activas de su canal.
- El coordinador analiza la consulta y la divide en **subtareas**, una por área. Saludos, temas ajenos y «¿qué puedo
  consultar?» los responde él mismo.
- Cada subtarea va al **sub-agente** de su área, en paralelo. El sub-agente responde solo con las FAQ de su área
  (búsqueda por similitud en pgvector) y sus herramientas.
- El coordinador redacta una sola respuesta con los resultados. Si un área no tiene información, lo dice y no inventa.
- Cada sub-agente puede **volver a buscar** en las FAQ de su área con otras palabras (`buscar_faq`) y, si la consulta es
  ambigua, devuelve las interpretaciones posibles para que el coordinador pregunte a cuál se refiere la persona.
- Un área puede tener **herramientas en código** (por ejemplo, Jira en solo lectura para Proyectos) y herramientas de
  **servidores MCP**, restringidas si hace falta a una lista de colaboradores habilitados.
- En Google Chat el asistente **lee los archivos subidos** (fotos, PDF, Word, Excel, PowerPoint y texto, hasta 20 MB).
- En cada mensaje el coordinador recibe, junto a la pregunta, los **temas vigentes** y, en Google Chat, el **nombre** de
  quien escribe: si se suman áreas durante la conversación, lo cuenta en vez de repetir lo que dijo antes.
- El área Proyectos **genera el EDR** como Google Doc con la plantilla institucional, en segundo plano: responde al
  momento y publica el enlace en el mismo hilo cuando el documento está listo.

Un saludo hace 1 llamada al modelo; una consulta a N áreas, 2 + N. Áreas, FAQ, prompts y configuración viven en la base
de datos y se leen sin caché en cada mensaje: un cambio se aplica desde el siguiente. La especificación está en
[docs/specs/001-virtual-assistant](docs/specs/001-virtual-assistant/spec.md) y
[docs/specs/002-tools-and-mcp](docs/specs/002-tools-and-mcp/spec.md) y
[docs/specs/003-current-topics-and-edr](docs/specs/003-current-topics-and-edr/spec.md).

## Requisitos

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL con la extensión [pgvector](https://github.com/pgvector/pgvector) (p. ej. la imagen `pgvector/pgvector:pg17`)

## Configuración

La configuración se divide en dos lugares:

| Dónde | Qué contiene |
|---|---|
| `.env` | Solo la conexión a la base de datos (`DB_*`) y `LOG_LEVEL` |
| Tabla `property` | Todo el resto de la configuración de la aplicación (pares `key` / `value`) |

Crea el `.env` a partir del ejemplo y completa los valores:

```bash
cp .env.example .env
```

| Variable | Descripción | Por defecto |
|---|---|---|
| `DB_HOST` | Host de PostgreSQL | — |
| `DB_PORT` | Puerto de PostgreSQL | — |
| `DB_USER` | Usuario | — |
| `DB_PASSWORD` | Contraseña | — |
| `DB_NAME` | Nombre de la base de datos | — |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL` (en mayúsculas) | `INFO` |

Las properties **no se cachean**: cada mensaje lee todas con una sola consulta y usa esa foto en todos sus pasos. Un
cambio en la tabla se aplica desde el siguiente mensaje, sin reiniciar y en todas las réplicas a la vez.

Properties usadas actualmente. Las que tienen valor por defecto las siembra la migración `seed assistant defaults`;
las obligatorias se cargan a mano:

| Key | Uso | Por defecto |
|---|---|---|
| `service_name` | Nombre del servicio que devuelve `/health` | — |
| `gemini_api_key` | API key de Gemini (secreta: ver SECURITY.md) | — (obligatoria) |
| `coordinator_model` | Modelo de los coordinadores (decidir y redactar), p. ej. `gemini-3.5-flash-lite`; debe admitir `thinking_level` (Gemini 3.x) | — (obligatoria) |
| `sub_agent_model` | Modelo de los sub-agentes de área, p. ej. `gemini-3.1-flash-lite`; mismo requisito | — (obligatoria) |
| `embedding_model` | Modelo de embeddings de las FAQ, con salida de 768 dimensiones (p. ej. `gemini-embedding-001`) | — (obligatoria) |
| `max_areas_per_message` | Máximo de áreas (subtareas) por mensaje | `3` |
| `faqs_per_search` | FAQ que recibe cada sub-agente | `5` |
| `history_messages` | Mensajes anteriores de la conversación que ve el coordinador | `10` |
| `conversation_retention_days` | Días sin mensajes tras los que se borra una conversación | `30` |
| `response_timeout_seconds` | Tiempo máximo de un mensaje; debe ser menor que los 30 s de Google Chat | `20` |
| `sub_agent_timeout_seconds` | Tiempo máximo de cada sub-agente; si se excede, su parte queda sin información | `6` |
| `sub_agent_max_steps` | Llamadas al modelo de un sub-agente con herramientas antes de forzar la respuesta | `3` |
| `google_chat_audience` | URL pública de `POST /api/v1/google-chat/events` (audiencia del ID token de Google) | — |
| `google_chat_addon_service_account` | Cuenta de servicio del complemento de Google Workspace que firma los eventos (`service-…@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`) | — |
| `google_chat_service_account_json` | JSON de la cuenta de servicio de la app de Chat (secreto: ver SECURITY.md). Descarga los archivos subidos a Google Chat (scope `chat.bot`), publica el enlace del EDR en el hilo (`chat.bot`) y guarda el EDR en Drive (`drive`). Sin ella, cada archivo se responde como «no se pudo leer» y no se generan EDR | — |
| `file_max_mb` | Tamaño máximo de un archivo; la descarga se corta al pasarlo | `20` |
| `file_max_chars` | Texto que se usa de cada archivo; si es más largo, se lee una parte y se avisa | `30000` |
| `file_response_timeout_seconds` | Tiempo máximo de un mensaje con archivos; debe ser menor que los 30 s de Google Chat | `27` |
| `jira_base_url` | URL de Jira Cloud, p. ej. `https://autofin.atlassian.net` | — |
| `jira_email` | Cuenta de Jira del asistente, de solo lectura | — |
| `jira_api_token` | Token de API de esa cuenta (secreto: ver SECURITY.md) | — |
| `jira_max_results` | Tickets por búsqueda o por lista de hijos | `20` |
| `jira_timeout_seconds` | Tiempo máximo de cada llamada a Jira | `5` |
| `mcp_timeout_seconds` | Tiempo máximo para conectar, listar o llamar a un servidor MCP | `5` |
| `edr_template_base64` | Plantilla HTML (Jinja2) del EDR en base64; se copia de la base anterior (ver «EDR del área Proyectos») | — |
| `edr_drive_folder_id` | Carpeta de Drive donde se crean los EDR, compartida con la cuenta de servicio | — |
| `edr_model` | Modelo que redacta el EDR; si no está, se usa `sub_agent_model` | — |
| `edr_job_timeout_seconds` | Tiempo máximo para redactar y guardar un EDR en segundo plano | `180` |
| `edr_history_messages` | Mensajes de la conversación que ve el redactor del EDR | `30` |

Si falta `gemini_api_key` o un modelo, el asistente responde «no disponible» y registra qué clave falta, nunca su valor.

> Los valores de la tabla `property` se guardan en texto plano. Revisa [SECURITY.md](SECURITY.md) antes de guardar secretos.

## Instalación

```bash
uv sync
uv run alembic upgrade head
```

La migración ejecuta `CREATE EXTENSION IF NOT EXISTS vector`, que requiere superusuario. Si el usuario de la aplicación
no lo es, un administrador crea la extensión antes en la base de datos:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Ejecución

```bash
uv run fastapi dev   # desarrollo, con recarga automática
uv run fastapi run   # producción
```

Documentación interactiva de la API: <http://127.0.0.1:8000/docs>

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Liveness: responde `true` si el proceso está vivo, sin consultar la base de datos |
| `GET` | `/health` | Verifica la base de datos. `200` si está disponible, `503` si no |
| `POST` | `/api/v1/chat` | Chat web (agente externo). Cuerpo `{session_id?, message}` → `{session_id, reply}`. Sin `session_id`, o con uno que no existe, crea una sesión nueva. Mensaje vacío, de más de 5000 caracteres o modelo caído: `200` con el aviso en `reply`. `503` si la base de datos no responde |
| `POST` | `/api/v1/google-chat/events` | Eventos de la app de Google Chat (complemento de Google Workspace, agente interno). Exige `Authorization: Bearer <ID token>` de la cuenta de servicio del complemento (`401` si falta o no es válido). Identifica al colaborador por el correo del evento y lee los archivos subidos al mensaje. Responde en el hilo del mensaje; al agregar el asistente a un space o DM responde la bienvenida `internal_welcome` |

## Datos de negocio

El contenido se carga directamente en la base de datos y se aplica desde el siguiente mensaje:

| Tabla | Contenido |
|---|---|
| `business_area` | Un sub-agente por fila activa: `name`, `description` (la usa el coordinador para enrutar), `scope` (`external` = chat web, `internal` = Google Chat), `system_prompt` del área, `tools` (herramientas en código), `mcp_servers` (servidores MCP) y `active` |
| `area_member` | Colaboradores habilitados para las herramientas de un área (`area_id`, `email` en minúsculas). Un área sin filas ofrece sus herramientas a todo su canal; sus FAQ siempre son para todos |
| `jira_board` | Tableros de Jira permitidos (`key`, `active`): las búsquedas y lecturas se acotan a ellos |
| `mcp_server` | Servidores MCP remotos (*streamable HTTP*): `name`, `url`, `credential_key` (nombre de la property con el token Bearer), `allowed_tools` (solo esas herramientas llegan al sub-agente; vacía = ninguna) y `active` |
| `faq_category` | Categorías de FAQ de cada área; se muestran cuando preguntan «¿qué puedo consultar?» |
| `faq` | Preguntas y respuestas (`active`). El embedding se genera solo la primera vez que se busca en su área después de crearla o editarla |
| `agent_prompt` | `external_coordinator`, `internal_coordinator` (rol, tono y reglas de cada coordinador), `sub_agent_rules` (reglas comunes de los sub-agentes) e `internal_welcome` (presentación en Google Chat) |
| `conversation`, `message` | Historial de cada sesión web y de cada hilo de Google Chat; se borra tras `conversation_retention_days` sin mensajes |

### Alta de un área

```sql
INSERT INTO business_area (name, description, scope, system_prompt)
VALUES ('Servicio al Cliente', 'Pagos de cuotas, prepagos, seguros y certificados', 'external',
        'Eres el especialista de Servicio al Cliente. Tono cordial y claro.');

INSERT INTO faq_category (area_id, name)
SELECT id, 'Pagos' FROM business_area WHERE name = 'Servicio al Cliente';

INSERT INTO faq (category_id, question, answer)
SELECT c.id, '¿Cómo pago mi cuota?', 'Puede pagar en la web, en la app o en cualquier sucursal.'
FROM faq_category c JOIN business_area a ON a.id = c.area_id
WHERE a.name = 'Servicio al Cliente' AND c.name = 'Pagos';
```

Para desactivar un área o una FAQ, `UPDATE … SET active = false`.

### Herramientas de un área

Todos los sub-agentes tienen `buscar_faq`, que vuelve a buscar en las FAQ de su propia área. Las demás herramientas se
programan en código con `code_tool` (`src/agents/tools/registry.py`) y se registran por nombre en
`src/agents/tools/available.py`. Hoy hay cuatro: `leer_ticket` y `buscar_tickets` (Jira en solo lectura), y
`generar_edr` y `leer_edr` (EDR en Google Docs).

```sql
-- Herramientas de Jira y del EDR para el área Proyectos, solo para dos JP, sobre el tablero DAIA
UPDATE business_area SET tools = ARRAY['leer_ticket', 'buscar_tickets', 'generar_edr', 'leer_edr'] WHERE name = 'Proyectos';
INSERT INTO area_member (area_id, email)
SELECT id, unnest(ARRAY['jp1@autofin.cl', 'jp2@autofin.cl']) FROM business_area WHERE name = 'Proyectos';
INSERT INTO jira_board (key) VALUES ('DAIA');
```

Un nombre que no está en el registro se ignora con un *warning* en el log. A un colaborador no habilitado el sub-agente
no le entrega las herramientas: le dice que esa función no está habilitada para él.

### Servidores MCP de un área

```sql
INSERT INTO mcp_server (name, url, credential_key, allowed_tools)
VALUES ('atlassian', 'https://mcp.example.com/mcp', 'atlassian_mcp_token', ARRAY['getJiraIssue']);
UPDATE business_area SET mcp_servers = ARRAY['atlassian'] WHERE name = 'Proyectos';
-- y la credencial en property: atlassian_mcp_token = <token> (ver SECURITY.md)
```

Solo las herramientas de `allowed_tools` llegan al sub-agente, aunque el servidor exponga otras. Si el servidor no
responde o excede `mcp_timeout_seconds`, el área sigue con sus FAQ y sus herramientas en código.

### Archivos en Google Chat

El asistente lee los archivos **subidos** al mensaje (no los enlaces de Drive): JPG, PNG, WebP y PDF los transcribe
Gemini; Word, Excel, PowerPoint, texto, Markdown, CSV y JSON se extraen en código. El texto entra al mensaje marcado como
información, queda en el historial de la conversación y sirve para las preguntas siguientes. Un archivo de más de
`file_max_mb`, en otro formato o que falla al leerse se le avisa al colaborador.

### EDR del área Proyectos

`generar_edr` revisa la configuración, agenda un trabajo en segundo plano y responde al momento. El trabajo redacta el
EDR con la conversación (incluidos los archivos), la épica de Jira y el EDR actual, usando el prompt `edr_writer` de
`agent_prompt`. Después lo renderiza con `edr_template_base64`, crea o actualiza el Google Doc en `edr_drive_folder_id`,
lo guarda en `edr_document` y publica el enlace en el hilo. `leer_edr` entrega el título, el enlace y las secciones
pendientes. Hay un solo EDR en curso por conversación, y si el pod se reinicia, el trabajo se pierde y hay que volver
a pedirlo.

La plantilla y la carpeta son las de la 1.x. Se copian una vez desde la base anterior (`chatbot_autofin`) con un
upsert de esas dos filas de `property`, sin mostrar sus valores. Para cambiar la plantilla, se codifica el HTML en
base64 y se actualiza la fila; no hace falta desplegar.

## Migraciones

```bash
uv run alembic revision --autogenerate -m "descripción del cambio"
uv run alembic upgrade head
uv run alembic downgrade -1
```

Revisa siempre el archivo generado en `alembic/versions/` antes de aplicarlo.

## Tests

```bash
uv run pytest
```

Los tests nunca se conectan a la base de datos, a Google ni a Gemini: reemplazan las dependencias con
`app.dependency_overrides` y usan los dobles de `tests/fakes.py`. Igual necesitan las variables `DB_*` (del `.env` o del entorno) porque `Settings` las exige al importar la app.

## CI/CD

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `.github/workflows/test.yaml` | Push a cualquier rama y PR a `main` | `pyright` + `pytest` |
| `.github/workflows/release.yaml` | Push a `main` | Verifica, publica la imagen en Docker Hub (`amd64` y `arm64`) y la despliega en Kubernetes (`deployment/chatbot-backend`, namespace `chatbot`) |

Configuración necesaria en GitHub:

| Tipo | Nombre | Uso |
|---|---|---|
| Variable | `DOCKERHUB_USERNAME` | Usuario de Docker Hub |
| Secret | `DOCKERHUB_TOKEN` | Token de Docker Hub |
| Secret | `LOCAL_NETWORK` | Service key de Twingate para llegar al cluster |
| Secret | `KUBE_CONFIG` | kubeconfig del cluster |

Las migraciones **no** se ejecutan en el pipeline: el contenedor las aplica al arrancar. `entrypoint.sh` ejecuta `alembic upgrade head` (no hace nada si la base de datos ya está en la última migración) y luego inicia la API. Si la migración falla, el contenedor no arranca. Con varias réplicas, un advisory lock de PostgreSQL en `alembic/env.py` hace que solo una las aplique a la vez.

## Estructura

```
main.py                     App FastAPI, lifespan y configuración de logs
entrypoint.sh               Entrypoint del contenedor: aplica migraciones y arranca la API
src/
├── config.py               Settings leídos del .env
├── database/session.py     Engine y sesión por request (SessionDep)
├── agents/                 Coordinador, sub-agentes, grafo de LangGraph, prompts por paso y Gemini
│   └── tools/              Registro de herramientas, acceso, buscar_faq, Jira, EDR y adaptador MCP
├── models/                 Modelos ORM de SQLAlchemy
├── interfaces/             Modelos Pydantic de petición y respuesta
├── routers/                Endpoints HTTP
├── services/               Lógica de negocio y acceso a datos
│   ├── google/             Token del complemento, evento, cuenta de servicio, adjuntos, Drive y mensajes de Chat
│   ├── edr/                EDR: documento y plantilla, repositorio y trabajo en segundo plano
│   ├── files/              Formatos, extractores de Office y texto, y lectura de adjuntos
│   ├── jira/               Cliente de solo lectura, JQL acotado y tableros permitidos
│   └── mcp/                Cliente de servidores MCP
└── utils/exceptions/       Excepciones propias del proyecto
alembic/                    Migraciones de la base de datos
tests/                      Tests con pytest
```

## Autor

Marco Antonio Figueroa Sanchez

## Licencia

Distribuido bajo la licencia Apache 2.0. Ver [LICENSE](LICENSE).
