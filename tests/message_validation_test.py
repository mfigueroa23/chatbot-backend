import pytest
from src.services.message_validation import validate_user_message
from src.utils.exceptions.message import EmptyMessageError, MessageTooLongError


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_rechaza_mensaje_vacio_o_solo_espacios(text: str):
    with pytest.raises(EmptyMessageError):
        validate_user_message(text)


def test_acepta_5000_caracteres_y_recorta_espacios_exteriores():
    assert validate_user_message(f"  {'a' * 5000}  ") == "a" * 5000


def test_rechaza_5001_caracteres():
    with pytest.raises(MessageTooLongError):
        validate_user_message("a" * 5001)
