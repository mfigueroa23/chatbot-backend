import asyncio
from logging.config import fileConfig
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from src.config import settings
from src.models.base import Base
from src.models.agent_prompt import AgentPrompt
from src.models.business_area import BusinessArea
from src.models.chat_thread import ChatThread
from src.models.edr_document import EdrDocumentRecord
from src.models.executive import Executive
from src.models.executive_session import ExecutiveSession
from src.models.fallback_space import FallbackSpace
from src.models.faq import Faq
from src.models.faq_category import FaqCategory
from src.models.holiday import Holiday
from src.models.jira_board import JiraBoard
from src.models.live_chat import LiveChat
from src.models.live_chat_message import LiveChatMessage
from src.models.official_channel import OfficialChannel
from src.models.procedure import Procedure
from src.models.procedure_field import ProcedureField
from src.models.project_collaborator import ProjectCollaborator
from src.models.property import Property
from src.models.service_schedule import ServiceSchedule
from src.models.web_session import WebSession

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Advisory lock de PostgreSQL: si arrancan varias réplicas a la vez, solo una aplica las migraciones
# y las demás esperan a que termine (y luego ven la base de datos ya al día).
MIGRATION_LOCK_ID = 727_100_001

def include_object(object, name, type_, reflected, compare_to) -> bool:
    # Las tablas del checkpointer de LangGraph no tienen modelo: sin esto, autogenerate propondría borrarlas.
    if type_ == "table" and name is not None and name.startswith("checkpoint"):
        return False
    if type_ == "index" and object.table.name.startswith("checkpoint"):
        return False
    return True

def run_migrations_offline() -> None:
    url = settings.database_url.render_as_string(hide_password=True)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
    connection.commit()
    try:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})
        connection.commit()

async def run_async_migrations() -> None:
    connectable = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
