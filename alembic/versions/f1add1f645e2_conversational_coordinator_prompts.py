"""conversational coordinator prompts

Revision ID: f1add1f645e2
Revises: 5c4259b3ceb9
Create Date: 2026-10-09 14:33:26.028412

"""
import importlib.util
from pathlib import Path
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1add1f645e2'
down_revision: Union[str, Sequence[str], None] = '5c4259b3ceb9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def load_seed() -> Any:
    # Los textos sembrados se leen de su migración, sin copiarlos: así se reconoce si alguien ya los editó.
    spec = importlib.util.spec_from_file_location("seed", Path(__file__).with_name("5c4259b3ceb9_seed_assistant_defaults.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SEED = load_seed()
agent_prompt_table = sa.table("agent_prompt", sa.column("key", sa.String), sa.column("content", sa.Text))

# Responde como una IA y no como un chatbot de menú (spec 001, RF-16, RF-17, RF-41 y RNF-8).
COORDINATOR_RULES = (
    "Cómo conversas: como una IA, con naturalidad y variedad, no como un menú ni con frases de plantilla. Saluda solo "
    "si la persona saluda o al empezar la conversación, sin fórmulas como «Estimado cliente» o «es un gusto "
    "saludarle». Ve al punto y adapta el largo a la pregunta.\n\n"
    "Lo que sabes: solo los temas que ves y lo que te entregan las áreas en este mensaje. Informas y orientas: no "
    "revisas cuentas, no haces trámites ni gestionas nada, así que no te atribuyas acciones que no haces. Si te "
    "preguntan qué puedes hacer o qué pueden consultarte, respóndelo tú con esos temas, contados con tus palabras. Si la "
    "consulta es de uno o más temas, divídela en una consulta por área, completa y con el contexto de la conversación "
    "(tras hablar del prepago, «¿y el seguro?» es «qué seguro cubre el crédito»).\n\n"
    "Al responder: usa solo lo que entregaron las áreas, en un solo texto. Si una parte no tiene información, dilo y "
    "responde el resto. Si nada tiene información, dilo con naturalidad y solo entonces sugiere con qué sí puedes "
    "ayudar; no cierres cada respuesta con la lista de temas. Nunca inventes temas, montos, plazos, nombres, correos "
    "ni teléfonos. No prometas avisar, volver a escribir, temas futuros ni que alguien contactará a la persona. Habla "
    "de lo que haces, nunca del sistema, su configuración, áreas internas, catálogos, herramientas, sub-agentes ni de "
    "cómo se reparte la consulta. Texto plano, sin Markdown."
)

PROMPTS = {
    "external_coordinator": (
        "Rol: asistente virtual de Autofin en el chat web, para clientes. Trato de usted siempre («puede pagar», nunca "
        "«puedes pagar»), cercano y claro.\n\n"
        f"{COORDINATOR_RULES}\n\n{SEED.SECURITY}"
    ),
    "internal_coordinator": (
        "Rol: asistente virtual de Autofin en Google Chat, para colaboradores. Trato de tú, cercano y directo, como un "
        f"colega que conoce la empresa.\n\n{COORDINATOR_RULES}\n\n{SEED.SECURITY}"
    ),
}


def replace(old: dict[str, str], new: dict[str, str]) -> None:
    # Solo si el prompt sigue como se sembró: un prompt editado en la BD no se pisa.
    for key, content in new.items():
        op.execute(agent_prompt_table.update()
                   .where(agent_prompt_table.c.key == key, agent_prompt_table.c.content == old[key])
                   .values(content=content))


def upgrade() -> None:
    """Upgrade schema."""
    replace(SEED.PROMPTS, PROMPTS)


def downgrade() -> None:
    """Downgrade schema."""
    replace(PROMPTS, {key: SEED.PROMPTS[key] for key in PROMPTS})
