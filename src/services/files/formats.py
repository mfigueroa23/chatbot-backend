"""Formatos legibles (spec 002, definiciones) y cómo se lee cada uno: imágenes y PDF los transcribe el modelo; Office y
texto se extraen en código (plan 002, D2)."""
from collections.abc import Callable
from pathlib import PurePosixPath
from src.services.files.extractors import decode_text, extract_docx, extract_pptx, extract_xlsx

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

TRANSCRIBED = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    DOCX: extract_docx, XLSX: extract_xlsx, PPTX: extract_pptx,
    "text/plain": decode_text, "text/markdown": decode_text, "text/csv": decode_text, "application/json": decode_text,
}
# Google Chat a veces informa application/octet-stream: la extensión desempata.
BY_EXTENSION = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf",
    ".docx": DOCX, ".xlsx": XLSX, ".pptx": PPTX, ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".json": "application/json",
}
SUPPORTED = "JPG, PNG, WebP, PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), texto, Markdown, CSV y JSON"

def resolve_mime(name: str, content_type: str) -> str:
    mime = content_type.split(";")[0].strip().lower()
    if mime in TRANSCRIBED or mime in EXTRACTORS:
        return mime
    return BY_EXTENSION.get(PurePosixPath(name.lower()).suffix, mime)

def readable(mime_type: str) -> bool:
    return mime_type in TRANSCRIBED or mime_type in EXTRACTORS
