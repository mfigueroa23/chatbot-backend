import pytest
from src.models.procedure_field import FieldKind
from src.services.procedures import CONTACT, FieldSpec, missing_or_invalid, validate_field, web_contact_fields


@pytest.mark.parametrize("kind, value, expected", [
    (FieldKind.rut, "12.345.678-5", "12345678-5"),
    (FieldKind.rut, "12345678-k", None),
    (FieldKind.rut, "11.111.111-1", "11111111-1"),
    (FieldKind.rut, "7.654.321-k", None),
    (FieldKind.rut, "7.654.321-6", "7654321-6"),
    (FieldKind.email, " ana@correo.cl ", "ana@correo.cl"),
    (FieldKind.email, "ana@", None),
    (FieldKind.phone, "+56 9 1234 5678", "+56 9 1234 5678"),
    (FieldKind.phone, "123", None),
    (FieldKind.number, "1500000", "1500000"),
    (FieldKind.number, "mil", None),
    (FieldKind.date, "07/10/2026", "07-10-2026"),
    (FieldKind.date, "31-02-2026", None),
    (FieldKind.text, "  Patente ABCD12 ", "Patente ABCD12"),
    (FieldKind.text, "   ", None),
    (CONTACT, "ana@correo.cl", "ana@correo.cl"),
    (CONTACT, "+56 9 1234 5678", "+56 9 1234 5678"),
    (CONTACT, "no sé", None),
])
def test_validate_field_por_tipo(kind, value: str, expected: str | None):
    assert validate_field(kind, value) == expected


def test_validate_missing_or_invalid_separa_faltantes_e_invalidos():
    fields = [FieldSpec("rut", "RUT del titular", FieldKind.rut), FieldSpec("patente", "Patente", FieldKind.text),
              FieldSpec("correo", "Correo", FieldKind.email)]

    check = missing_or_invalid(fields, {"rut": "12.345.678-5", "correo": "ana@"})

    assert check.valid == {"rut": "12345678-5"}
    assert [field.name for field in check.missing] == ["patente"]
    assert [field.name for field in check.invalid] == ["correo"]
    assert not check.complete


def test_validate_web_exige_nombre_y_contacto():
    fields = web_contact_fields()

    assert not missing_or_invalid(fields, {"nombre": "Ana"}).complete
    assert not missing_or_invalid(fields, {"contacto": "ana@correo.cl"}).complete
    assert missing_or_invalid(fields, {"nombre": "Ana", "contacto": "ana@correo.cl"}).complete
