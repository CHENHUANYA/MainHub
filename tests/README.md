# 測試目錄

測試依功能分類，從專案根目錄執行。共用資料產生工具放在 `support/`，跨功能的 pytest fixture 放在 `conftest.py`；測試檔不互相匯入。

| 目錄 | 範圍 |
| --- | --- |
| `company/` | 公司設定、設備對照、文件領域與模板封裝 |
| `workflow/` | 通報、工單、歷史資料匯入與知識審核 |
| `documents/` | 文件上傳、解析與索引匯入 |
| `rag/` | 檢索、Ollama 呼叫、來源引用與回答評估 |
| `api/` | API 契約、統計、設定、分頁與請求限制 |
| `auth/`、`security/` | 登入、角色權限、憑證與安全回歸 |
| `storage/` | JSON／PostgreSQL repository、交易與向量儲存 |
| `postgresql/` | PostgreSQL 遷移、備份、還原及維運工具 |
| `operations/` | 部署檢查、環境工具、文件連結與專案檔案規則 |
| `frontend/` | 靜態資源、前後端路徑與瀏覽器工具設定 |
| `browser/` | 實際無頭瀏覽器操作；使用隔離測試 API |
| `js/` | Node.js 前端單元測試 |
| `support/` | 共用上傳替身、Excel 與 ZIP 測試資料產生工具 |

## 執行方式

先依 [專案 README](../README.md#開發測試) 安裝開發依賴，在獨立 PowerShell 視窗設定隔離環境：

```powershell
$env:DATA_STORE = "json"
$env:DB_PATH = "tests_tmp/local-regression"
$env:ADMIN_INITIAL_PASSWORD = "LocalTestOnly123"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m pytest -q
```

只執行本次修改相關的分類：

```powershell
python -m pytest -q tests/company tests/workflow
python -m pytest -q tests/rag
python -m pytest -q tests/browser
node --test tests/js/*.test.js
```

不執行無頭瀏覽器時，可用 `python -m pytest -q --ignore=tests/browser`。
目前瀏覽器測試使用 Playwright 與本機 Microsoft Edge；缺少其中之一會標記為 skipped。
測試使用角色替身與臨時資料，不能當成正式登入、部署隔離或模型回答品質的驗收。

## 測試資料與快取

- 優先使用 pytest 的 `tmp_path`，共用工具只產生模擬資料。
- 不把產出的 Excel、截圖、資料庫、憑證或模型放入 `tests/`。
- `PYTHONDONTWRITEBYTECODE=1` 可避免 Python 位元碼快取；本專案已停用 pytest 快取。
- `tests_tmp/` 是另一個工作目錄，可能包含人工保留的驗證產物；不應當作 `tests/` 的快取整包刪除。
