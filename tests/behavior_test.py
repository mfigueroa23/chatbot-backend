from src.agents.behavior import requester_key
from src.services.area_notifier import Requester


def test_requester_key_usa_el_correo_de_google_chat_o_web():
    assert requester_key(Requester("Ana", "ana@autofin.cl", "google_chat")) == "ana@autofin.cl"
    assert requester_key(None) == "web"
    assert requester_key(Requester(None, None, "google_chat")) == "anonymous"
