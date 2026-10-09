import pytest
from src.services.message_validation import EMPTY_MESSAGE, TOO_LONG_MESSAGE, validate_user_message
from src.utils.exceptions.message import InvalidMessageError


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_rechaza_mensaje_vacio_o_solo_espacios(text: str):
    with pytest.raises(InvalidMessageError) as error:
        validate_user_message(text)

    assert error.value.reply == EMPTY_MESSAGE


def test_acepta_5000_caracteres_y_recorta_espacios_exteriores():
    assert validate_user_message(f"  {'a' * 5000}  ") == "a" * 5000


def test_rechaza_5001_caracteres_avisando_el_limite():
    with pytest.raises(InvalidMessageError) as error:
        validate_user_message("a" * 5001)

    assert error.value.reply == TOO_LONG_MESSAGE and "5000" in TOO_LONG_MESSAGE
