import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import work_orders
from tests.support.uploads import Upload, make_xlsx_zip


class WorkOrderImportTests(unittest.IsolatedAsyncioTestCase):
    def test_excel_mapping_preserves_chinese_headers_and_labels(self):
        self.assertEqual("待處理", work_orders.STATUS_LABELS["pending"])
        self.assertEqual("緊急", work_orders.PRIORITY_LABELS["critical"])

        mapping = work_orders._detect_columns(["警報代碼", "機台", "描述", "技師", "處理結果"])

        self.assertEqual({
            0: "alarm_code",
            1: "machine_id",
            2: "description",
            3: "assigned_to",
            4: "resolution",
        }, mapping)

    async def test_excel_import_rejects_files_over_server_limit(self):
        tmp_root = Path("tests_tmp") / f"excel_{uuid.uuid4().hex}"
        tmp_root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(tmp_root, ignore_errors=True))

        with patch.object(work_orders, "DB_DIR", str(tmp_root)):
            with patch.object(work_orders, "EXCEL_UPLOAD_MAX_BYTES", 8):
                result = await work_orders.import_excel(
                    file=Upload("orders.xlsx", b"x" * 12),
                    actor={"user_id": "admin01", "role": "admin"},
                )

        self.assertEqual("error", result["status"])
        self.assertIn("Excel upload exceeds", result["message"])

    async def test_excel_import_rejects_corrupt_xlsx_archive_before_openpyxl(self):
        result = await work_orders.import_excel(
            file=Upload("orders.xlsx", b"PK\x03\x04not a valid zip"),
            actor={"user_id": "admin01", "role": "admin"},
        )

        self.assertEqual("error", result["status"])
        self.assertEqual("Invalid XLSX archive", result["message"])

    async def test_excel_import_rejects_large_shared_strings_before_openpyxl(self):
        content = make_xlsx_zip({"xl/sharedStrings.xml": b"a" * 128})

        with patch.object(work_orders, "XLSX_MAX_SHARED_STRINGS_BYTES", 64):
            result = await work_orders.import_excel(
                file=Upload("orders.xlsx", content),
                actor={"user_id": "admin01", "role": "admin"},
            )

        self.assertEqual("error", result["status"])
        self.assertIn("shared strings exceed", result["message"])

    async def test_excel_import_rejects_zip_bomb_compression_ratio(self):
        content = make_xlsx_zip({"xl/worksheets/sheet1.xml": b"0" * 4096})

        with patch.object(work_orders, "XLSX_MAX_COMPRESSION_RATIO", 5):
            result = await work_orders.import_excel(
                file=Upload("orders.xlsx", content),
                actor={"user_id": "admin01", "role": "admin"},
            )

        self.assertEqual("error", result["status"])
        self.assertEqual("XLSX archive compression ratio is too high", result["message"])


if __name__ == "__main__":
    unittest.main()
