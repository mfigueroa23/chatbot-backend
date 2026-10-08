import json
from dataclasses import dataclass
from typing import Any
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.chat_api_client import service_account_token
from src.services.property import get_str_property
from src.utils.exceptions.drive import DriveFileNotAccessibleError

DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"
GOOGLE_DOC = "application/vnd.google-apps.document"
MULTIPART_BOUNDARY = "edr-boundary"
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

@dataclass(frozen=True)
class DriveUpload:
    id: str
    web_link: str

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

    async def create_document_from_html(self, name: str, folder_id: str, html: str) -> DriveUpload:
        # Drive convierte el HTML en un Google Doc al subirlo con el mimeType de destino.
        metadata = json.dumps({"name": name, "mimeType": GOOGLE_DOC, "parents": [folder_id]})
        body = (f"--{MULTIPART_BOUNDARY}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
                f"--{MULTIPART_BOUNDARY}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n{html}\r\n"
                f"--{MULTIPART_BOUNDARY}--").encode()
        headers = {**await self._headers(), "Content-Type": f"multipart/related; boundary={MULTIPART_BOUNDARY}"}
        response = await self._http.post(f"{DRIVE_UPLOAD_URL}/files", content=body, headers=headers,
                                         params={"uploadType": "multipart", "fields": "id,webViewLink", **ALL_DRIVES})
        return self._upload(response, folder_id)

    async def replace_document_html(self, file_id: str, html: str) -> DriveUpload:
        headers = {**await self._headers(), "Content-Type": "text/html; charset=UTF-8"}
        response = await self._http.patch(f"{DRIVE_UPLOAD_URL}/files/{file_id}", content=html.encode(), headers=headers,
                                          params={"uploadType": "media", "fields": "id,webViewLink", **ALL_DRIVES})
        return self._upload(response, file_id)

    def _upload(self, response: httpx.Response, target: str) -> DriveUpload:
        if response.status_code in (403, 404):
            raise DriveFileNotAccessibleError(target)
        response.raise_for_status()
        body = response.json()
        return DriveUpload(body["id"], body["webViewLink"])

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
