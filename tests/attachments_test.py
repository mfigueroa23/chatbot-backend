import io
import pytest
from docx import Document
from src.services.attachments import Attachment, AttachmentLimits, AttachmentText, read_attachments
from src.services.drive_client import DOCX_EXPORT, DriveFile
from src.utils.exceptions.attachment import AttachmentTooLargeError
from src.utils.exceptions.drive import DriveFileNotAccessibleError
from tests.fakes import FakeAgentLLM

LIMITS = AttachmentLimits(max_bytes=100_000, max_chars=500)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class FakeChatMedia:
    def __init__(self, files: dict[str, bytes], fail: bool = False):
        self.files = files
        self.fail = fail
        self.downloads: list[str] = []

    async def download_media(self, resource_name: str, max_bytes: int | None = None) -> bytes:
        self.downloads.append(resource_name)
        if self.fail:
            raise RuntimeError("caída")
        data = self.files[resource_name]
        if max_bytes is not None and len(data) > max_bytes:
            raise AttachmentTooLargeError(resource_name)
        return data


class FakeDrive:
    account_email = "bot@proyecto.iam.gserviceaccount.com"

    def __init__(self, files: dict[str, tuple[DriveFile, bytes]], private: set[str] | None = None):
        self.files = files
        self.private = private or set()
        self.downloads: list[str] = []
        self.exports: list[tuple[str, str]] = []

    async def file_metadata(self, file_id: str) -> DriveFile:
        if file_id in self.private:
            raise DriveFileNotAccessibleError(file_id)
        return self.files[file_id][0]

    async def download(self, file_id: str) -> bytes:
        self.downloads.append(file_id)
        return self.files[file_id][1]

    async def export(self, file_id: str, mime_type: str) -> bytes:
        self.exports.append((file_id, mime_type))
        return self.files[file_id][1]


def uploaded(name: str, mime_type: str) -> Attachment:
    return Attachment(name, mime_type, resource_name=f"media/{name}")


def from_drive(name: str, file_id: str) -> Attachment:
    return Attachment(name, "", drive_file_id=file_id)


@pytest.mark.anyio
@pytest.mark.parametrize(("name", "mime_type"), [("error.png", "image/png"), ("foto.jpg", "image/jpeg"),
                                                 ("captura.webp", "image/webp"), ("contrato.pdf", "application/pdf")])
async def test_lee_imagenes_y_pdf_transcribiendolos(name, mime_type):
    llm = FakeAgentLLM(transcripts=["Error 500 en el portal de pagos"])

    texts = await read_attachments([uploaded(name, mime_type)], FakeChatMedia({f"media/{name}": b"bin"}), None, llm, LIMITS)

    assert texts == [AttachmentText(name, "read", "Error 500 en el portal de pagos")]
    assert llm.transcribe_calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(("mime_type", "data", "expected"), [
    (DOCX, docx_bytes("Tope de viáticos 30.000"), "Tope de viáticos 30.000"),
    ("text/plain", "cañón".encode("utf-8"), "cañón"),
    ("text/csv", "mes,monto\noctubre,150000".encode("latin-1"), "mes,monto\noctubre,150000"),
    ("application/json", b'{"a": 1}', '{"a": 1}'),
    ("text/markdown", b"# Hola", "# Hola"),
])
async def test_lee_office_y_texto_en_codigo(mime_type, data, expected):
    llm = FakeAgentLLM()

    texts = await read_attachments([uploaded("archivo", mime_type)], FakeChatMedia({"media/archivo": data}), None, llm, LIMITS)

    assert texts == [AttachmentText("archivo", "read", expected)] and llm.transcribe_calls == 0


@pytest.mark.anyio
async def test_lee_un_documento_nativo_de_drive_exportandolo():
    drive = FakeDrive({"D1": (DriveFile("D1", "Minuta", "application/vnd.google-apps.document", None), docx_bytes("Acuerdos"))})

    texts = await read_attachments([from_drive("Minuta", "D1")], FakeChatMedia({}), drive, FakeAgentLLM(), LIMITS)

    assert texts == [AttachmentText("Minuta", "read", "Acuerdos")] and drive.exports == [("D1", DOCX_EXPORT)]


@pytest.mark.anyio
async def test_mas_de_20_mb_no_se_lee():
    chat = FakeChatMedia({"media/grande.pdf": b"x" * 100_001})
    drive = FakeDrive({"D2": (DriveFile("D2", "enorme.pdf", "application/pdf", 200_000), b"")})
    llm = FakeAgentLLM()

    texts = await read_attachments([uploaded("grande.pdf", "application/pdf"), from_drive("enorme.pdf", "D2")],
                                   chat, drive, llm, LIMITS)

    assert [text.status for text in texts] == ["too_large", "too_large"]
    assert drive.downloads == [] and llm.transcribe_calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("mime_type", ["video/mp4", "audio/mpeg", "application/zip"])
async def test_formato_no_legible_no_se_descarga(mime_type):
    chat = FakeChatMedia({"media/x": b"bin"})

    texts = await read_attachments([uploaded("x", mime_type)], chat, None, FakeAgentLLM(), LIMITS)

    assert texts == [AttachmentText("x", "unsupported")] and chat.downloads == []


@pytest.mark.anyio
async def test_drive_sin_acceso_indica_la_cuenta_para_compartir():
    drive = FakeDrive({}, private={"D3"})

    texts = await read_attachments([from_drive("privado.pdf", "D3")], FakeChatMedia({}), drive, FakeAgentLLM(), LIMITS)

    assert texts == [AttachmentText("privado.pdf", "not_accessible", "", "bot@proyecto.iam.gserviceaccount.com")]


@pytest.mark.anyio
async def test_un_fallo_de_lectura_no_impide_leer_el_resto():
    class HalfBroken(FakeChatMedia):
        async def download_media(self, resource_name: str, max_bytes: int | None = None) -> bytes:
            if resource_name == "media/roto.txt":
                raise RuntimeError("caída")
            return await super().download_media(resource_name, max_bytes)

    texts = await read_attachments([uploaded("roto.txt", "text/plain"), uploaded("bien.txt", "text/plain")],
                                   HalfBroken({"media/bien.txt": b"contenido"}), None, FakeAgentLLM(), LIMITS)

    assert texts == [AttachmentText("roto.txt", "failed"), AttachmentText("bien.txt", "read", "contenido")]


@pytest.mark.anyio
async def test_texto_largo_se_trunca_y_se_indica():
    texts = await read_attachments([uploaded("largo.txt", "text/plain")], FakeChatMedia({"media/largo.txt": b"a" * 900}),
                                   None, FakeAgentLLM(), LIMITS)

    assert texts == [AttachmentText("largo.txt", "truncated", "a" * 500)]


@pytest.mark.anyio
async def test_varios_archivos_en_su_orden():
    chat = FakeChatMedia({"media/a.txt": b"uno", "media/b.txt": b"dos"})

    texts = await read_attachments([uploaded("a.txt", "text/plain"), uploaded("b.txt", "text/plain")], chat, None,
                                   FakeAgentLLM(), LIMITS)

    assert [(text.name, text.text) for text in texts] == [("a.txt", "uno"), ("b.txt", "dos")]
