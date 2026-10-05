# 共用模板導入

本版：`mainthub-company-template-20260929-password`；修正內容見 [更新說明（含 9/29 密碼修正）](RELEASE_NOTES_2026-09-28_ZH_TW.md)。

**第一次導入請從 [相同基礎檔案的公司導入 SOP](COMPANY_DEPLOYMENT_SOP_ZH_TW.md) 開始。**
交付標準為不同人取得同一份基礎包，只填設定、建立帳號及匯入資料，依步驟完成；正常導入不修改程式。
本頁提供設定欄位與功能細節，SOP 是新部署的操作入口。
新部署的啟動、狀態查詢及重啟使用 `scripts/company_service.py`；工具會隔離其他公司殘留的 shell 設定。

本次完成：公司設定包、欄位與參照驗證、管理員預覽／套用、角色畫面的公司名稱與動態選單、
設備到知識庫對照、共用預設值、通用文字型 PDF 解析與領域提示詞切換。
沿用查詢、問題、工單、權限及 JSON／PostgreSQL 儲存層。

AI 已改為僅使用本機 Ollama，預設 `gemma4:e2b`，學校 API 連線已移除。
模型下載與離線快取準備見 [地端模型設定](LOCAL_OLLAMA_ZH_TW.md)。

已提供兩家公司隔離的模擬後端流程驗證，涵蓋 PDF／BM25 查詢、通報、派工、結案與知識審核入庫。
歷史版本的兩家公司已通過真實瀏覽器角色流程與部署還原隔離；各交付包須另核對其 ZIP SHA256、映像及驗收報告，不能沿用舊版結果當作新包通過。
PostgreSQL 標準部署已支援人員批次預覽、首次改密碼及匯入履歷。
另已備妥 CNC／空壓機各五題的 MOCK 品質與失敗案例，操作見 [查詢展示驗收](RAG_DEMO_ACCEPTANCE_ZH_TW.md)。
尚未完成：正式公司文件的領域品質簽收，
以及由不同人拿同一基礎包、從乾淨環境只照 SOP 完成的交付驗收。

## 本次清理

- 將前端與執行時的固定手冊選項移至 `templates/company.legacy.json`，保留舊知識庫 ID。
- n8n 改為選用 `automation` profile；API 與既有整合能力保留。
- 移除固定容器名稱，使用 `docker compose exec alarm_rag ...` 操作服務。
- 模板封裝排除 `.env`、正式帳號、文件、資料庫、索引、備份、模型快取及歷史計畫／報告。
- 原始工作目錄的正式資料、文件與備份保留。歷史報告不放進部署包，不刪除研發紀錄。

## 公司設定包

- `templates/company.cnc-demo.json`：CNC 工廠 A，模擬設備與產線。
- `templates/company.compressor-demo.json`：空壓機工廠 B，模擬設備與產線。
- `templates/company.legacy.json`：未導入公司設定時的舊部署相容選项。

每份 JSON 包含公司、廠區、產線、设备、型號、知識庫、預設值與流程選項。
ID 限英數字、底線及連字號，最長 64 字；設備需指向已宣告的產線和知識庫。
不放帳密、金鑰或正式文件。設備 ID、產線 ID 及知識庫 ID 是穩定識別，既有資料不會隨設定重命名。

## 文件解析與領域提示詞

每個知識庫的兩項設定現在會影響執行行為：

| 設定 | 選項 | 行為 |
| --- | --- | --- |
| `parser` | `sinumerik_alarm_v1` | 沿用 SINUMERIK 警報碼、頁首頁尾與一般章節切分規則。 |
| `parser` | `text_v1` | 擷取文字型 PDF／SOP，保留短行與字母設備代碼，依頁分段並限制段落長度，不推定警報碼。 |
| `prompt_profile` | `cnc_maintenance_v1` | CNC 手冊查詢、診斷與對話提示詞。 |
| `prompt_profile` | `maintenance_v1` | 依來源文件回答一般設備問題，不預設廠牌、控制器或 CNC 警報分類。 |

畫面 PDF 上傳與 `python ingest.py --pdf ... --name ...` 都讀取公司設定中的解析器。
通用 SOP 不要求警報碼；請用自然語言查詢，也可在問題中保留 `AIR-01`、`E-42` 等完整代碼。
不會將這些字母代碼轉換成 CNC 數字警報。無法擷取文字的掃描 PDF 會回報需要 OCR，
本版尚未提供 OCR。版面複雜的表格、圖面及多欄 PDF 仍需另外驗證文字順序。

每個索引段落保留文件 ID、來源檔名、頁碼、段落 ID、解析器與知識庫。
一般設備提示詞要求引用來源、區分模擬與正式文件，資料不足時說明缺少的證據。
一般維護回覆會檢查原文摘錄、繁中說明及對應檔名／頁碼，格式不符最多重試一次；仍不符則標記未完成的備援回覆。
這類串流在檢查完成後才送出正文，因此首次文字會較晚出現。格式檢查不取代事實、翻譯及設備適用性的人工審閱。
自由聊天使用預設知識庫的領域提示詞，但未檢索文件，不能視為有文件引用的回答。

切換解析器不會自動改寫既有索引；請重新匯入文件並確認來源。
本版 CNC 解析保留 `Explanation`／`Remedy` 等原文欄位標題。先前索引不會自動補回被省略的標題；
既有部署升級時須先備份，再由管理員透過文件管理移除該文件的舊索引、重新上傳原 PDF 並核對來源。
只重新啟動服務或重建既有向量，不會重新解析原 PDF。本次全新導入直接使用新版解析器，不需這項升級操作。
CLI 若遇到相同文件雜湊，需使用 `--force`；`text_v1` 不接受 `--no-general`。
CLI 仍沿用整個知識庫重建行為；多文件知識庫請使用管理畫面的既有逐文件匯入流程。

## 全新獨立部署

統一依 [導入 SOP](COMPANY_DEPLOYMENT_SOP_ZH_TW.md) 使用 `init_company_deployment.py` 建立全新 PostgreSQL 部署，
由工具產生獨立帳密、Cookie 與服務設定。不要自行混搭其他 Compose 覆蓋檔作為新人的標準操作路徑。
發行方使用 `scripts/export_company_template.py` 產生相同的基礎 ZIP 給不同導入人員。

舊部署升級另依原有維運說明處理，不與全新導入混用。`20260921_0010` 移除固定手冊預設；`20260923_0011` 新增工單匯入識別碼、
來源資訊及唯一約束；`20260924_0012` 新增人員／工單匯入批次履歷。既有工單保留，舊匯入紀錄不自動推算識別碼或補建履歷。
既有部署請先依操作文件備份；移除固定容器名稱後，Compose 操作以服務名稱為準。

## 設定來源與 API

公司設定明確套用後，保存在既有 `system_settings.json` 或 PostgreSQL `system_settings` 中。
重啟不重新匯入範例、不覆寫管理員預設值。管理員再次套用必須先取得最新預覽版本。

- `GET /company-config`：已登入使用者可讀的展示設定；設備與產線依帳號範圍篩選。
- `POST /company-config/preview`：管理員傳 `{ "config": <設定包> }`，回傳前後內容與 `expected_revision`。
- `PUT /company-config`：管理員傳同一份 `config` 與預覽取得的 `expected_revision`。
- `PATCH /system-settings`：沿用既有管理設定與版本檢查；預設知識庫限公司設定的清單。

新增紀錄保留原本 `manual` 欄位。指定設備時依對照選擇知識庫與產線；明確指定不一致時拒絕。
設定包模式遇到未知設備、未知知識庫或錯誤產線會回傳錯誤；未指定設備與手冊時採公司預設。
修改既有通報或工單的設備／產線時，同樣驗證對照與使用者產線權限；不允許換成其他知識庫的設備。
只修改狀態、優先級等其他欄位時，不重新驗證已退役的歷史設備對照，也不改寫原有知識庫。
舊部署未套用設定包前容許既有額外知識庫與手動設備編號，作為相容過渡。

公司設定清單與索引就緒狀態分開；修改公司 ID 不會隔離資料，也不會清空歷史資料。
切換不同公司的展示應使用獨立測試部署，不要在正式環境輪流套用兩家公司的設定。

## 歷史工單預覽與確認

管理員在資料匯入或維運頁面選取 `.xlsx` 後，會先顯示有效筆數、錯誤列、實際採用的知識庫及狀態。
展開各列可檢查內容；取消不寫入，確認只匯入有效列。每次限 1000 筆資料、32 欄，並沿用上傳容量與 ZIP 解壓限制。

建議使用英文欄名，首列至少包含 `alarm_code`，同一欄位不能用不同別名重複出現。

| 欄位 | 規則 |
| --- | --- |
| `alarm_code` | 必填，可使用字母異常代碼 |
| `machine_id`、`manual` | 可省略；指定設備時依公司對照選知識庫，未知或互相衝突即列為錯誤 |
| `priority` | `low`、`medium`、`high`、`critical`；空白採 `medium`，拼錯不自動改值 |
| `status` | `pending`、`assigned`、`in_progress`、`completed`、`verified`、`cancelled`；空白採 `pending` |
| `assigned_to` | 可空白；有值時必須為存在且啟用中的 `maintenance` 帳號 ID，不能填姓名或其他角色 |
| `source`、`source_record_id` | 來源系統及其原始紀錄 ID；相同來源與 ID 視為同一事件，即使內容有修改也不再新增 |
| `description`、`notes`、`resolution` | 問題描述、備註、處理結果；預覽顯示實際寫入內容 |
| `root_cause`、`repair_action` | 根本原因與維修動作；完成工單需符合既有結案規則 |
| `verified_by` | 不採信歷史檔案的驗證身分，預覽會提示忽略 |

`verified` 會轉成 `completed`，仍需在系統內由有權限的人員驗證。符合條件的維修紀錄成為待審核知識，
不會直接加入知識庫。空白列忽略；未辨識出標題時沿用舊版固定欄位順序，正式導入建議一律加標題。

API 已改為兩步，舊的直接上傳呼叫需同步修改：

1. `POST /work-orders/import-excel/preview`：multipart 欄位 `file`；回傳 `rows`、`valid`、`skipped`、`candidate_count` 與 `preview_token`。
2. `POST /work-orders/import-excel`：multipart 同一份 `file` 與 `preview_token`。確認前重新檢查檔案、操作者、指派帳號、公司設定及工單版本。預覽後帳號停用、刪除或改角色，必須重新預覽。

成功匯入後，同一預覽憑據再次確認會因工單已變動而拒絕。JSON 使用一次原子檔案寫入，PostgreSQL 沿用交易提交；
寫入失敗不回報成功。連線中斷時先查閱工單，再決定是否重試。
同批次及跨批次重複列會顯示錯誤並略過；更換檔名、欄位順序或重新預覽不會避開去重。
有 `source_record_id` 時以「來源＋來源紀錄 ID」辨識；未填時以正規化後的匯入內容辨識。
內容完全相同的不同事件必須提供不同的來源紀錄 ID；沒有 ID 的列修改內容後，會視為新紀錄。
`source` 空白時為 `excel`；來源 ID 在同一部署的該來源內必須唯一，不依設備分開計算。

工單保存不可變的 `import_key` 與 `import_metadata`（檔案 SHA256、原始列號、來源 ID、匯入人員）。
後續編輯或軟刪除工單不清除識別碼。去重涵蓋本版之後匯入且仍保存在工單儲存區的紀錄；
升級前匯入、移出工單儲存區的封存資料及永久清除資料不在這項保證內。
### 人員批次建立與匯入履歷（PostgreSQL）

在管理後台「使用者」下載六欄 Excel 範本，填寫 `user_id`、`name`、`role`、`team`、`line_scope`、`password`。
姓名、團隊可留白，其餘必填；每次最多 200 筆、檔案最多 1 MB。角色與產線依公司設定檢查，不接受公式。
帳號 ID 同批及跨批去重，僅新增有效列，不覆寫既有帳號。新帳號首次登入在畫面設定個人密碼。
完整填寫及操作步驟見 [SOP 第 6 步](COMPANY_DEPLOYMENT_SOP_ZH_TW.md#6-建立人員匯入文件與工單)。

管理員可在「資料匯入」查閱、篩選及分頁瀏覽人員／工單批次，展開查看原始列號、紀錄 ID、錯誤與警告。
履歷包含檔名、SHA256、執行人員與新增／略過數；不保存試算表原始內容、密碼或密碼雜湊。
成功履歷與資料在同一 PostgreSQL 交易提交，任一失敗全部回滾；確認失敗另嘗試記錄，資料庫不可用時可能無履歷。
預覽、取消及未進入確認的格式錯誤不建立履歷，升級前的舊匯入不回填。
JSON 舊模式保留工單預覽與去重；人員批次及此履歷頁面須使用 PostgreSQL 標準部署。

技術介面為 `GET /users/import-template`、`POST /users/import-excel/preview`、`POST /users/import-excel`，
以及 `GET /imports/batches`、`GET /imports/batches/{batch_id}`，均限管理員。
確認人員匯入需送相同檔案與 `preview_token`；帳號或公司設定改變後必須重新預覽。

## 操作與備份

### 建立全新的 PostgreSQL 公司部署

先準備本機映像與完整模型快取。以下指令從原始碼建立新目錄，不複製舊公司的資料或帳密：

```powershell
docker build -t mainthub:local-acceptance .
python scripts/init_company_deployment.py --output outputs/company-cnc --company-config templates/company.cnc-demo.json --project mainthub-cnc --port 8131 --embedding mixedbread-ai/mxbai-embed-large-v1 --reranker cross-encoder/ms-marco-MiniLM-L-6-v2
python scripts/init_company_deployment.py --output outputs/company-air --company-config templates/company.compressor-demo.json --project mainthub-air --port 8132 --embedding mixedbread-ai/mxbai-embed-large-v1 --reranker cross-encoder/ms-marco-MiniLM-L-6-v2
docker compose --env-file outputs/company-cnc/.env -f outputs/company-cnc/compose.company.json up -d
docker compose --env-file outputs/company-air/.env -f outputs/company-air/compose.company.json up -d
```

模型參數應與已安裝快取一致；上例是本機驗收使用的模型。每家公司有獨立 project、連接埠、資料庫名稱、
帳密、登入 Cookie 與資料目錄。只共用唯讀模型快取及主機 Ollama；同時推論會共用主機算力。
PostgreSQL 與 Qdrant 不公開主機連接埠。公司 JSON 準備在新部署根目錄，首次登入後須在管理後台預覽及套用。
初始管理員密碼位於各部署的 `.env`，首次登入須更換；不要分享 `.env` 或驗收帳密檔。

Qdrant 使用各 project 專屬 Docker 命名磁碟區，避免 Windows bind mount 導致重啟後資料損壞。
依據 [Qdrant 官方檔案系統限制](https://qdrant.tech/documentation/common-errors/)，Windows 的共享掛載不完全相容 POSIX。
原有 `qdrant_data` 資料夾與舊 PostgreSQL volumes 不會自動搬移或刪除。

### 完整公司備份與還原

對上述工具建立的部署使用：

```powershell
python scripts/company_runtime_backup.py --deployment outputs/company-cnc backup
python scripts/company_runtime_backup.py --deployment outputs/company-cnc restore --backup outputs/company-cnc/backups/company-實際編號
```

備份時短暫停止該公司的應用程式與 Qdrant，包含 PostgreSQL 邏輯備份、文件與 BM25 索引、Qdrant volume 封存及 SHA256 清單。
還原前檢查部署識別、容器掛載與完整性，拒絕其他公司的備份。還原會覆寫該公司的目前資料；原資料保存於
`backups/before-restore-*`，包含 SQL dump、Qdrant archive 與被替換的 runtime 目錄。
備份不包含 `.env`、Docker 映像或模型，須另外妥善保存原憑證，尤其索引簽章金鑰。
這是同機、同部署、相容服務版本的還原流程，不是跨主機災難復原或加密異地備份。

### 舊部署工具

沿用 `python scripts/data_maintenance.py backup-runtime` 與
`python scripts/data_maintenance.py restore-runtime --backup backups/YYYY-MM-DD_HHMMSS`。
各公司備份位置與憑證獨立；PostgreSQL 另使用 `scripts/postgresql_backup.py`，並指定實際容器名稱。

設定與後端測試用隔離目錄，勿對正式資料目錄執行測試。正式部署與查詢品質驗收仍需準備文件與模型。

## 雙公司模擬流程驗證

在已安裝專案 Python 套件的環境執行：

```powershell
python scripts/verify_company_workflows.py --output outputs/company-demo-run-01
```

輸出路徑必須不存在。指令分別以獨立程序及 JSON 資料目錄載入 CNC 與空壓機設定，建立標示
`MOCK DATA` 的 PDF 與測試角色，走完「文件匯入與查詢 → 通報 → 派工 → 維修完成 →
操作員確認 → 管理員核准知識 → 知識可再次檢索」。另檢查重複派工、錯誤設備／產線、
越權審核、重新開案政策、索引重載，以及執行 B 情境後 A 的資料檔案是否維持原樣。

產出 `report.json`、兩組詳細報告與程序紀錄。報告比較程式指紋以確認兩組使用同一份核心。
執行秒數只代表自動化流程時間，不能當成企業導入工時。保留的資料僅供核對證據，
測試帳號使用隨機密碼，並不是可直接登入的正式部署環境。

這個模式使用真正的文字型 PDF 解析、BM25 索引與既有後端業務函式；登入狀態以測試角色物件替代，
向量儲存與模型載入以測試替身停用。它不呼叫 Ollama、學校 API、PostgreSQL 或 Qdrant。
因此不代表瀏覽器登入、Gemma 4 回答品質、向量檢索或 Docker／PostgreSQL 隔離驗收已完成。

### 真實瀏覽器與雙部署驗收

`scripts/verify_company_deployment.py --deployment 部署目錄 --pdf 模擬PDF路徑 --output 新證據目錄`
會在標記為 fresh 的 demo 部署建立模擬帳號、套用設定，使用本機無頭 Edge 真正登入四種角色並留下截圖。
需安裝 Playwright Python 套件、Microsoft Edge，且模型與文件準備完成；執行會新增工單與核准知識。

`scripts/verify_deployment_isolation.py --first 第一家部署目錄 --second 第二家部署目錄 --output 新證據目錄`
會在兩家公司各執行重啟、備份、測試異動及還原，同時檢查另一家的 HTTP 健康狀態、資料表內容、文件與向量雜湊。
此工具只接受 fresh demo 部署；須先完成角色驗收以建立模擬帳號。驗收證據及備份皆留在各自目錄。
