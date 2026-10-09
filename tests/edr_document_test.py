import base64
import json
import pytest
from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment
from src.services.edr.document import (PENDIENTE_DEFINIR, SECTIONS, EdrDocument, edr_config, pending_sections,
                                       render_edr_html)
from src.services.property import Properties
from src.utils.exceptions.edr import EdrNotConfiguredError

TEMPLATE = "<h1>{{ edr.titulo }}</h1><p>{{ edr.objetivo_general }}</p><p>{{ pending }}</p>"


def encoded(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def properties(**overrides: str) -> Properties:
    values = {"edr_template_base64": encoded(TEMPLATE), "edr_drive_folder_id": "carpeta-1",
              "google_chat_service_account_json": json.dumps({"client_email": "bot@x"})}
    return Properties({**values, **overrides})


def test_la_configuracion_decodifica_la_plantilla_de_la_bd():
    config = edr_config(properties())

    assert config.template == TEMPLATE and config.folder_id == "carpeta-1"
    assert config.service_account == {"client_email": "bot@x"}


@pytest.mark.parametrize("values", [{"edr_template_base64": "no es base64!"},
                                    {"google_chat_service_account_json": "{no json"}])
def test_plantilla_o_cuenta_invalida_no_genera_el_edr(values):
    with pytest.raises(EdrNotConfiguredError):
        edr_config(properties(**values))


@pytest.mark.parametrize("missing", ["edr_template_base64", "edr_drive_folder_id", "google_chat_service_account_json"])
def test_falta_una_property_no_genera_el_edr_y_nombra_solo_la_clave(missing):
    values = dict(properties().values)
    del values[missing]

    with pytest.raises(EdrNotConfiguredError, match=missing):
        edr_config(Properties(values))


def test_lo_que_nadie_entrego_queda_pendiente_y_el_html_se_escapa():
    edr = EdrDocument(titulo="<script>alert(1)</script> Cobranza")

    html = render_edr_html(edr, TEMPLATE)

    assert "<script>" not in html and "&lt;script&gt;" in html
    assert html.count(PENDIENTE_DEFINIR) == 2
    assert "objetivo general" in pending_sections(edr) and "titulo" not in pending_sections(edr)


def test_la_plantilla_de_la_bd_no_sale_del_sandbox():
    with pytest.raises(SecurityError):
        render_edr_html(EdrDocument(titulo="x"), "{{ edr.__class__.__mro__[1].__subclasses__() }}")


def test_un_edr_completo_solo_usa_campos_del_esquema():
    edr = EdrDocument.model_validate({
        "titulo": "PoC", "objetivo_general": "Responder FAQ", "product_owner": {"nombre": "Ana"},
        "especificaciones_rf": [{"codigo_rf": "RF-1", "bloques": [{"titulo": "Chat", "items": [{"texto": "a"}]}]}],
        "campo_inventado": "se ignora"})
    strict = SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)
    template = ("{{ edr.titulo }} {{ edr.product_owner.nombre }} {{ edr.product_owner.cargo }} "
                "{% for rf in edr.especificaciones_rf %}{{ rf.codigo_rf }} {{ rf.bloques[0].items[0].texto }}{% endfor %}")

    assert strict.from_string(template).render(edr=edr) == f"PoC Ana {PENDIENTE_DEFINIR} RF-1 a"


def test_cada_seccion_del_edr_tiene_su_nombre_para_el_colaborador():
    assert set(SECTIONS) == set(EdrDocument.model_fields) - {"titulo", "metadata", "historial"}
