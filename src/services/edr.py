"""Especificación de requerimientos de desarrollo (EDR) con la estructura de agente-ti, guardada como Google Doc."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.edr_document import EdrDocumentRecord
from src.services.drive_client import DriveUpload
from src.utils.exceptions.database import DatabaseUnavailableError

PENDIENTE_DEFINIR = "[PENDIENTE DEFINIR]"
TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
                        autoescape=select_autoescape(["html"]))

class EdrModel(BaseModel):
    # Campos de más del modelo se ignoran: un nombre mal escrito no debe impedir guardar el resto del EDR.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

class EdrMetadata(EdrModel):
    version: str = "0.1"
    codigo_documento: str = PENDIENTE_DEFINIR
    tarea_trinidad: str = PENDIENTE_DEFINIR
    fecha: str = PENDIENTE_DEFINIR
    nombre_sistema: str = PENDIENTE_DEFINIR

class EdrHistorialEntry(EdrModel):
    fecha: str
    responsable: str
    cargo: str = PENDIENTE_DEFINIR
    descripcion_cambio: str
    version: str

class EdrPersona(EdrModel):
    nombre: str
    cargo: str = PENDIENTE_DEFINIR

class EdrMiembroEquipo(EdrModel):
    tipo: str  # p. ej. interno o proveedor
    nombre: str

class EdrAplicacionAfectada(EdrModel):
    nombre: str
    nivel_impacto: str  # Crítico, Moderado o Marginal

class EdrRequerimientoEntry(EdrModel):
    codigo_rf: str
    nombre: str
    tipo: str  # Funcional o No funcional

class EdrItemBloque(EdrModel):
    texto: str
    sub_items: list[str] = Field(default_factory=list)

class EdrBloqueEspecificacion(EdrModel):
    titulo: str
    parrafo: str | None = None
    items: list[EdrItemBloque] = Field(default_factory=list)

class EdrEspecificacionRF(EdrModel):
    codigo_rf: str
    descripcion: str | None = None
    bloques: list[EdrBloqueEspecificacion] = Field(default_factory=list)
    reglas_negocio: list[str] = Field(default_factory=list)
    flujos_positivos: list[str] = Field(default_factory=list)
    flujos_negativos: list[str] = Field(default_factory=list)
    notas: str | None = None

class EdrRolPermiso(EdrModel):
    gerencia: str
    perfil: str
    permiso: str
    accion: str

class EdrImpacto(EdrModel):
    area: str
    proceso_afectado: str
    responsable: str
    rf_afectado: str

class EdrSeguridad(EdrModel):
    referencia: str
    nombre: str
    descripcion: str
    nivel_riesgo: str

class EdrCriterioAceptacion(EdrModel):
    codigo: str
    descripcion: str
    resultado_esperado: str
    referencia_rf: str
    es_critico: bool = False

class EdrGlosarioEntry(EdrModel):
    termino: str
    definicion: str

class EdrDocument(EdrModel):
    """Lo que nadie entregó queda como «[PENDIENTE DEFINIR]»: el EDR nunca inventa datos."""
    titulo: str
    metadata: EdrMetadata = Field(default_factory=EdrMetadata)
    historial: list[EdrHistorialEntry] = Field(default_factory=list)
    objetivo_general: str = PENDIENTE_DEFINIR
    vision_general: str = PENDIENTE_DEFINIR
    product_owner: EdrPersona | None = None
    equipo_desarrollo: list[EdrMiembroEquipo] = Field(default_factory=list)
    aplicaciones_afectadas: list[EdrAplicacionAfectada] = Field(default_factory=list)
    usuarios_afectados: list[str] = Field(default_factory=list)
    requerimientos: list[EdrRequerimientoEntry] = Field(default_factory=list)
    especificaciones_rf: list[EdrEspecificacionRF] = Field(default_factory=list)
    roles_permisos: list[EdrRolPermiso] = Field(default_factory=list)
    impacto: list[EdrImpacto] = Field(default_factory=list)
    infraestructura: str = PENDIENTE_DEFINIR
    seguridad: list[EdrSeguridad] = Field(default_factory=list)
    criterios_aceptacion: list[EdrCriterioAceptacion] = Field(default_factory=list)
    validaciones_cartera: str = PENDIENTE_DEFINIR
    glosario: list[EdrGlosarioEntry] = Field(default_factory=list)

@dataclass(frozen=True)
class EdrSaved:
    web_link: str
    created: bool

class DriveWriter(Protocol):
    async def create_document_from_html(self, name: str, folder_id: str, html: str) -> DriveUpload: ...
    async def replace_document_html(self, file_id: str, html: str) -> DriveUpload: ...

def render_edr_html(edr: EdrDocument) -> str:
    return TEMPLATES.get_template("edr.html").render(edr=edr, pending=PENDIENTE_DEFINIR)

async def latest_record(session: AsyncSession, conversation_id: str) -> EdrDocumentRecord | None:
    statement = (select(EdrDocumentRecord).where(EdrDocumentRecord.conversation_id == conversation_id)
                 .order_by(EdrDocumentRecord.updated_at.desc(), EdrDocumentRecord.id.desc()).limit(1))
    try:
        return await session.scalar(statement)
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_edr(session: AsyncSession, conversation_id: str) -> EdrDocument | None:
    record = await latest_record(session, conversation_id)
    return EdrDocument.model_validate(record.content) if record is not None else None

async def save_edr(session: AsyncSession, conversation_id: str, edr: EdrDocument, drive: DriveWriter, folder_id: str,
                   new: bool = False) -> EdrSaved:
    """Crea el Google Doc del primer EDR de la conversación y actualiza el mismo después; un fallo de Drive no deja fila."""
    record = None if new else await latest_record(session, conversation_id)
    html = render_edr_html(edr)
    content = edr.model_dump()
    if record is None:
        upload = await drive.create_document_from_html(edr.titulo, folder_id, html)
        session.add(EdrDocumentRecord(conversation_id=conversation_id, drive_file_id=upload.id, web_link=upload.web_link,
                                      title=edr.titulo, content=content))
    else:
        upload = await drive.replace_document_html(record.drive_file_id, html)
        record.content, record.title, record.web_link = content, edr.titulo, upload.web_link
    try:
        await session.commit()
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    return EdrSaved(upload.web_link, created=record is None)
