"""Especificación de requerimientos de desarrollo (EDR) con la estructura de agente-ti (spec 003, RF-9, RF-10, RF-18).
Los modelos son los de la 1.x (spec 005): la plantilla guardada en la base anterior usa estos mismos campos."""
import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field
from src.services.property import Properties
from src.utils.exceptions.edr import EdrNotConfiguredError
from src.utils.exceptions.property import PropertyNotFoundError

PENDIENTE_DEFINIR = "[PENDIENTE DEFINIR]"
TEMPLATE_PROPERTY = "edr_template_base64"
FOLDER_PROPERTY = "edr_drive_folder_id"
SERVICE_ACCOUNT_PROPERTY = "google_chat_service_account_json"
# La plantilla viene de la BD: el sandbox impide que salga del EDR hacia el intérprete (plan 003, D8).
TEMPLATES = SandboxedEnvironment(autoescape=True)

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
class EdrConfig:
    """Lo que hace falta para guardar un EDR, leído de la foto de properties del mensaje (spec 003, RF-18, RF-19)."""
    template: str
    folder_id: str
    service_account: dict[str, Any]

def edr_config(properties: Properties) -> EdrConfig:
    """Lanza EdrNotConfiguredError si falta algo o la plantilla no es base64 válido: mejor no generar el EDR que
    guardarlo con otro formato en silencio. El error nombra la clave, nunca el valor."""
    try:
        template = base64.b64decode(properties.required(TEMPLATE_PROPERTY), validate=True).decode("utf-8")
        service_account = json.loads(properties.required(SERVICE_ACCOUNT_PROPERTY))
        return EdrConfig(template, properties.required(FOLDER_PROPERTY), service_account)
    except PropertyNotFoundError as exc:
        raise EdrNotConfiguredError(f"falta la property {exc.key}") from exc
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise EdrNotConfiguredError(f"{TEMPLATE_PROPERTY} no es base64 válido") from exc
    except ValueError as exc:
        raise EdrNotConfiguredError(f"{SERVICE_ACCOUNT_PROPERTY} no es JSON válido") from exc

def render_edr_html(edr: EdrDocument, template: str) -> str:
    return TEMPLATES.from_string(template).render(edr=edr, pending=PENDIENTE_DEFINIR)

# Nombres de las secciones como se le dicen al colaborador, en el orden del EDR.
SECTIONS = {
    "objetivo_general": "objetivo general", "vision_general": "visión general", "product_owner": "product owner",
    "equipo_desarrollo": "equipo de desarrollo", "aplicaciones_afectadas": "aplicaciones afectadas",
    "usuarios_afectados": "usuarios afectados", "requerimientos": "requerimientos",
    "especificaciones_rf": "especificaciones de cada RF", "roles_permisos": "roles y permisos", "impacto": "impacto",
    "infraestructura": "infraestructura", "seguridad": "seguridad", "criterios_aceptacion": "criterios de aceptación",
    "validaciones_cartera": "validaciones de cartera", "glosario": "glosario",
}

def pending_sections(edr: EdrDocument) -> list[str]:
    """Secciones que siguen en «[PENDIENTE DEFINIR]» o vacías, para contarlas al colaborador (spec 003, RF-13)."""
    data = edr.model_dump(include=set(SECTIONS))
    return [label for field, label in SECTIONS.items() if data[field] in (PENDIENTE_DEFINIR, None, [])]
