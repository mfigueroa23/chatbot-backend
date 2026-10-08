"""seed fixed messages

Revision ID: 20be34b82e76
Revises: 36f04146ef00
Create Date: 2026-10-07 23:16:06.893372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20be34b82e76'
down_revision: Union[str, Sequence[str], None] = '36f04146ef00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Textos iniciales de los mensajes fijos de cada canal; la lista de áreas la añade el código.
FIXED_MESSAGES = {
    "greeting": "¡Hola! Soy el asistente virtual. ¿En qué te puedo ayudar?",
    "closing": "¡Con gusto! Si necesitas algo más, escríbeme.",
    "off_topic": "Lo siento, no puedo ayudarte con eso.",
}
KEYS = [(f"{scope}_{kind}", text) for scope in ("internal", "external") for kind, text in FIXED_MESSAGES.items()]


def upgrade() -> None:
    """Upgrade schema."""
    # Sin pisar un texto que ya se haya editado en la BD.
    statement = sa.text("INSERT INTO agent_prompt (key, content) VALUES (:key, :content) ON CONFLICT (key) DO NOTHING")
    for key, content in KEYS:
        op.execute(statement.bindparams(key=key, content=content))


def downgrade() -> None:
    """Downgrade schema."""
    statement = sa.text("DELETE FROM agent_prompt WHERE key = :key")
    for key, _ in KEYS:
        op.execute(statement.bindparams(key=key))
