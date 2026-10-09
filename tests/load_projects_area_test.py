from src.cli.load_projects_area import FAQS, SYSTEM_PROMPT, TOOLS
from src.agents.tools.available import TOOLS as REGISTRY


def test_las_herramientas_del_area_existen_en_el_registro():
    assert set(TOOLS) <= set(REGISTRY)


def test_el_prompt_dice_que_solo_consulta_jira():
    assert "solo puedes consultar Jira" in SYSTEM_PROMPT


def test_el_area_genera_y_lee_el_edr_en_segundo_plano():
    assert {"generar_edr", "leer_edr"} <= set(TOOLS) and "segundo plano" in SYSTEM_PROMPT


def test_faqs_completas_y_sin_preguntas_repetidas():
    questions = [question for faqs in FAQS.values() for question, _ in faqs]
    assert all(question.strip() and answer.strip() for faqs in FAQS.values() for question, answer in faqs)
    assert len(questions) == len(set(questions)) and "Secciones de la EDR" in FAQS
