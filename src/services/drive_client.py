import json
from dataclasses import dataclass
from typing import Any
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.chat_api_client import service_account_token
from src.services.property import get_str_property
from src.utils.exceptions.drive import DriveFileNotAccessibleError

DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DOCX_EXPORT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_EXPORT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_EXPORT = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# Los archivos de una unidad compartida solo aparecen con este parámetro.
ALL_DRIVES = {"supportsAllDrives": "true"}

@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None  # Google Docs, Sheets y Slides nativos no informan tamaño

class DriveClient:
    """Drive con la cuenta de servicio del asistente: solo ve lo que se compartió con ella o con su unidad."""

    def __init__(self, http: httpx.AsyncClient, service_account: dict[str, Any]):
        self._http = http
        self._service_account = service_account

    @property
    def account_email(self) -> str:
        return self._service_account["client_email"]

    async def file_metadata(self, file_id: str) -> DriveFile:
        response = await self._get(f"{DRIVE_API_URL}/files/{file_id}", file_id, fields="id,name,mimeType,size")
        body = response.json()
        size = body.get("size")
        return DriveFile(body["id"], body["name"], body["mimeType"], int(size) if size is not None else None)

    async def download(self, file_id: str) -> bytes:
        return (await self._get(f"{DRIVE_API_URL}/files/{file_id}", file_id, alt="media")).content

    async def export(self, file_id: str, mime_type: str) -> bytes:
        return (await self._get(f"{DRIVE_API_URL}/files/{file_id}/export", file_id, mimeType=mime_type)).content

    async def _get(self, url: str, file_id: str, **params: str) -> httpx.Response:
        response = await self._http.get(url, params={**params, **ALL_DRIVES}, headers=await self._headers())
        if response.status_code in (403, 404):
            raise DriveFileNotAccessibleError(file_id)
        response.raise_for_status()
        return response

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await service_account_token(self._http, self._service_account, DRIVE_SCOPE)}"}

async def build_drive_client(session: AsyncSession, http: httpx.AsyncClient) -> DriveClient:
    # Misma cuenta de servicio que Google Chat, con el scope de Drive.
    return DriveClient(http, json.loads(await get_str_property(session, "google_chat_service_account_json")))
