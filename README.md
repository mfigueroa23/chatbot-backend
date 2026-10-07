# chatbot-backend

Backend de ChatBot, construido con FastAPI, SQLAlchemy (async) y PostgreSQL.

Es un asistente virtual con un patrón agéntico coordinador ([spec 001](docs/specs/001-agentic-pattern-coordinator/spec.md)):
un grafo de LangGraph por ámbito clasifica cada mensaje y lo delega en sub-agentes por área de negocio. Cada sub-agente
usa tools para consultar las FAQ y los procedimientos de su área (RAG con pgvector y Gemini), notificar al área y, en
el chat web, derivar a un ejecutivo; un guardarraíl en código descarta las respuestas que no se apoyan en lo recuperado.
Atiende dos canales:

- **Chat web** (clientes, áreas externas) por WebSocket, con memoria por sesión y derivación a un ejecutivo en vivo.
- **Google Chat** (colaboradores, áreas internas), con memoria por conversación y aviso al space de Google Chat del área cuando no hay respuesta.

Si existe un procedimiento, el asistente explica los pasos, pide los datos que exige (validados en código) y publica la
solicitud en el space del área para que una persona la ejecute.

## Requisitos

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL con la extensión [pgvector](https://github.com/pgvector/pgvector) instalada en el servidor

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

Las properties se leen de la base de datos en cada uso, así que un cambio en la tabla se aplica de inmediato sin reiniciar la aplicación.

Properties usadas actualmente:

| Key | Uso | Por defecto |
|---|---|---|
| `service_name` | Nombre del servicio que devuelve `/health` | — |
| `gemini_model` | Modelo de Gemini de los agentes (obligatoria) | — |
| `gemini_api_key` | API key de Gemini (obligatoria) | — |
| `gemini_embedding_model` | Modelo de embeddings, p. ej. `gemini-embedding-001` (obligatoria) | — |
| `llm_timeout_seconds` | Tiempo máximo de espera de cada llamada a Gemini | `20` |
| `rag_top_k` | FAQ recuperadas por área | `4` |
| `rag_min_similarity` | Similitud coseno mínima para usar una FAQ | `0.68` |
| `web_session_retention_days` | Días que se conserva una sesión web desde su último mensaje | `30` |
| `web_max_sessions` | Sesiones web activas simultáneas | `50` |
| `executive_max_chats` | Chats en vivo simultáneos por ejecutivo | `3` |
| `executive_session_hours` | Duración de la sesión de un ejecutivo | `8` |
| `jwt_secret` | Clave HS256 con la que se firman los JWT de los ejecutivos; al menos 32 caracteres (obligatoria). Cambiarla invalida todas las sesiones | — |
| `login_max_attempts` | Intentos de login fallidos antes de bloquear la cuenta | `5` |
| `login_lock_minutes` | Minutos de bloqueo de la cuenta | `15` |
| `executive_reconnect_minutes` | Plazo para que un ejecutivo desconectado retome sus chats | `60` |
| `google_chat_audience` | URL pública de `POST /api/v1/google-chat/events` (audiencia del token de Google) | — |
| `google_chat_service_account_json` | JSON de la cuenta de servicio con permiso `chat.bot` (respuestas diferidas y avisos a los spaces de las áreas) | — |
| `google_chat_sync_timeout_seconds` | Segundos que se espera la respuesta antes de contestar "procesando" | `25` |
| `google_chat_retention_days` | Días que se conserva la memoria de una conversación de Google Chat desde su último mensaje | `30` |
| `agent_max_steps` | Pasos máximos (llamadas al modelo) del bucle de tools de cada sub-agente | `4` |
| `procedure_max_attempts` | Intentos para entregar datos válidos de un procedimiento antes de abandonarlo | `3` |

> Los valores de la tabla `property` se guardan en texto plano. Revisa [SECURITY.md](SECURITY.md) antes de guardar secretos.

## Instalación

La extensión `vector` no es de confianza (`trusted`), así que un superusuario debe instalarla en el servidor y crearla
en la base de datos una vez, antes de la primera migración:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

```bash
uv sync
uv run alembic upgrade head
```

### Datos de negocio

Las tablas de negocio empiezan vacías y se cargan directamente en la base de datos:

| Tabla | Contenido |
|---|---|
| `business_area` | Áreas con su ámbito (`internal`/`external`), descripción, system prompt y `chat_space` (space de Google Chat del área, `spaces/…`) |
| `faq_category`, `faq` | Categorías y preguntas frecuentes de cada área. El embedding se calcula solo al usarlas |
| `procedure`, `procedure_field` | Procedimientos de cada área (nombre y pasos que se explican al usuario) y los datos que exige cada uno, con su tipo (`text`, `email`, `phone`, `rut`, `number`, `date`). El embedding se calcula solo al usarlos |
| `agent_prompt` | Prompts con las keys `classifier` (clasificador), `internal_agent` y `external_agent` (agente de cada canal, incluye cómo combinar respuestas de varias áreas) y `area_rules` (reglas comunes de todos los sub-agentes). El texto recomendado, con las cláusulas de protección frente a manipulación, está en [`prompts.md`](docs/specs/001-agentic-pattern-coordinator/prompts.md) |
| `service_schedule` | Franja de atención por día (`weekday` 0 = lunes … 6 = domingo), en hora de Santiago |
| `holiday` | Fechas sin atención |
| `official_channel` | Canales oficiales que se muestran al cliente |
| `fallback_space` | Space general de Google Chat por ámbito, para consultas internas sin área |
| `executive` | Ejecutivos del chat en vivo; el hash de la contraseña se genera con el comando de abajo |

```bash
uv run python -m src.cli.hash_password   # pide la contraseña sin mostrarla e imprime el hash Argon2
```

Los cambios en áreas, FAQ, procedimientos y prompts se aplican desde el siguiente mensaje, sin reiniciar.

La app de Google Chat debe ser **miembro del space de cada área** (y del space general) para poder publicar en él; si no
lo es, el aviso falla y se pide al usuario contactar directamente con el área. Es configuración de Google Workspace.

### Protección frente a manipulación

```bash
uv run python -m src.cli.jailbreak_check --url ws://127.0.0.1:8000/ws/v1/chat
```

Envía una batería de más de 20 intentos de manipulación (revelar el prompt, las herramientas o las áreas internas,
"ignora tus instrucciones", juegos de rol…) y falla (código de salida 1) si alguna respuesta contiene fragmentos de los
prompts de la BD, nombres de herramientas o áreas internas. Ejecútalo tras cambiar los prompts.

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
| `POST` | `/api/v1/executives/login` | Login de ejecutivo: `{username, password}` → `{token, expires_at}` (`token` es un JWT); `401` genérico |
| `POST` | `/api/v1/executives/logout` | Revoca la sesión del `Authorization: Bearer` |
| `GET` | `/api/v1/live-chats?status=waiting` | Chats en espera de la cola web, en orden de llegada (Bearer) |
| `POST` | `/api/v1/live-chats/{id}/take` | Toma un chat en espera; devuelve el resumen del cliente (`409` si ya está asignado o se alcanzó el máximo) |
| `POST` | `/api/v1/live-chats/{id}/close` | Cierra el chat (solo el ejecutivo asignado) |
| `POST` | `/api/v1/google-chat/events` | Eventos de interacción de Google Chat; `401` si el token de Google no es válido |

| WebSocket | Descripción |
|---|---|
| `/ws/v1/chat?session_id=<uuid opcional>` | Chat web del cliente: bot, oferta de ejecutivo, datos de contacto, cola y chat en vivo |
| `/ws/v1/executive` | Chat en vivo del ejecutivo; el primer mensaje debe ser `{type: "auth", token}` (si no, cierra con `4401`) |

Los endpoints protegidos declaran el esquema HTTP Bearer (JWT) en OpenAPI: en `/docs`, el botón **Authorize** permite
pegar el token del login. El JWT se valida también contra la sesión guardada, así que el logout lo revoca.

Los mensajes de cada WebSocket están en la sección 4 del [plan](docs/specs/001-agentic-pattern-coordinator/plan.md).

## Migraciones

```bash
uv run alembic revision --autogenerate -m "descripción del cambio"
uv run alembic upgrade head
uv run alembic downgrade -1
```

Revisa siempre el archivo generado en `alembic/versions/` antes de aplicarlo.

Las tablas `checkpoint*` del checkpointer de LangGraph las crea una migración propia con una copia fija de
`AsyncPostgresSaver.MIGRATIONS` (y `alembic/env.py` las excluye de autogenerate). Si al actualizar
`langgraph-checkpoint-postgres` cambian sus migraciones, hay que añadir una migración de Alembic con las nuevas.

## Tests

```bash
uv run pytest
```

Los tests nunca se conectan a la base de datos: reemplazan la sesión con `app.dependency_overrides`. Igual necesitan las variables `DB_*` (del `.env` o del entorno) porque `Settings` las exige al importar la app.

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
├── agents/                 Grafo coordinador (LangGraph), LLM, recuperador de FAQ y estrategias por canal
├── cli/                    Comandos de mantenimiento (hash_password)
├── config.py               Settings leídos del .env
├── database/session.py     Engine y sesión por request (SessionDep)
├── models/                 Modelos ORM de SQLAlchemy
├── interfaces/             Modelos Pydantic de respuesta
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
