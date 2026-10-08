import httpx
import pytest
from typing import cast
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.edr_document import EdrDocumentRecord
from src.services.drive_client import DriveUpload
from jinja2 import StrictUndefined
from src.services import edr as edr_module
from src.services.edr import (
    PENDIENTE_DEFINIR, EdrAplicacionAfectada, EdrBloqueEspecificacion, EdrCriterioAceptacion, EdrDocument,
    EdrEspecificacionRF, EdrGlosarioEntry, EdrHistorialEntry, EdrImpacto, EdrItemBloque, EdrMiembroEquipo, EdrPersona,
    EdrRequerimientoEntry, EdrRolPermiso, EdrSeguridad, get_edr, render_edr_html, save_edr)

# Las secciones numeradas de la plantilla institucional del EDR (la misma de agente-ti).
SECTIONS = ["1.&nbsp;&nbsp; Objetivo General", "2.&nbsp;&nbsp; Visión General", "a.&nbsp;&nbsp; Product Owner",
            "b.&nbsp;&nbsp; Equipo de Desarrollo", "c.&nbsp;&nbsp; Aplicaciones y Servicios Afectados",
            "d.&nbsp;&nbsp; Usuarios Afectados por la Solución", "3.&nbsp;&nbsp; Lista de Requerimientos",
            "4.&nbsp;&nbsp; Especificación Detallada de Requerimientos", "5.&nbsp;&nbsp; Matriz de Roles y Permisos",
            "6.&nbsp;&nbsp; Matriz de Impacto", "7.&nbsp;&nbsp; Infraestructura", "8.&nbsp;&nbsp; Seguridad y Ciberseguridad",
            "9.&nbsp;&nbsp; Criterios de Aceptación (QA)", "10.&nbsp;&nbsp; Validaciones de Cartera",
            "11.&nbsp;&nbsp; Glosario", "12.&nbsp;&nbsp; Historial de Modificaciones", "13.&nbsp;&nbsp; Aprobación Documento"]


def edr(**fields) -> EdrDocument:
    return EdrDocument(titulo="EDR DAIA-52 Curse automatizado", **fields)


def test_pendiente_por_defecto_en_lo_que_nadie_entrego():
    document = edr()

    assert document.objetivo_general == document.infraestructura == document.validaciones_cartera == PENDIENTE_DEFINIR
    assert document.metadata.codigo_documento == PENDIENTE_DEFINIR and document.product_owner is None


def test_html_con_todas_las_secciones_y_los_pendientes_marcados():
    html = render_edr_html(edr(
        objetivo_general="Automatizar el curse de créditos <rápido>",
        requerimientos=[EdrRequerimientoEntry(codigo_rf="RF-01", nombre="Leer el pagaré", tipo="Funcional")],
        criterios_aceptacion=[EdrCriterioAceptacion(codigo="CA-01", descripcion="Lee el pagaré",
                                                    resultado_esperado="Fechas correctas", referencia_rf="RF-01",
                                                    es_critico=True)]))

    assert all(section in html for section in SECTIONS)
    assert "RF-01" in html and "Leer el pagaré" in html and "CA-01" in html
    assert "&lt;rápido&gt;" in html and PENDIENTE_DEFINIR in html


def full_edr() -> EdrDocument:
    return edr(
        historial=[EdrHistorialEntry(fecha="08-10-2026", responsable="Marco Figueroa", cargo="JP", descripcion_cambio="Inicial",
                                     version="0.1")],
        objetivo_general="Automatizar el curse", vision_general="Menos tiempo de curse",
        product_owner=EdrPersona(nombre="Luis Ramos", cargo="Gerente"),
        equipo_desarrollo=[EdrMiembroEquipo(tipo="Interno", nombre="Equipo IA")],
        aplicaciones_afectadas=[EdrAplicacionAfectada(nombre="Core", nivel_impacto="Crítico")],
        usuarios_afectados=["Ejecutivos de curse"],
        requerimientos=[EdrRequerimientoEntry(codigo_rf="RF-01", nombre="Leer el pagaré", tipo="Funcional")],
        especificaciones_rf=[EdrEspecificacionRF(
            codigo_rf="RF-01", descripcion="Lee las fechas", reglas_negocio=["Fecha válida"], flujos_positivos=["OK"],
            flujos_negativos=["Error"], notas="Sin notas",
            bloques=[EdrBloqueEspecificacion(titulo="Pantalla", parrafo="Detalle", items=[EdrItemBloque(texto="Campo", sub_items=["Sub"])])])],
        roles_permisos=[EdrRolPermiso(gerencia="Riesgos", perfil="JP", permiso="Ver", accion="Leer")],
        impacto=[EdrImpacto(area="Operaciones", proceso_afectado="Curse", responsable="Ana", rf_afectado="RF-01")],
        infraestructura="Un ambiente nuevo",
        seguridad=[EdrSeguridad(referencia="S-1", nombre="Cifrado", descripcion="TLS", nivel_riesgo="Alto")],
        criterios_aceptacion=[EdrCriterioAceptacion(codigo="CA-01", descripcion="Lee", resultado_esperado="Fechas",
                                                    referencia_rf="RF-01", es_critico=True)],
        validaciones_cartera="Sin impacto en el devengo", glosario=[EdrGlosarioEntry(termino="TMC", definicion="Tasa máxima")])


def test_html_institucional_usa_solo_campos_del_esquema(monkeypatch: pytest.MonkeyPatch):
    # StrictUndefined falla si la plantilla pide un campo que el esquema no tiene.
    monkeypatch.setattr(edr_module.TEMPLATES, "undefined", StrictUndefined)

    html = render_edr_html(full_edr())

    assert "PLANTILLA DE ESPECIFICACIÓN DE REQUERIMIENTOS" in html and 'class="logo"' in html
    assert "Luis Ramos" in html and "Leer el pagaré" in html and "riesgo-alto" in html


class EdrSession:
    def __init__(self, existing: EdrDocumentRecord | None = None):
        self.existing = existing
        self.added: list = []
        self.commits = 0

    async def scalar(self, statement):
        return self.existing

    def add(self, record):
        self.added.append(record)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


class FakeDriveWriter:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.created: list[tuple[str, str]] = []
        self.replaced: list[str] = []

    async def create_document_from_html(self, name: str, folder_id: str, html: str) -> DriveUpload:
        if self.fail:
            raise httpx.HTTPStatusError("500", request=httpx.Request("POST", "https://x"), response=httpx.Response(500))
        self.created.append((name, folder_id))
        return DriveUpload("DOC1", "https://docs.google.com/document/d/DOC1/edit")

    async def replace_document_html(self, file_id: str, html: str) -> DriveUpload:
        self.replaced.append(file_id)
        return DriveUpload(file_id, f"https://docs.google.com/document/d/{file_id}/edit")


@pytest.mark.anyio
async def test_guardar_el_primer_edr_crea_el_documento():
    session, drive = EdrSession(), FakeDriveWriter()

    saved = await save_edr(cast(AsyncSession, session), "spaces/AAA", edr(), drive, "CARPETA")

    assert saved.web_link == "https://docs.google.com/document/d/DOC1/edit" and saved.created
    assert drive.created == [("EDR DAIA-52 Curse automatizado", "CARPETA")] and session.commits == 1
    record = session.added[0]
    assert (record.conversation_id, record.drive_file_id) == ("spaces/AAA", "DOC1")
    assert record.content["titulo"] == "EDR DAIA-52 Curse automatizado"


@pytest.mark.anyio
async def test_guardar_otra_vez_actualiza_el_mismo_documento():
    existing = EdrDocumentRecord(conversation_id="spaces/AAA", drive_file_id="DOC7", web_link="viejo", title="viejo",
                                 content={})
    session, drive = EdrSession(existing), FakeDriveWriter()

    saved = await save_edr(cast(AsyncSession, session), "spaces/AAA", edr(objetivo_general="Nuevo objetivo"), drive, "CARPETA")

    assert drive.replaced == ["DOC7"] and drive.created == [] and not saved.created
    assert existing.content["objetivo_general"] == "Nuevo objetivo" and session.added == []


@pytest.mark.anyio
async def test_guardar_uno_nuevo_aunque_exista_otro():
    existing = EdrDocumentRecord(conversation_id="spaces/AAA", drive_file_id="DOC7", web_link="v", title="v", content={})
    session, drive = EdrSession(existing), FakeDriveWriter()

    await save_edr(cast(AsyncSession, session), "spaces/AAA", edr(), drive, "CARPETA", new=True)

    assert drive.created and drive.replaced == [] and len(session.added) == 1


@pytest.mark.anyio
async def test_guardar_con_drive_caido_no_crea_fila():
    session = EdrSession()

    with pytest.raises(httpx.HTTPStatusError):
        await save_edr(cast(AsyncSession, session), "spaces/AAA", edr(), FakeDriveWriter(fail=True), "CARPETA")
    assert session.added == [] and session.commits == 0


@pytest.mark.anyio
async def test_guardar_y_leer_el_edr_de_la_conversacion():
    existing = EdrDocumentRecord(conversation_id="spaces/AAA", drive_file_id="DOC7", web_link="v", title="v",
                                 content=edr(objetivo_general="Objetivo guardado").model_dump())

    found = await get_edr(cast(AsyncSession, EdrSession(existing)), "spaces/AAA")
    missing = await get_edr(cast(AsyncSession, EdrSession()), "spaces/BBB")

    assert found is not None and found.objetivo_general == "Objetivo guardado" and missing is None
