from io import BytesIO
from typing import Any, Sequence
import zipfile

from openpyxl import Workbook


ADMIN = {"user_id": "admin01", "role": "admin", "line_scope": ["*"]}


class Upload:
    """Small upload double shared by file validation and import tests."""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.content = content

    async def read(self) -> bytes:
        return self.content


def workbook_bytes(rows: Sequence[Sequence[Any]]) -> bytes:
    workbook = Workbook()
    try:
        for row in rows:
            workbook.active.append(row)
        with BytesIO() as output:
            workbook.save(output)
            return output.getvalue()
    finally:
        workbook.close()


def make_xlsx_zip(entries: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    with BytesIO() as output:
        with zipfile.ZipFile(output, "w", compression=compression) as archive:
            archive.writestr("[Content_Types].xml", b"<Types></Types>")
            for name, content in entries.items():
                archive.writestr(name, content)
        return output.getvalue()
