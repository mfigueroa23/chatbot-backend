"""seed tools and files defaults

Revision ID: 181653739733
Revises: 85edb5a46f4b
Create Date: 2026-10-09 16:32:47.850388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '181653739733'
down_revision: Union[str, Sequence[str], None] = '85edb5a46f4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


property_table = sa.table("property", sa.column("key", sa.String), sa.column("value", sa.Text))

# Valores por defecto de la spec 002 (plan, sección 5). Las credenciales de Jira y de la cuenta de servicio de Chat se
# cargan a mano (SECURITY.md).
PROPERTIES = {
    "jira_max_results": "20",
    "jira_timeout_seconds": "5",
    "mcp_timeout_seconds": "5",
    "file_max_mb": "20",
    "file_max_chars": "30000",
    "file_response_timeout_seconds": "27",
}


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(postgresql.insert(property_table)
               .values([{"key": key, "value": value} for key, value in PROPERTIES.items()])
               .on_conflict_do_nothing(index_elements=["key"]))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(property_table.delete().where(property_table.c.key.in_(list(PROPERTIES))))
