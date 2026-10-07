import asyncio
import smtplib
from email.message import EmailMessage
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.property import get_int_property, get_str_property
from src.utils.exceptions.mail import MailDeliveryError
from src.utils.exceptions.property import PropertyNotFoundError

SMTP_TIMEOUT_SECONDS = 15

class Mailer:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def send(self, to: list[str], subject: str, body: str) -> None:
        try:
            host = await get_str_property(self._session, "smtp_host")
            port = await get_int_property(self._session, "smtp_port")
            user = await get_str_property(self._session, "smtp_user")
            password = await get_str_property(self._session, "smtp_password")
            sender = await get_str_property(self._session, "smtp_from")
            starttls = (await get_str_property(self._session, "smtp_starttls")).lower() == "true"
        except PropertyNotFoundError as exc:
            raise MailDeliveryError(str(exc)) from exc
        message = EmailMessage()
        message["From"] = sender
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message.set_content(body)
        try:
            # smtplib es síncrono: se ejecuta en un hilo para no bloquear el event loop.
            await asyncio.to_thread(deliver, host, port, user, password, starttls, message)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailDeliveryError(str(exc)) from exc

def deliver(host: str, port: int, user: str, password: str, starttls: bool, message: EmailMessage) -> None:
    with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        if starttls:
            smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(message)
