import smtplib
import pytest
from src.services import mailer as mailer_module
from src.services.mailer import Mailer
from src.utils.exceptions.mail import MailDeliveryError
from tests.fakes import property_session

SMTP_PROPERTIES = {
    "smtp_host": "smtp.autofin.cl",
    "smtp_port": "587",
    "smtp_user": "bot",
    "smtp_password": "secreto",
    "smtp_from": "bot@autofin.cl",
    "smtp_starttls": "true",
}


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host: str, port: int, timeout: float):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def starttls(self):
        pass

    def login(self, user: str, password: str):
        if FakeSMTP.fail:
            raise smtplib.SMTPAuthenticationError(535, b"credenciales incorrectas")

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch):
    FakeSMTP.sent = []
    FakeSMTP.fail = False
    monkeypatch.setattr(mailer_module.smtplib, "SMTP", FakeSMTP)


@pytest.mark.anyio
async def test_envia_el_correo_con_las_properties_smtp():
    await Mailer(property_session(SMTP_PROPERTIES)).send(["rrhh@autofin.cl"], "Consulta", "¿Bono?")

    message = FakeSMTP.sent[0]
    assert message["To"] == "rrhh@autofin.cl"
    assert message["From"] == "bot@autofin.cl"
    assert message.get_content().strip() == "¿Bono?"


@pytest.mark.anyio
async def test_error_smtp_lanza_mail_delivery_error():
    FakeSMTP.fail = True

    with pytest.raises(MailDeliveryError):
        await Mailer(property_session(SMTP_PROPERTIES)).send(["rrhh@autofin.cl"], "Consulta", "¿Bono?")
