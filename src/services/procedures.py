import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from src.models.procedure_field import FieldKind
from src.services.web_session import EMAIL_PATTERN, is_valid_phone

# Tipo solo de código para el dato de contacto del cliente web: correo o teléfono.
CONTACT: Literal["contact"] = "contact"
MAX_TEXT_LENGTH = 500
NUMBER_PATTERN = re.compile(r"^\d+([.,]\d+)?$")
RUT_PATTERN = re.compile(r"^(\d{1,8})-([\dkK])$")

Kind = FieldKind | Literal["contact"]

@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: Kind

@dataclass(frozen=True)
class FieldCheck:
    valid: dict[str, str] = field(default_factory=dict)
    missing: list[FieldSpec] = field(default_factory=list)
    invalid: list[FieldSpec] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing and not self.invalid

def rut_check_digit(number: str) -> str:
    total = sum(int(digit) * factor for digit, factor in zip(reversed(number), [2, 3, 4, 5, 6, 7] * 2))
    digit = 11 - total % 11
    return {11: "0", 10: "k"}.get(digit, str(digit))

def validate_rut(value: str) -> str | None:
    match = RUT_PATTERN.match(value.replace(".", "").replace(" ", ""))
    if match is None or rut_check_digit(match.group(1)) != match.group(2).lower():
        return None
    return f"{match.group(1)}-{match.group(2).lower()}"

def validate_date(value: str) -> str | None:
    try:
        return datetime.strptime(value.replace("/", "-"), "%d-%m-%Y").strftime("%d-%m-%Y")
    except ValueError:
        return None

def validate_field(kind: Kind, value: str) -> str | None:
    """Devuelve el valor normalizado, o None si no tiene el formato del tipo."""
    value = value.strip()
    if not value or len(value) > MAX_TEXT_LENGTH:
        return None
    match kind:
        case FieldKind.email:
            return value if EMAIL_PATTERN.match(value) else None
        case FieldKind.phone:
            return value if is_valid_phone(value) else None
        case FieldKind.rut:
            return validate_rut(value)
        case FieldKind.number:
            return value if NUMBER_PATTERN.match(value) else None
        case FieldKind.date:
            return validate_date(value)
        case "contact":
            return value if EMAIL_PATTERN.match(value) or is_valid_phone(value) else None
        case _:
            return value

def missing_or_invalid(fields: list[FieldSpec], data: dict[str, str]) -> FieldCheck:
    check = FieldCheck()
    for spec in fields:
        raw = data.get(spec.name)
        if raw is None or not str(raw).strip():
            check.missing.append(spec)
            continue
        value = validate_field(spec.kind, str(raw))
        if value is None:
            check.invalid.append(spec)
        else:
            check.valid[spec.name] = value
    return check

def web_contact_fields() -> list[FieldSpec]:
    # El cliente web es anónimo: el área necesita saber a quién contactar aunque el procedimiento no lo pida.
    return [FieldSpec("nombre", "Nombre", FieldKind.text), FieldSpec("contacto", "Correo o teléfono", CONTACT)]
