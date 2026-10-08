"""seed personas

Revision ID: 7a0f507a341b
Revises: 20be34b82e76
Create Date: 2026-10-08 11:17:19.188915

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a0f507a341b'
down_revision: Union[str, Sequence[str], None] = '20be34b82e76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tono del asistente de cada canal. Son instrucciones de estilo y no una presentación: una frase de identidad larga se
# repetiría en las respuestas y el auditor la tomaría por una fuga del prompt.
PERSONAS = {
    "internal_persona": (
        "Tono: cercano y profesional, con trato de tú y un humor ligero cuando la conversación lo permite. "
        "Sin modismos marcados. Frases cortas y naturales, sin títulos, listas largas ni negritas."
    ),
    "external_persona": (
        "Tono: cercano, cordial y profesional, con trato de usted. Sin modismos y sin humor ante un reclamo o un "
        "problema del cliente. Frases cortas y naturales, sin títulos, listas largas ni negritas."
    ),
}


def upgrade() -> None:
    """Upgrade schema."""
    # Sin pisar una persona que ya se haya editado en la BD.
    statement = sa.text("INSERT INTO agent_prompt (key, content) VALUES (:key, :content) ON CONFLICT (key) DO NOTHING")
    for key, content in PERSONAS.items():
        op.execute(statement.bindparams(key=key, content=content))


def downgrade() -> None:
    """Downgrade schema."""
    statement = sa.text("DELETE FROM agent_prompt WHERE key = :key")
    for key in PERSONAS:
        op.execute(statement.bindparams(key=key))
