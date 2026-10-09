"""add edr document and defaults

Revision ID: e984499708d8
Revises: 181653739733
Create Date: 2026-10-09 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e984499708d8'
down_revision: Union[str, Sequence[str], None] = '181653739733'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

property_table = sa.table("property", sa.column("key", sa.String), sa.column("value", sa.Text))
agent_prompt_table = sa.table("agent_prompt", sa.column("key", sa.String), sa.column("content", sa.Text))

# Valores por defecto de la spec 003 (plan, sección 4). edr_template_base64 y edr_drive_folder_id se copian de la base
# anterior (plan, sección 5); edr_model es opcional y sin él se usa sub_agent_model.
PROPERTIES = {
    "edr_job_timeout_seconds": "180",
    "edr_history_messages": "30",
}

# Rol y criterios de redacción (spec 003, RF-8, RF-9, RF-19); el formato JSON y los campos van en el código.
EDR_WRITER = (
    "Eres el redactor de EDR (especificación de requerimientos de desarrollo) del área Proyectos de TI de Autofin. "
    "Redactas en español formal y claro, para que el product owner, el equipo de desarrollo y QA trabajen sobre lo "
    "mismo.\n\n"
    "Usa solo lo que está en la conversación, en los archivos compartidos, en la épica de Jira y en el EDR actual. "
    "Nunca inventes nombres, cargos, fechas, cifras, sistemas ni códigos: lo que nadie entregó se omite y queda como "
    "«[PENDIENTE DEFINIR]». Si el Jefe de Proyecto confirmó que una sección no aplica, escribe «NA.».\n\n"
    "Criterios por sección: el objetivo general dice el porqué en una frase; la visión general, el objetivo de negocio "
    "en términos de negocio; las aplicaciones afectadas llevan su nivel de impacto (Crítico, Moderado o Marginal); los "
    "usuarios afectados son quienes usan el sistema, no los desarrolladores; cada requerimiento funcional tiene su "
    "código (RF-1, RF-2…) y su especificación con bloques por pantalla o agrupación; el impacto es sobre áreas de la "
    "organización, no sistemas; los criterios de aceptación son verificables y marcan los críticos; las validaciones "
    "de cartera hablan del efecto sobre los cierres de cartera; el glosario es vocabulario del negocio.\n\n"
    "Si hay un EDR actual, conserva todo lo que no te piden cambiar y suma una fila al historial con el cambio.")
PROMPTS = {"edr_writer": EDR_WRITER}


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('edr_document',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('drive_file_id', sa.String(length=255), nullable=False),
    sa.Column('web_link', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_edr_document_conversation_id'), 'edr_document', ['conversation_id'], unique=False)
    # ON CONFLICT DO NOTHING: si alguien ya cargó una de estas claves, se respeta su valor.
    op.execute(postgresql.insert(property_table)
               .values([{"key": key, "value": value} for key, value in PROPERTIES.items()])
               .on_conflict_do_nothing(index_elements=["key"]))
    op.execute(postgresql.insert(agent_prompt_table)
               .values([{"key": key, "content": content} for key, content in PROMPTS.items()])
               .on_conflict_do_nothing(index_elements=["key"]))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(agent_prompt_table.delete().where(agent_prompt_table.c.key.in_(list(PROMPTS))))
    op.execute(property_table.delete().where(property_table.c.key.in_(list(PROPERTIES))))
    op.drop_index(op.f('ix_edr_document_conversation_id'), table_name='edr_document')
    op.drop_table('edr_document')
