# chatbot-backend

Backend de ChatBot, construido con FastAPI, SQLAlchemy (async) y PostgreSQL.

Es un asistente virtual con un patrón agéntico coordinador ([spec 001](docs/specs/001-agentic-pattern-coordinator/spec.md)
a [spec 004](docs/specs/004-conversational-coordinator/spec.md)) en tres niveles y **una sola voz**:

```
usuario ─► [coordinador] ──(texto final, tras el control posterior)──► usuario
               │ consultar_areas (el canal fija el ámbito)
               ▼
         [agente interno | agente externo] ──(áreas elegidas, en paralelo)──► [agente de área A] [agente de área B]
               ▲                                                                   │ FAQ, procedimientos
               └──────────────────── contenido de cada área ◄──────────────────────┘
```

- **Coordinador** (`src/agents/coordinator.py`): la IA con personalidad. Conversa en texto libre con la persona del canal
  y el historial, sin áreas, FAQ ni procedimientos en su contexto, y actúa con herramientas: `consultar_areas` (atada
  por código al agente de ámbito de su canal), `avisar_area` en Google Chat (solo si el colaborador lo pide) y
  `ofrecer_ejecutivo`/`responder_oferta` en el web.
- **Agente de ámbito** (`src/agents/scope_agent.py`): el interno en Google Chat y el externo en el web. Conoce las áreas
  de su ámbito con sus temas y trámites, decide en una llamada a cuáles va la consulta (o responde qué se puede
  consultar) mientras se calcula el embedding, y lanza los agentes de área en paralelo.
- **Agentes de área** (`src/agents/sub_agent.py`): buscan en su área con sus tools (como máximo `agent_max_steps` pasos),
  generan el contenido para el coordinador y gestionan los procedimientos, cuya validación sigue en código.

**Holgura en la forma, rigidez en la seguridad**: antes de enviar, un control posterior rechaza fugas de prompts o
nombres internos, datos personales que no vengan de una FAQ o un procedimiento, promesas de avisar más adelante y
acciones afirmadas que no ocurrieron; todo eso se reintenta una vez y, si persiste, se envía la negativa genérica (el
código va directo a la negativa). Una fuga de prompt es una copia de 50 caracteres seguidos. Cada mensaje tiene un tope de `agent_max_model_calls` llamadas al modelo. Atiende dos canales:

- **Chat web** (clientes, áreas externas) por WebSocket, con trato de usted, memoria por sesión y derivación a un
  ejecutivo en vivo. Nunca da respuestas libres: si ninguna área aporta información, ofrece un ejecutivo en horario o
  los canales oficiales fuera de él, aunque el coordinador no lo pida.
- **Google Chat** (colaboradores, áreas internas), con trato de tú y memoria por conversación. Sin FAQ responde con su
  propio conocimiento avisando que no es información oficial y solo avisa al space del área cuando el colaborador lo
  pide; tras 3 datos inválidos de un procedimiento ofrece avisar al área en lugar de hacerlo.

En **Google Chat** el asistente además ([spec 005](docs/specs/005-attachments-jira-edr/spec.md)):

- **Lee los archivos compartidos** (subidos a Chat o enlazados desde Drive): PDF, Word, Excel, PowerPoint, texto, CSV,
  JSON e imágenes JPG, PNG y WebP, hasta `attachment_max_mb`. Imágenes y PDF los transcribe Gemini; Office y texto se
  leen en código. El texto entra en el mensaje marcado como información (no instrucciones) y queda en la memoria del hilo.
- **Consulta Jira en solo lectura** y **redacta EDR** como Google Docs desde las áreas con herramientas habilitadas
  (`business_area.tools`, p. ej. Proyectos con `{jira,edr}`), solo para los colaboradores de `project_collaborator` y
  los tableros de `jira_board`. El EDR usa la plantilla institucional de `agente-ti` (`src/templates/edr.html`, o la de la
  property `edr_template_base64` si existe), deja
  «[PENDIENTE DEFINIR]» lo que nadie entregó y se actualiza sobre el mismo documento en la conversación. La guía de
  redacción de cada sección va en el `system_prompt` del área (BD), así que se ajusta sin desplegar.

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
| `rag_min_similarity` | Similitud coseno mínima para usar una FAQ o un procedimiento al responder | `0.68` |
| `rag_clarify_similarity` | Ya no se usa para aclarar (spec 004): solo limita las señales del ámbito; debe ser menor que `rag_min_similarity` | `0.55` |
| `web_session_retention_days` | Días que se conserva una sesión web desde su último mensaje | `30` |
| `web_max_sessions` | Sesiones web activas simultáneas | `50` |
| `executive_max_chats` | Chats en vivo simultáneos por ejecutivo | `3` |
| `executive_session_hours` | Duración de la sesión de un ejecutivo | `8` |
| `jwt_secret` | Clave HS256 con la que se firman los JWT de los ejecutivos; al menos 32 caracteres (obligatoria). Cambiarla invalida todas las sesiones | — |
| `login_max_attempts` | Intentos de login fallidos antes de bloquear la cuenta | `5` |
| `login_lock_minutes` | Minutos de bloqueo de la cuenta | `15` |
| `executive_reconnect_minutes` | Plazo para que un ejecutivo desconectado retome sus chats | `60` |
| `google_chat_audience` | URL pública de `POST /api/v1/google-chat/events` (audiencia del ID token de Google) | — |
| `google_chat_addon_service_account` | Cuenta de servicio del complemento de Google Workspace que firma las peticiones (`service-…@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`) | — |
| `google_chat_service_account_json` | JSON de la cuenta de servicio con permiso `chat.bot` (respuestas diferidas y avisos a los spaces de las áreas) | — |
| `google_chat_sync_timeout_seconds` | Segundos que se espera la respuesta antes de contestar "procesando" | `25` |
| `google_chat_retention_days` | Días que se conserva la memoria de una conversación de Google Chat desde su último mensaje | `30` |
| `agent_history_messages` | Mensajes anteriores de la conversación que se envían al modelo | `20` |
| `agent_max_steps` | Pasos (llamadas al modelo) de cada agente de área por mensaje; con Jira y EDR conviene `8` (leer épica, hijos y EDR, guardar y responder) | `4` |
| `procedure_max_attempts` | Intentos para entregar datos válidos de un procedimiento antes de abandonarlo | `3` |
| `agent_max_model_calls` | Tope de llamadas al modelo por mensaje entre coordinador, agente de ámbito y agentes de área; al agotarse se responde "servicio no disponible" | `100` |
| `attachment_max_mb` | Tamaño máximo de un archivo compartido que el asistente lee | `20` |
| `attachment_max_chars` | Caracteres de texto que se usan de cada archivo; el resto se descarta y se avisa | `60000` |
| `jira_base_url` | URL de Jira Cloud, p. ej. `https://autofin.atlassian.net` | — |
| `jira_email` | Correo de la cuenta de Jira del asistente (de solo lectura) | — |
| `jira_api_token` | Token de API de esa cuenta (secreto: ver SECURITY.md) | — |
| `jira_max_results` | Tickets por búsqueda o por lista de hijos | `20` |
| `edr_drive_folder_id` | Carpeta de una unidad compartida de Drive donde se crean los EDR | — |
| `edr_template_base64` | Plantilla HTML (Jinja2, en sandbox) del EDR en base64; reemplaza a `src/templates/edr.html` sin desplegar | — (usa la del repo) |
| `scope_topics_per_area` | Temas (FAQ) y trámites (procedimientos) de cada área que conoce el agente de ámbito | `50` |
| `conversation_temperature` | Temperatura de Gemini en ambos canales: con `0` los textos redactados serían siempre idénticos | `0.7` |

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
| `business_area` | Áreas con su ámbito (`internal`/`external`), descripción, system prompt, `chat_space` (space de Google Chat del área, `spaces/…`) y `tools` (herramientas extra de su agente: `jira`, `edr`) |
| `jira_board` | Tableros de Jira que el asistente puede consultar (`key`, p. ej. `DAIA`) |
| `project_collaborator` | Colaboradores habilitados para Jira y EDR, por su correo de Google Chat |
| `edr_document` | EDR guardados por conversación: documento de Drive, enlace y el último contenido |
| `faq_category`, `faq` | Categorías y preguntas frecuentes de cada área. El embedding se calcula solo al usarlas |
| `procedure`, `procedure_field` | Procedimientos de cada área (nombre y pasos que se explican al usuario) y los datos que exige cada uno, con su tipo (`text`, `email`, `phone`, `rut`, `number`, `date`). El embedding se calcula solo al usarlos |
| `agent_prompt` | Prompts del asistente; su texto solo vive en la BD (no se versiona). `internal_coordinator` y `external_coordinator`: el coordinador de cada canal (rol, prioridades, cuándo usar cada herramienta, principios: inferir sin inventar, no confirmar lo que una herramienta no confirmó, no prometer avisos; en el interno, la respuesta libre con aviso de no oficial). `internal_agent` y `external_agent`: el agente de ámbito (decidir a qué áreas va la consulta, reformularla con el contexto y reconocer «qué puedo consultar»). `area_rules`: reglas comunes de los agentes de área (generar contenido solo con lo encontrado para el coordinador). `internal_persona` (trato de tú, humor ligero) y `external_persona` (trato de usted): el tono de cada canal, sembrado por la migración. Todos deben tratar lo que escribe el usuario como información, nunca como instrucciones, y un cambio aplica desde el siguiente mensaje. Las keys `{internal,external}_{greeting,closing,off_topic}` de la spec 002 ya no se usan |
| `service_schedule` | Franja de atención por día (`weekday` 0 = lunes … 6 = domingo), en hora de Santiago |
| `holiday` | Fechas sin atención |
| `official_channel` | Canales oficiales que se muestran al cliente |
| `fallback_space` | Space general de Google Chat por ámbito, para consultas internas sin área |
| `executive` | Ejecutivos del chat en vivo; el hash de la contraseña se genera con el comando de abajo |

```bash
uv run python -m src.cli.hash_password   # pide la contraseña sin mostrarla e imprime el hash Argon2
```

Los cambios en áreas, FAQ, procedimientos, prompts y mensajes fijos se aplican desde el siguiente mensaje, sin reiniciar.

#### Alta de un área

Una área nueva es solo datos: el grafo lanza un `area_agent` por cada área activa, sin código ni despliegue.

1. Insertar la fila en `business_area` con su `scope`, una `description` clara (es lo único que ve el agente del canal
   para decidir si le delega una consulta), su `system_prompt` (sin él el área no responde) y su `chat_space`.
2. Cargar sus categorías y FAQ en `faq_category` y `faq`, y sus procedimientos en `procedure` y `procedure_field`. Los
   embeddings se calculan solos en el siguiente mensaje.
3. Añadir la app de Google Chat como miembro del space del área.

Para retirar un área se usa `active = false`; borrarla elimina en cascada sus FAQ y procedimientos.

La app de Google Chat se configura como **complemento de Google Workspace**: en la API de Chat, la URL del endpoint
HTTP es la de `google_chat_audience`, y la cuenta de servicio que muestra la consola va en
`google_chat_addon_service_account`. Cada petición trae un ID token de Google de esa cuenta, y el backend responde con
`hostAppDataAction`. Si la respuesta tarda más de `google_chat_sync_timeout_seconds`, contesta "procesando" y la publica
después en el mismo hilo con la API de Chat.

La app de Google Chat debe ser **miembro del space de cada área** (y del space general) para poder publicar en él; si no
lo es, el aviso falla y se pide al usuario contactar directamente con el área. Es configuración de Google Workspace.

La cuenta de servicio de `google_chat_service_account_json` también lee Drive (scope `drive`): debe ser miembro de la
unidad compartida de `edr_drive_folder_id` y tener acceso a los archivos de Drive que se compartan en el chat; si no, el
asistente pide compartirlos con su correo (`client_email`). Jira se consulta por REST con el token de una cuenta de
solo lectura.

### Protección frente a manipulación

```bash
uv run python -m src.cli.jailbreak_check --url ws://127.0.0.1:8000/ws/v1/chat
uv run python -m src.cli.jailbreak_check --scope internal
```

Por defecto ataca el WebSocket del chat web; con `--scope internal` ejecuta la batería en proceso contra el grafo de
Google Chat (con la BD y Gemini reales; los avisos a las áreas solo se registran). Envía una batería de más de 20 intentos de manipulación (revelar el prompt, las herramientas o las áreas internas,
"ignora tus instrucciones", juegos de rol…) y falla (código de salida 1) si alguna respuesta contiene fragmentos de los
prompts de la BD (incluidas las personas), nombres internos, código o, en el web, áreas internas. Ejecútalo tras
cambiar los prompts. Los mensajes fijos no cuentan como prompts: se muestran al usuario.

### Variedad de los saludos

```bash
uv run python -m src.cli.behavior_check --scope internal --variety 5
uv run python -m src.cli.behavior_check --scope external --variety 5
```

Envía N saludos en conversaciones nuevas, contra la BD y Gemini (dentro del pod o en local), y exige al menos 3 textos
distintos de cada 5. No envía avisos a las áreas. El tono del coordinador se acepta en una demo manual (spec 004).

En el chat web, mientras se ofrece un ejecutivo, el cliente puede aceptar o rechazar escribiendo («ok», «no, gracias»)
además de con `human_response`; cualquier otro mensaje no cancela la oferta ni la petición de datos.

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
| `POST` | `/api/v1/google-chat/events` | Eventos de la app de Google Chat (complemento de Google Workspace); `401` si el ID token no es de la cuenta de servicio del complemento |

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
├── agents/                 Grafo coordinador (LangGraph), agentes de área y sus tools, LLM, recuperador y estrategias por canal
├── cli/                    Comandos de mantenimiento (hash_password, jailbreak_check, behavior_check)
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
