# AGENTS.md — chatbot-backend

## Proyecto
Backend de un asistente virtual basado en un patrón agéntico coordinador: un agente
coordinador recibe la conversación y delega en agentes especializados. API HTTP en FastAPI, SQLAlchemy 2 async
(asyncpg) sobre PostgreSQL y migraciones con Alembic. Se despliega como imagen Docker en Kubernetes
(namespace `chatbot`) mediante GitHub Actions.
Capas: `routers/` (HTTP) → `services/` (lógica y acceso a datos) → `models/` (ORM); `interfaces/` (Pydantic
de respuesta), `utils/exceptions/` (excepciones propias), `database/session.py` (`SessionDep`).

## Comandos
- Instalar: `uv sync && uv run alembic upgrade head`
- Ejecutar: `uv run fastapi dev` (producción: `uv run fastapi run`)
- Tests: `uv run pytest`
- Lint/tipos: `uv run pyright`
- Migración nueva: `uv run alembic revision --autogenerate -m "<descripción>"`

## Estilo y convenciones
- Python 3.14, type hints en todo; pyright sin errores.
- Identificadores en inglés (snake_case funciones/módulos, PascalCase clases); logs, mensajes de error y
  campos de respuesta al usuario en español.
- Endpoints async con `SessionDep`; los services lanzan excepciones de `src/utils/exceptions/` y los routers
  las traducen a códigos HTTP.
- Logger por módulo: `logging.getLogger(__name__)` bajo el logger `src`.
- Tests en `tests/` con nombre `*_test.py`.
- Responder al usuario en español.

## Reglas
- Lee docs/constitution.md y la spec activa (`docs/specs/<feature>/spec.md`) antes de tocar código.
- En `.env` solo van `DB_*` y `LOG_LEVEL`; cualquier otra configuración va en la tabla `property` (`get_property`).
- Ningún test se conecta a la base de datos: usar `app.dependency_overrides[get_session]`.
- No añadir dependencias, workflows de CI ni cambiar el esquema sin preguntar; todo cambio de esquema va con
  migración de Alembic revisada a mano.
- No modificar migraciones ya existentes en `alembic/versions/`.
- No guardar secretos en el código ni en `.env.example`.

## Al terminar cualquier tarea
- Ejecutar `uv run pyright` y `uv run pytest` y mostrar el resultado.
- Actualizar README.md si cambian endpoints, properties o variables de entorno.
