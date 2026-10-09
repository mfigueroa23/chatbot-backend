"""Carga o actualiza el área interna Proyectos (spec 002, RF-16, RF-21, RF-23): su prompt, sus FAQ sobre el EDR, sus
herramientas de Jira, los tableros permitidos y los colaboradores habilitados. Es idempotente: se puede volver a correr
para actualizar el contenido. Las credenciales de Jira no pasan por aquí: van a mano en property (SECURITY.md).

    uv run python -m src.cli.load_projects_area --boards DAIA --members jp1@autofin.cl,jp2@autofin.cl

Las FAQ derivan de la guía de secciones del EDR de agente-ti y deben revisarlas en el área Proyectos (spec 002, dudas).
"""
import argparse
import asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from src.database.session import SessionLocal, engine
from src.models.area_member import AreaMember
from src.models.business_area import AreaScope, BusinessArea
from src.models.faq import Faq
from src.models.faq_category import FaqCategory
from src.models.jira_board import JiraBoard

NAME = "Proyectos"
DESCRIPTION = ("Jefes de Proyecto de TI: cómo redactar una EDR (especificación de requerimientos de desarrollo) y qué va "
               "en cada sección, y consulta del estado de tickets y épicas en Jira.")
SYSTEM_PROMPT = (
    "Eres el especialista del área Proyectos de TI: orientas sobre cómo redactar una EDR y consultas Jira en solo "
    "lectura. Para el estado de un ticket o una épica, léelo; para encontrar tickets, búscalos con una condición sin "
    "indicar el proyecto. Entrega el estado, el tipo, el responsable, la descripción y las subtareas tal como vienen, "
    "sin inventar datos. Si piden crear, modificar, comentar, cambiar de estado o vincular un ticket, responde que por "
    "ahora solo puedes consultar Jira.")
TOOLS = ["leer_ticket", "buscar_tickets"]

SECTIONS = [
    ("objetivo general", "El porqué del desarrollo en una frase, para quien lea solo esa sección."),
    ("visión general", "El objetivo de negocio en términos de negocio, por ejemplo «transparentar pérdidas y utilidades "
     "conforme lo instruye el Servicio de Impuestos Internos», no «modificar la función X»."),
    ("product owner", "Quién valida que el resultado sirve al área: nombre y cargo."),
    ("equipo de desarrollo", "Quiénes construyen la solución. No se confunde con el product owner ni con los usuarios "
     "afectados."),
    ("aplicaciones afectadas", "Los sistemas o módulos que se tocan, cada uno con su nivel de impacto: Crítico, "
     "Moderado o Marginal."),
    ("usuarios afectados", "Quiénes usan el sistema y sienten el cambio, no los desarrolladores."),
    ("requerimientos", "El índice de requerimientos funcionales (RF) y no funcionales (RNF); el detalle de cada uno va "
     "en las especificaciones."),
    ("especificaciones de cada RF", "La descripción y bloques por pantalla o agrupación, con ítems y como máximo un "
     "nivel de sub-ítems; y, cuando corresponde, reglas de negocio, flujos positivos, flujos negativos y notas."),
    ("roles y permisos", "El control de acceso por pantalla o funcionalidad, solo si el desarrollo lo introduce o lo "
     "cambia."),
    ("impacto", "Qué áreas de la organización se ven afectadas y en qué proceso; no son sistemas."),
    ("infraestructura", "Lo que ese equipo debe provisionar: ambientes, DNS, base de datos o proyecto en Azure DevOps. "
     "Si no requiere nada nuevo, se dice explícitamente."),
    ("seguridad", "Los controles generales (cifrado, auditoría, autenticación), distintos de roles y permisos. Solo si "
     "hay datos sensibles o un riesgo real."),
    ("criterios de aceptación", "Cómo QA o el JP confirman que está bien hecho: verificables y marcando los críticos."),
    ("validaciones de cartera", "El efecto sobre los procesos de cierre de cartera, diario o mensual, no el desarrollo "
     "en sí. Por ejemplo, cambiar cómo se calculan los intereses impacta cómo se devengan día a día, y cambiar períodos "
     "o fechas de cuotas puede impactar cómo se cuentan los días de mora."),
    ("glosario", "Vocabulario del negocio de cartera y crédito (mora, devengo, cuota flex, TMC, GAC) o siglas internas "
     "del EDR; no términos técnicos genéricos."),
    ("metadata e historial", "La metadata lleva versión, fecha y nombre del sistema; el código de documento y la tarea "
     "Trinidad los maneja el JP. El historial registra las revisiones del documento, con el cargo de quien lo cambió."),
]

FAQS: dict[str, list[tuple[str, str]]] = {
    "EDR": [
        ("¿Qué es una EDR?",
         "La EDR es la especificación de requerimientos de desarrollo: el documento que describe qué se va a construir "
         "y por qué, para que el product owner, el equipo de desarrollo y QA trabajen sobre lo mismo. La redacta el "
         "Jefe de Proyecto."),
        ("¿Qué secciones tiene una EDR?",
         "Metadata, historial, objetivo general, visión general, product owner, equipo de desarrollo, aplicaciones "
         "afectadas, usuarios afectados, requerimientos, especificaciones de cada RF, roles y permisos, impacto, "
         "infraestructura, seguridad, criterios de aceptación, validaciones de cartera y glosario."),
        ("¿Qué hago si me falta un dato de la EDR?",
         "Si nadie entregó el dato, se deja como «[PENDIENTE DEFINIR]»; nunca se inventa un nombre, una fecha o una "
         "cifra. Si el JP evaluó y confirmó que la sección no aplica, se escribe «NA.» (típico en roles y permisos y en "
         "validaciones de cartera)."),
    ],
    "Secciones de la EDR": [(f"¿Qué va en la sección {name} de la EDR?", answer) for name, answer in SECTIONS],
    "Jira": [
        ("¿Puedo consultar Jira con el asistente?",
         "Sí, si estás habilitado para el área Proyectos: puedes preguntar por el estado, la descripción y las subtareas "
         "de un ticket o una épica, o buscar tickets de los tableros permitidos. Por ahora solo consulta: no crea ni "
         "modifica tickets."),
    ],
}

async def load(boards: list[str], members: list[str]) -> None:
    async with SessionLocal() as session:
        area = await session.scalar(select(BusinessArea).where(BusinessArea.name == NAME))
        if area is None:
            area = BusinessArea(name=NAME, description=DESCRIPTION, scope=AreaScope.internal)
            session.add(area)
        area.description, area.system_prompt, area.tools, area.active = DESCRIPTION, SYSTEM_PROMPT, TOOLS, True
        await session.flush()
        # Las FAQ del área se reemplazan completas; FaqCategory borra en cascada sus FAQ.
        await session.execute(delete(FaqCategory).where(FaqCategory.area_id == area.id))
        for category_name, faqs in FAQS.items():
            category = FaqCategory(area_id=area.id, name=category_name)
            session.add(category)
            await session.flush()
            session.add_all([Faq(category_id=category.id, question=question, answer=answer) for question, answer in faqs])
        for key in boards:
            await session.execute(insert(JiraBoard).values(key=key.strip().upper()).on_conflict_do_nothing())
        for email in members:
            await session.execute(insert(AreaMember).values(area_id=area.id, email=email.strip().lower())
                                  .on_conflict_do_nothing())
        await session.commit()
        print(f"Área {NAME} (id {area.id}): {sum(len(faqs) for faqs in FAQS.values())} FAQ en {len(FAQS)} categorías, "
              f"herramientas {', '.join(TOOLS)}, {len(boards)} tableros y {len(members)} colaboradores habilitados.")
    await engine.dispose()

def main() -> None:
    parser = argparse.ArgumentParser(description="Carga o actualiza el área Proyectos")
    parser.add_argument("--boards", default="", help="Tableros de Jira permitidos, separados por comas")
    parser.add_argument("--members", default="", help="Correos de los colaboradores habilitados, separados por comas")
    args = parser.parse_args()
    split = lambda value: [item for item in (part.strip() for part in value.split(",")) if item]  # noqa: E731
    asyncio.run(load(split(args.boards), split(args.members)))

if __name__ == "__main__":
    main()
