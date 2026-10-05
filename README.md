# MaintHub｜設備維修與知識管理

MaintHub 讓工廠人員在同一套系統中查閱設備文件、通報問題、追蹤維修，並保存經過審核的維修經驗。
AI 回答使用本機 Ollama，查詢時附上文件來源與頁碼，方便回頭核對原文。

每家公司獨立部署、保存自己的帳號與資料。導入時使用同一份程式，填寫公司設定，再匯入人員、文件及工單。

**第一次部署，請從 [公司導入 SOP](docs/guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md) 開始。**
目前版本與下載位置見 [9/29 安裝包驗證報告](docs/reports/INSTALL_PACKAGE_ACCEPTANCE_2026-09-29.md)，修正內容見 [更新說明](docs/guides/RELEASE_NOTES_2026-09-28_ZH_TW.md)。
測試站另已新增自行改密碼與臨時密碼流程，尚未納入該固定 ZIP；請依 [密碼測試指南](docs/guides/PASSWORD_ACCEPTANCE_ZH_TW.md) 完成人工測試。

## 可以做什麼

- **查設備文件**：匯入文字型 PDF／SOP，提問後查看回答、原文與引用頁碼。
- **處理維修問題**：從現場通報到派工、維修及確認，追蹤同一筆紀錄。
- **累積維修知識**：維修經驗經管理員核准後，加入知識庫供後續查詢。
- **批次導入資料**：用 Excel 匯入人員與歷史工單，先預覽錯誤，再確認寫入並查閱履歷。
- **管理公司與權限**：設定廠區、產線、設備及知識庫，依角色與產線限制操作範圍。

日常流程：**查詢文件 → 通報問題 → 指派維修 → 填寫維修結果 → 確認完成 → 審核知識入庫**。

| 角色 | 主要工作 |
| --- | --- |
| 操作員 | 查詢文件、通報問題、確認維修結果 |
| 主管 | 指派維修人員、追蹤工單、確認結果 |
| 維修人員 | 接手工單，記錄原因、處置與維修結果 |
| 管理員 | 管理公司設定、帳號、文件、批次匯入及知識審核 |

## 第一次部署

目前驗證的操作環境為 **Windows PowerShell、Docker Desktop 的 Linux containers，以及主機上的 Ollama**。
需要 Python 3.11 或 3.12；每家公司使用獨立的 PostgreSQL 與 Qdrant 儲存資料。

依 [公司導入 SOP](docs/guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md) 按順序完成：

1. **取得部署包**：核對 ZIP 的 SHA256，解壓並檢查共用檔案完整性。
2. **準備工具與模型**：安裝套件、建置映像，準備 Ollama `gemma4:e2b` 及兩個文件檢索模型。
3. **填寫公司設定**：設定公司、產線、設備與知識庫；選定獨立部署目錄、project 名稱及連接埠。
4. **初始化、啟動並登入**：通過啟動檢查後，以管理員首次登入、改密碼，再預覽及套用公司設定。
5. **匯入並驗收**：建立人員、匯入文件與工單，確認查詢引用、角色流程及備份還原都可用。

公司設定可從以下範例複製：

| 範例 | 適用展示 |
| --- | --- |
| [CNC 示範工廠 A](templates/company.cnc-demo.json) | CNC 設備與警報手冊 |
| [空壓機示範工廠 B](templates/company.compressor-demo.json) | 一般設備與文字型 SOP |

範例是模擬設定，不包含正式文件或帳號。設定套用後，仍需建立人員及匯入文件才能查詢。
首次安裝與下載模型需要網路；部署 ZIP 不包含模型、映像或公司執行資料。

## 已部署公司的日常操作

回到原本的基礎目錄，將 `$Deployment` 改成自己的**既有公司部署目錄**：

```powershell
$Deployment = "C:\MaintHubDeployments\company-a"
```

啟動與查看狀態：

```powershell
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" start
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" status
```

備份與停止服務：

```powershell
.\.venv\Scripts\python.exe scripts/company_runtime_backup.py --deployment "$Deployment" backup
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" stop
```

備份會短暫停止該公司的應用程式與 Qdrant。`stop` 保留容器及資料，下次使用 `start` 即可恢復。
主機共用的 Ollama 與 Docker Desktop 需另行關閉；還原及完整收尾步驟見 [SOP 第 8 步](docs/guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md#8-備份重啟及還原)。

## 目前驗收狀態

目前交付版本：`mainthub-company-template-20260929-review.zip`。

| 範圍 | 狀態 |
| --- | --- |
| 本版乾淨部署 | 全新公司資料；啟動、首次登入改密碼、角色流程、批次匯入、補充再送審／核准與不採用通過 |
| 本版 MOCK 查詢 | 兩次真實模型回答與 PDF 原文、頁碼、SHA256 核對通過 |
| 歷史雙公司／完整題庫 | 9/26 版已通過雙公司備份隔離及題庫驗收；未視為本版重跑 |
| 正式公司驗收 | 正式文件品質、兩位人員從乾淨環境獨立依 SOP 導入及簽收仍待完成 |

完整版本、SHA256 與證據見 [本版安裝驗證報告](docs/reports/INSTALL_PACKAGE_ACCEPTANCE_2026-09-29.md)；
剩餘工作見 [目前完成與待辦清單](docs/plans/CURRENT_REFINEMENT_CHECKLIST_ZH_TW.md)。

目前支援可擷取文字的 PDF，尚未提供掃描文件 OCR；複雜表格、圖面與多欄文件需另行核對解析結果。
公司設定中的設備對照用來選擇知識庫，文件是否適用仍須確認。
MOCK 是訓練資料，不能當作實際設備操作指引；查詢與審閱方式見 [查詢品質驗收指南](docs/guides/RAG_DEMO_ACCEPTANCE_ZH_TW.md)。

## 開發測試

以下在原始碼工作目錄執行。開啟獨立 PowerShell 視窗，建立虛擬環境並使用測試資料目錄：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
$env:DATA_STORE = "json"
$env:DB_PATH = "tests_tmp/readme-regression"
$env:ADMIN_INITIAL_PASSWORD = "LocalTestOnly123"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m pytest -q
python -m ruff check .
python -m mypy
```

測試結束後關閉該視窗，再以公司部署設定啟動服務。部署 ZIP 不含 `tests/`；分類與個別執行方式見 [測試說明](tests/README.md)。

其他工程檢查在完成各自的環境與依賴設定後執行：

```powershell
# 主機 Ollama 與檢索模型快取檢查
python scripts/preflight_check.py --ollama-url http://127.0.0.1:11434 --require-ollama-model --require-model-cache

# 雙公司模擬後端流程；輸出目錄須尚未存在
python scripts/verify_company_workflows.py --output outputs/company-demo-run-01
```

主機檢查通過後，仍須依 SOP 驗證容器內的模型連線。
模擬後端流程使用 PDF／BM25 與角色替身，不呼叫 LLM、PostgreSQL 或 Qdrant；真實部署驗收另見前述報告。

## 技術與延伸文件

後端採 FastAPI，前端為 HTML／JavaScript；文件檢索使用 BM25、Qdrant 及嵌入／重排模型，回答由本機 Ollama 生成。
公司標準部署使用 PostgreSQL，另保留 JSON 模式；n8n 為選用整合。

| 想了解的內容 | 文件 |
| --- | --- |
| 完整部署步驟與日常維運 | [公司導入 SOP](docs/guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md) |
| 公司設定、文件解析及匯入欄位 | [共用模板導入說明](docs/guides/COMPANY_TEMPLATE_ZH_TW.md) |
| Ollama、模型下載與離線準備 | [地端模型設定](docs/guides/LOCAL_OLLAMA_ZH_TW.md) |
| 環境設定與其他部署方式 | [部署說明](docs/guides/DEPLOYMENT.md) |
| 開發計畫與歷次進度 | [共用模板實作計畫](docs/plans/REUSABLE_COMPANY_TEMPLATE_PLAN_ZH_TW.md) |
| 其他文件與歷史驗收報告 | [文件總覽](docs/README.md) |
