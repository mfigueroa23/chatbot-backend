"""add jira access and edr documents

Revision ID: d80964432e58
Revises: 7a0f507a341b
Create Date: 2026-10-08 15:03:51.181050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd80964432e58'
down_revision: Union[str, Sequence[str], None] = '7a0f507a341b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Acceso a Jira y EDR (spec 005): tableros y colaboradores permitidos, EDR guardados y herramientas por área.
    # Las áreas existentes quedan sin herramientas; Proyectos recibe {jira,edr} en la carga de datos del despliegue.
    op.create_table('edr_document',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.String(length=255), nullable=False),
    sa.Column('drive_file_id', sa.String(length=255), nullable=False),
    sa.Column('web_link', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_edr_document_conversation_id'), 'edr_document', ['conversation_id'], unique=False)
    op.create_table('jira_board',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=20), nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('project_collaborator',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.add_column('business_area', sa.Column('tools', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('business_area', 'tools')
    op.drop_table('project_collaborator')
    op.drop_table('jira_board')
    op.drop_index(op.f('ix_edr_document_conversation_id'), table_name='edr_document')
    op.drop_table('edr_document')
