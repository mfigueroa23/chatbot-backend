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

Un saludo hace 1 llamada al modelo; una consulta a N áreas, 2 + N. Áreas, FAQ, prompts y configuración viven en la base
de datos y se leen sin caché en cada mensaje: un cambio se aplica desde el siguiente. La especificación está en
[docs/specs/001-virtual-assistant](docs/specs/001-virtual-assistant/spec.md).

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
| `coordinator_model` | Modelo de los coordinadores (decidir y redactar); debe admitir `thinking_budget`, p. ej. un Gemini Flash | — (obligatoria) |
| `sub_agent_model` | Modelo de los sub-agentes de área; mismo requisito | — (obligatoria) |
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
| `POST` | `/api/v1/google-chat/events` | Eventos de la app de Google Chat (complemento de Google Workspace, agente interno). Exige `Authorization: Bearer <ID token>` de la cuenta de servicio del complemento (`401` si falta o no es válido). Responde en el hilo del mensaje; al agregar el asistente a un space o DM responde la bienvenida `internal_welcome` |

## Datos de negocio

El contenido se carga directamente en la base de datos y se aplica desde el siguiente mensaje:

| Tabla | Contenido |
|---|---|
| `business_area` | Un sub-agente por fila activa: `name`, `description` (la usa el coordinador para enrutar), `scope` (`external` = chat web, `internal` = Google Chat), `system_prompt` del área, `tools` y `active` |
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

Las herramientas se programan en código, en el registro `TOOLS` de `src/agents/tools.py` (nombre, descripción, esquema
Pydantic de sus argumentos y función `async`). En la 2.0.0 el registro está vacío. Para habilitar una en un área:

```sql
UPDATE business_area SET tools = ARRAY['nombre_de_la_herramienta'] WHERE name = 'Servicio al Cliente';
```

Un nombre que no está en el registro se ignora con un *warning* en el log.

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
├── agents/                 Coordinador, sub-agentes, grafo de LangGraph, prompts por paso, Gemini y herramientas
├── models/                 Modelos ORM de SQLAlchemy
├── interfaces/             Modelos Pydantic de petición y respuesta
├── routers/                Endpoints HTTP
├── services/               Lógica de negocio y acceso a datos
└── utils/exceptions/       Excepciones propias del proyecto
alembic/                    Migraciones de la base de datos
tests/                      Tests con pytest
```

## Autor

Marco Antonio Figueroa Sanchez

## Licencia

Distribuido bajo la licencia Apache 2.0. Ver [LICENSE](LICENSE).
