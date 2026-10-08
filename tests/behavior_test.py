import pytest
from src.agents.behavior import (
    Candidate, ClarifyOption, Clarification, areas_question, build_options, can_clarify, chosen, combine, ensure_areas,
    fixed_text, mentions_area, options_text, other_procedures_text, requester_key)
from src.services.area_notifier import Requester


def faq(item_id: int, label: str, similarity: float, area_id: int = 1) -> Candidate:
    return Candidate("faq", item_id, area_id, label, similarity)


def procedure(item_id: int, label: str, similarity: float, area_id: int = 1) -> Candidate:
    return Candidate("procedure", item_id, area_id, label, similarity)


OPTIONS = [
    ClarifyOption(1, "faq", 10, 1, "¿Cómo pago mi cuota?"),
    ClarifyOption(2, "faq", 11, 1, "¿Dónde veo mi saldo?"),
    ClarifyOption(3, "procedure", 5, 2, "Solicitar certificado de deuda"),
]


def test_requester_key_usa_el_correo_de_google_chat_o_web():
    assert requester_key(Requester("Ana", "ana@autofin.cl", "google_chat")) == "ana@autofin.cl"
    assert requester_key(None) == "web"
    assert requester_key(Requester(None, None, "google_chat")) == "anonymous"


def test_build_options_ordena_por_similitud_y_limita_a_tres():
    candidates = [faq(1, "Plazo de pago", 0.60), procedure(2, "Repactar deuda", 0.66), faq(3, "Pagar en línea", 0.58),
                  faq(4, "Cambiar fecha de pago", 0.57), procedure(5, "Pedir certificado", 0.56)]

    options = build_options(candidates)

    assert [(o.number, o.kind, o.item_id) for o in options] == [(1, "procedure", 2), (2, "faq", 1), (3, "faq", 3)]


def test_build_options_desempata_alfabeticamente():
    options = build_options([faq(1, "zeta", 0.6), faq(2, "Alfa", 0.6)])

    assert [o.label for o in options] == ["Alfa", "zeta"]


def test_build_options_ofrece_un_texto_repetido_una_sola_vez_con_el_de_mayor_similitud():
    options = build_options([faq(1, "Plazo de pago", 0.58), procedure(2, "plazo de pago ", 0.64), faq(3, "Otro", 0.57)])

    assert [(o.number, o.item_id) for o in options] == [(1, 2), (2, 3)]


def test_options_text_numera_las_opciones_sin_respuesta_ni_pasos():
    text = options_text(OPTIONS)

    assert "1. ¿Cómo pago mi cuota?" in text
    assert "3. Solicitar certificado de deuda" in text
    assert text.index("1.") < text.index("2.") < text.index("3.")


def test_areas_question_nombra_las_areas_del_canal():
    assert areas_question(["Pagos", "Seguros", "Créditos"]).endswith("Puedo ayudarte con temas de: Pagos, Seguros y Créditos.")


def test_areas_question_sin_areas_no_incluye_la_lista():
    assert "Puedo ayudarte" not in areas_question([])


@pytest.mark.parametrize(("pending", "kind", "expected"), [
    (None, "options", True),
    (None, "areas", True),
    (Clarification("options", OPTIONS), "options", False),
    (Clarification("options", OPTIONS), "areas", False),
    (Clarification("areas", []), "options", True),
    (Clarification("areas", []), "areas", False),
])
def test_can_clarify(pending, kind, expected):
    assert can_clarify(pending, kind) is expected


@pytest.mark.parametrize(("names", "suffix"), [
    ([], None),
    (["Pagos"], "Puedo ayudarte con temas de: Pagos."),
    (["Pagos", "Seguros", "Créditos"], "Puedo ayudarte con temas de: Pagos, Seguros y Créditos."),
])
def test_fixed_text_añade_las_areas(names, suffix):
    text = fixed_text("¡Hola!", names)

    if suffix is None:
        assert text == "¡Hola!"
    else:
        assert text.startswith("¡Hola!") and text.endswith(suffix)


def test_chosen_separa_varias_faq():
    result = chosen(OPTIONS, [2, 1])

    assert [o.item_id for o in result.faqs] == [11, 10]
    assert result.procedure is None and result.other_procedures == []


def test_chosen_inicia_solo_el_primer_procedimiento_mencionado():
    options = [*OPTIONS, ClarifyOption(4, "procedure", 6, 2, "Repactar deuda")]

    result = chosen(options, [4, 1, 3])

    assert [o.item_id for o in result.faqs] == [10]
    assert result.procedure is not None and result.procedure.item_id == 6
    assert [o.label for o in result.other_procedures] == ["Solicitar certificado de deuda"]
    assert "Solicitar certificado de deuda" in other_procedures_text(result.other_procedures)


def test_chosen_ignora_un_numero_fuera_de_rango():
    result = chosen(OPTIONS, [4])

    assert result.faqs == [] and result.procedure is None


def test_combine_una_respuesta_va_tal_cual():
    assert combine([("Pagos", "Paga en línea.")]) == "Paga en línea."


def test_combine_varias_respuestas_nombran_su_area():
    text = combine([("Pagos", "Paga en línea."), ("Seguros", "El seguro cubre robo.")])

    assert text is not None
    assert "Pagos" in text and "Paga en línea." in text and "Seguros" in text and "El seguro cubre robo." in text


def test_combine_parcial_indica_las_areas_sin_respuesta():
    text = combine([("Pagos", "Paga en línea."), ("Seguros", None)])

    assert text is not None
    assert text.startswith("Paga en línea.")
    assert text.endswith("No encontré información sobre: Seguros.")


def test_combine_sin_respuestas_devuelve_none():
    assert combine([("Pagos", None)]) is None


@pytest.mark.parametrize(("text", "expected"), [
    ("Te ayudo con temas de remuneraciones y beneficios.", True),
    ("¡Hola! Cuéntame qué necesitas.", False),
])
def test_mentions_area_sin_distinguir_mayusculas(text, expected):
    assert mentions_area(text, ["Remuneraciones", "Gestión"]) is expected


def test_mentions_area_sin_areas_es_falso():
    assert mentions_area("Puedo ayudarte con Remuneraciones.", []) is False


def test_ensure_areas_no_repite_las_areas_si_el_texto_ya_nombra_una():
    text = "¡Hola! Te ayudo con lo de Remuneraciones."

    assert ensure_areas(text, ["Remuneraciones", "Gestión"]) == text


def test_ensure_areas_añade_la_linea_si_el_texto_no_nombra_ninguna():
    assert ensure_areas("¡Hola!", ["Remuneraciones", "Gestión"]) == (
        "¡Hola!\n\nPuedo ayudarte con temas de: Remuneraciones y Gestión.")


def test_ensure_areas_sin_areas_deja_el_texto():
    assert ensure_areas("¡Hola!", []) == "¡Hola!"
