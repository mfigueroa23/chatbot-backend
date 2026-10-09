"""Google Docs del EDR en Drive con la cuenta de servicio (spec 003, RF-10, RF-12; plan D7): solo ve la carpeta que se
compartió con ella. Recuperado de la 1.x (spec 005)."""
import json
from dataclasses import dataclass
from typing import Any
import httpx
from src.services.google.service_account import service_account_token

DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_DOC = "application/vnd.google-apps.document"
MULTIPART_BOUNDARY = "edr-boundary"
# Los archivos de una unidad compartida solo aparecen con este parámetro.
ALL_DRIVES = {"supportsAllDrives": "true"}

@dataclass(frozen=True)
class DriveUpload:
    id: str
    web_link: str

class DriveClient:
    def __init__(self, http: httpx.AsyncClient, service_account: dict[str, Any]):
        self._http = http
        self._service_account = service_account

    async def create_document_from_html(self, name: str, folder_id: str, html: str) -> DriveUpload:
        # Drive convierte el HTML en un Google Doc al subirlo con el mimeType de destino.
        metadata = json.dumps({"name": name, "mimeType": GOOGLE_DOC, "parents": [folder_id]})
        body = (f"--{MULTIPART_BOUNDARY}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
                f"--{MULTIPART_BOUNDARY}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n{html}\r\n"
                f"--{MULTIPART_BOUNDARY}--").encode()
        headers = {**await self._headers(), "Content-Type": f"multipart/related; boundary={MULTIPART_BOUNDARY}"}
        response = await self._http.post(f"{DRIVE_UPLOAD_URL}/files", content=body, headers=headers,
                                         params={"uploadType": "multipart", "fields": "id,webViewLink", **ALL_DRIVES})
        return self._upload(response)

    async def replace_document_html(self, file_id: str, html: str) -> DriveUpload:
        headers = {**await self._headers(), "Content-Type": "text/html; charset=UTF-8"}
        response = await self._http.patch(f"{DRIVE_UPLOAD_URL}/files/{file_id}", content=html.encode(), headers=headers,
                                          params={"uploadType": "media", "fields": "id,webViewLink", **ALL_DRIVES})
        return self._upload(response)

    def _upload(self, response: httpx.Response) -> DriveUpload:
        response.raise_for_status()
        body = response.json()
        return DriveUpload(body["id"], body["webViewLink"])

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await service_account_token(self._http, self._service_account, DRIVE_SCOPE)}"}
