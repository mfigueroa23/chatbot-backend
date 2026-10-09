"""Archivos de un mensaje convertidos en texto, una vez, al recibirlos (spec 002, RF-31 a RF-41; plan D1). No conoce
Google: recibe la descarga como un Protocol, así que otro origen (Drive o el web) se suma sin tocar la lectura (D16).
El texto entra en el mensaje del colaborador: queda en el historial y se usa en los mensajes siguientes (RF-35)."""
import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from src.agents.llm import Transcriber
from src.agents.prompts import information
from src.services.files.formats import EXTRACTORS, SUPPORTED, TRANSCRIBED, readable, resolve_mime
from src.services.property import Properties
from src.utils.exceptions.attachment import AttachmentTooLargeError

logger = logging.getLogger(__name__)

AttachmentStatus = Literal["read", "truncated", "too_large", "unsupported", "failed"]
FILES_SOURCE = "archivos compartidos"

@dataclass(frozen=True)
class Attachment:
    name: str
    content_type: str
    resource_name: str | None = None  # None si no se puede descargar (por ejemplo, un enlace de Drive)

@dataclass(frozen=True)
class AttachmentText:
    name: str
    status: AttachmentStatus
    text: str = ""

@dataclass(frozen=True)
class AttachmentLimits:
    max_bytes: int = 20 * 1024 * 1024
    max_chars: int = 30_000

def limits_from(properties: Properties) -> AttachmentLimits:
    return AttachmentLimits(properties.get_int("file_max_mb", 20) * 1024 * 1024,
                            properties.get_int("file_max_chars", 30_000))

class MediaDownloader(Protocol):
    async def download(self, resource_name: str, max_bytes: int) -> bytes: ...

async def read_attachments(attachments: Sequence[Attachment], media: MediaDownloader, transcriber: Transcriber,
                           limits: AttachmentLimits) -> list[AttachmentText]:
    # En paralelo: transcribir una imagen o un PDF tarda segundos (spec 002, RNF-7). Un archivo que falla no detiene
    # a los demás (RF-39).
    return list(await asyncio.gather(*(read_one(item, media, transcriber, limits) for item in attachments)))

async def read_one(attachment: Attachment, media: MediaDownloader, transcriber: Transcriber,
                   limits: AttachmentLimits) -> AttachmentText:
    name = attachment.name
    mime = resolve_mime(name, attachment.content_type)
    if attachment.resource_name is None or not readable(mime):
        return AttachmentText(name, "unsupported")
    try:
        data = await media.download(attachment.resource_name, limits.max_bytes)
        text = await transcriber.transcribe(data, mime) if mime in TRANSCRIBED else EXTRACTORS[mime](data)
    except AttachmentTooLargeError:
        return AttachmentText(name, "too_large")
    except Exception as exc:
        # Sin el contenido en el log: solo el tipo de error (spec 002, RNF-9).
        logger.warning("No se pudo leer el archivo %s: %s", name, type(exc).__name__)
        return AttachmentText(name, "failed")
    if len(text) > limits.max_chars:
        return AttachmentText(name, "truncated", text[:limits.max_chars])
    return AttachmentText(name, "read", text)

def status_line(item: AttachmentText, limits: AttachmentLimits) -> str:
    max_mb = limits.max_bytes // (1024 * 1024)
    return {
        "read": f"[{item.name} · leído]",
        "truncated": f"[{item.name} · leído en parte: es más largo de lo que se puede usar; dile a la persona que leíste "
                     "solo una parte]",
        "too_large": f"[{item.name} · supera los {max_mb} MB: no se leyó]",
        "unsupported": f"[{item.name} · formato no admitido: se admiten {SUPPORTED}]",
        "failed": f"[{item.name} · no se pudo leer]",
    }[item.status]

def files_block(items: Sequence[AttachmentText], limits: AttachmentLimits) -> str:
    """Bloque de información con una línea de estado por archivo y su texto (RF-37 a RF-41)."""
    parts = [status_line(item, limits) + (f"\n{item.text}" if item.text else "") for item in items]
    return information(FILES_SOURCE, "\n\n".join(parts))
