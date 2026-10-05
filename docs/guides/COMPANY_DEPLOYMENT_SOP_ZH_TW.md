# 相同基礎檔案的公司導入 SOP

本 SOP 的交付目標：不同導入人員取得**同一版本、同一份基礎部署包**，只填公司設定與導入資料，
依序完成部署、登入、文件查詢、維修流程及備份還原。正常導入不需要修改程式碼。

目前狀態：操作步驟已整理；既有雙公司工程驗收已通過，但「由不同人從乾淨環境只照本 SOP 完成」
仍待正式驗收。不可將既有開發者操作紀錄視為這項交付驗收已完成。

## 1. 先確認交付內容及支援範圍

每位導入人員取得相同的部署 ZIP，以及相同版本的本 SOP。公司名稱、設備、帳號與文件另行準備，
不由開發者為每家公司修改一份程式。發行方應記錄 ZIP 檔名及 SHA256，供接收者核對版本。

先以 `Get-FileHash "收到的部署包.zip" -Algorithm SHA256` 比對發行方提供的雜湊。
解壓後先依第 2 步安裝 Python，再於基礎目錄執行檔案完整性檢查，應顯示 `PASS`。
此檢查使用包內 `template-manifest.json`，用於偵測檔案變動；不是數位簽章驗證。

本版標準路徑為 Windows PowerShell、Docker Desktop 的 Linux containers、主機 Ollama，
以及每家公司獨立 PostgreSQL／Qdrant 部署。以下步驟在 ZIP 解壓後的基礎目錄執行。

| 導入時可以調整 | 不應要求導入人員修改 |
| --- | --- |
| 公司設定 JSON：公司、廠區、產線、設備、知識庫及既有流程選項 | Python、JavaScript、HTML、CSS、SQL 或資料庫遷移程式 |
| 初始化指令參數：部署目錄、project、連接埠、模型快取位置 | Dockerfile、Compose 服務結構或路由 |
| 系統畫面：帳號、角色、產線權限、文件及歷史工單 | 文件解析器、提示詞實作或模型呼叫程式 |
| SOP 明列的環境設定與模型選擇 | 為某家公司加入例外判斷 |

目前支援 SINUMERIK 警報手冊及可擷取文字的 PDF／SOP。掃描 PDF 的 OCR、新設備介接或全新流程屬功能擴充，
應回到產品開發處理，不算一般導入步驟；不能要求導入人員自行改程式解決。

## 2. 準備工具與模型

先安裝 Python 3.11 或 3.12、Docker Desktop、Ollama，並啟動 Docker 與 Ollama。
首次安裝及模型下載需要網路；完全離線主機須由發行方另行提供已備妥的映像、套件與模型，
目前來源 ZIP 本身不包含這些大型檔案。

```powershell
python --version
python scripts/verify_template_bundle.py
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-postgresql.txt
docker info
ollama pull gemma4:e2b
ollama list
ollama run gemma4:e2b "請用繁體中文回答：你是否可以正常回覆？"

$env:RAG_EMBEDDING_MODEL = "mixedbread-ai/mxbai-embed-large-v1"
$env:RAG_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
.\.venv\Scripts\python.exe scripts/model_cache.py --online preload
.\.venv\Scripts\python.exe scripts/model_cache.py check
docker build -t mainthub:local-acceptance .
```

完成標準：Docker 可用、`gemma4:e2b` 列在模型清單且實際回覆、兩個檢索模型均顯示 `OK`、映像建置成功。
上例沿用目前工程驗收實際使用的檢索模型，不表示任意語言或文件品質已通過評估。
任何指令失敗先停止本步，保存錯誤；不能以跳過模型檢查當作安裝成功。

若 Docker Desktop 顯示「WSL integration with distro Ubuntu unexpectedly stopped」，
先在 PowerShell 執行 `docker info`。Ubuntu 發行版整合與 Docker Linux 引擎分開檢查：
若 Linux 引擎可用且本 SOP 的服務檢查通過，可繼續 PowerShell 部署。
需要在 Ubuntu 內使用 Docker 時，於提示框選擇「Restart the WSL integration」，
並依 [Docker 官方 WSL 說明](https://docs.docker.com/desktop/features/wsl/)
確認 Settings → Resources → WSL Integration 已啟用 Ubuntu；再於 Ubuntu 執行 `docker info` 驗證。
若 PowerShell 的 Docker API 也失效，保存當次失敗紀錄後重新啟動 Docker Desktop，
以 `company_service.py start` 恢復既有部署並重跑啟動檢查；不要重新初始化同一公司目錄。

## 3. 填寫公司設定與部署參數

先複製一份 `templates/company.cnc-demo.json` 或 `templates/company.compressor-demo.json` 為 `my-company.json`。
只改副本中的公司資料；這是設定檔，不是程式。欄位與解析器選擇見 [設定說明](COMPANY_TEMPLATE_ZH_TW.md)。

按順序填公司、知識庫、廠區、產線、設備；每台設備引用已宣告的產線與知識庫 ID。
ID 使用英數字、底線或連字號；中文名稱放在 `display_name`。
預設知識庫須在清單中，設備的 `collection`、產線的 `site_id` 等參照也須一致。
帳密不填入公司 JSON。

以下參數由導入人員填寫。範例值僅供示範，同主機第二家公司必須使用不同部署目錄、project 及連接埠：

```powershell
$CompanyConfig = (Resolve-Path .\my-company.json).Path
$Deployment = "C:\MaintHubDeployments\company-a"
$Project = "mainthub-company-a"
$AppPort = 8131
$ModelCache = (Resolve-Path .\hf_cache).Path
```

完成標準：新部署目錄尚不存在，project 尚未使用，連接埠未占用。不要選舊公司資料目錄。
第二家公司可使用 `company-b`、`mainthub-company-b`、`8132`；不同人的獨立主機可使用相同示範連接埠。

## 4. 初始化並啟動獨立部署

```powershell
.\.venv\Scripts\python.exe scripts/init_company_deployment.py --output "$Deployment" --company-config "$CompanyConfig" --project "$Project" --port $AppPort --hf-cache "$ModelCache" --embedding mixedbread-ai/mxbai-embed-large-v1 --reranker cross-encoder/ms-marco-MiniLM-L-6-v2
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" start
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" status
.\.venv\Scripts\python.exe scripts/check_company_deployment.py --deployment "$Deployment" --probe-model --report "$Deployment/startup-check.json"
```

工具會驗證公司設定，產生獨立資料庫身分、密碼、金鑰、Cookie 名稱與 Qdrant volume，
並在啟動時執行既有資料庫遷移。不要另改 Compose 或手動執行 SQL。
初始化會先檢查封裝共用檔案（有 manifest 時）、Docker Linux containers、應用程式映像、名稱／連接埠衝突及 Compose 設定，
這些檢查失敗時不建立公司目錄，修正後可使用原本的新目錄參數重跑。
若是檔案複製或磁碟寫入失敗，可能留下未完成目錄；保留錯誤與該目錄，改用新的目錄，不覆寫既有資料。
啟動、狀態、重啟與停止一律使用 `company_service.py`，備份還原使用第 8 步工具。
這些工具使用自己的部署 `.env`，不讓 PowerShell 殘留的其他公司設定或 Compose project 覆蓋。
初始化只採用明列參數與共用預設值；不要靠設定 PowerShell 環境變數來修改此公司的 Compose 內容。
完成標準：檢查工具顯示 `"status": "PASS"`，且瀏覽器能開啟 `http://127.0.0.1:8131/login`（依所填連接埠調整）。
工具會核對資料掛載與連接埠、等待 PostgreSQL／Qdrant 就緒（預設最多 180 秒）、檢查檢索模型快取，
並從應用程式容器呼叫 Ollama 取得非空回答。推論另有等待時間，整體可能需要數分鐘。
工具不建立帳號、不匯入文件、不清理資料；輸出不含密碼與金鑰。保存檢查結果作為驗收證據。
`--report` 會將 UTF-8 JSON 存到指定新檔，既有報告不覆寫；重跑時換成 `startup-check-2.json` 等新檔名。
`PASS` 只代表這些啟動項目通過；快取存在不代表檢索模型已成功載入，仍須完成第 6、7 步的實際查詢與引用驗收。
顯示 `FAIL` 時依該項 `next_step` 處理，並重跑同一檢查；不要跳過失敗項目繼續簽收。
初始化因設定錯誤或名稱衝突失敗時，依錯誤修正設定／參數；不要刪除舊公司的資料來騰出名稱。
PowerShell 視窗若關閉，重新開啟後須回到相同基礎目錄，並重新填寫第 3 步的參數；不要重新初始化既有部署。

## 5. 首次登入並套用公司設定

1. 在自己的部署目錄開啟 `.env`，取得 `ADMIN_INITIAL_PASSWORD`；此檔含私密設定，須妥善保管。
2. 使用 `admin01` 登入，依畫面要求更換初始密碼。
3. 前往管理後台的「設定與稽核／公司設定包」，選取新部署中的 `company.json`。
4. 預覽公司、設備與知識庫，確認正確後套用。

完成標準：重新整理後顯示自己的公司名稱及設備清單。初始化只準備設定檔，仍須在畫面預覽及套用，
不能省略此步。空知識庫顯示尚未建立索引屬正常現象。

## 6. 建立人員、匯入文件與工單

1. 在「使用者」逐一建立帳號，或下載人員 Excel 範本，填入主管、維修人員及操作員。先套用第 5 步的公司設定，再填寫產線 ID。
2. 批次上傳後逐列檢查角色、產線及錯誤；按「確認匯入」只建立有效列。按取消不寫入帳號或履歷，既有帳號不覆寫。批次新帳號第一次登入會顯示改密碼表單，設定後再以新密碼登入。
3. 在知識庫選擇正確的公司知識庫，匯入自己的文字型 PDF／SOP，確認文件名稱及索引就緒狀態。
4. 若有歷史工單，先建立工單指派使用的維修帳號，再到「資料匯入」上傳 Excel，逐列檢查預覽，確認有效列後匯入。
5. 在「資料匯入／人員與工單匯入履歷」核對批次、檔名、執行人員、新增與略過數量；展開查看原始列號、錯誤及新增紀錄 ID。可依人員或工單篩選。

人員範本第一列欄位名稱不可更改，檔案為 `.xlsx`，最多 1 MB、200 筆資料，不使用公式：

| 欄位 | 填寫方式 |
| --- | --- |
| `user_id` | 必填；英數字、底線或連字號，不能與既有帳號或同批有效列重複 |
| `name`、`team` | 選填；顯示姓名與團隊 |
| `role` | 必填；`operator`、`maintenance`、`supervisor` 或 `admin` |
| `line_scope` | 必填；公司設定的產線 ID，以半形逗號分隔；全部產線填 `*`，管理員及全部產線權限須特別核對 |
| `password` | 必填；至少 8 字元的初始密碼，避免常見預設密碼；以文字格式填寫，妥善保管含密碼的來源檔 |

修正錯誤後只保留要新增的列，再重新上傳預覽。預覽後若有人修改帳號或公司設定，確認會拒絕寫入，須重新預覽。
人員批次與持久化履歷適用本 SOP 的 PostgreSQL 部署；不追溯建立舊匯入履歷。
履歷不保存試算表原始內容或密碼，只記錄確認結果；預覽、取消、尚未進入確認的格式錯誤不列入。
確認階段的版本衝突或交易失敗會嘗試記錄「未寫入」，資料庫不可用時連履歷也可能無法保存。
若確認時連線中斷，先查詢帳號／工單及履歷，不要直接重做。

完成標準：各角色能登入，看到授權設備；每台設備查詢的文件對照正確。
設備對照只決定查哪個知識庫；通用手冊沒有設備識別碼時，明問該設備可能保守拒答。
請核對 [設備對照與拒答邊界](RAG_DEMO_ACCEPTANCE_ZH_TW.md#設備對照與拒答邊界)，
確認文件的設備適用性，不以改對照或改檔名代替對應文件。
歷史工單先預覽後寫入，維修知識仍須審核。人員建立、首次改密碼與匯入履歷查閱均可在畫面完成。

## 7. 按角色執行功能驗收

正式文件到位前，先依 [正式公司驗收準備](FORMAL_ACCEPTANCE_PREPARATION_ZH_TW.md) 登錄核准文件版本、
SHA256、設備適用證據與審閱人員，再填五題問題及逐句審閱紀錄。

為每家自己的文件準備至少兩題有答案、兩題資料不足與一題設備不符的問題；使用
[查詢品質與展示操作](RAG_DEMO_ACCEPTANCE_ZH_TW.md) 核對引用及每項事實，將結果填入
[導入驗收紀錄表](../../templates/COMPANY_ACCEPTANCE_RECORD_ZH_TW.md)。示範題庫不可代替自己的正式文件驗收。

| 操作者 | 操作 | 完成標準／保留證據 |
| --- | --- | --- |
| 操作員 | 選設備、提問 | 回答非空，來源檔名、頁碼與原文相符；保存問題及截圖 |
| 操作員 | 問文件沒有提供的資訊 | 明確指出資料不足，不杜撰設備處置；失敗記錄待改善 |
| 操作員 | 建立通報並通知維修 | 產生可追蹤的通報與工單 ID |
| 主管 | 指派維修人員 | 指派正確且有權限的帳號 |
| 維修人員 | 開始維修、填原因／動作／結果並完成 | 工單完成且人員紀錄正確 |
| 操作員或主管 | 確認維修 | 工單確認；維修知識仍為待審核 |
| 管理員 | 審核候選知識 | 核准後才入庫；可追蹤來源工單並再次檢索 |

完成標準：所有必要操作通過；文件品質失敗不能因服務正常啟動而忽略。
自動化的 `verify_company_deployment.py` 是工程用 MOCK 驗收工具，不是正式公司必跑步驟，
正式導入不應讓它建立模擬帳號或混入模擬文件。

## 8. 備份、重啟及還原

從原本的基礎目錄使用同一組 `$Deployment` 參數：

```powershell
.\.venv\Scripts\python.exe scripts/company_runtime_backup.py --deployment "$Deployment" backup
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" restart
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" status
.\.venv\Scripts\python.exe scripts/check_company_deployment.py --deployment "$Deployment"
```

記錄工具輸出的備份完整路徑，重新登入確認文件、帳號、工單與匯入履歷仍在。備份會短暫停止該公司的應用程式與 Qdrant。
還原演練在尚未正式投入使用的驗收部署進行：

```powershell
$Backup = "填入上一步產生的備份完整路徑"
.\.venv\Scripts\python.exe scripts/company_runtime_backup.py --deployment "$Deployment" restore --backup "$Backup"
.\.venv\Scripts\python.exe scripts/check_company_deployment.py --deployment "$Deployment" --probe-model
```

還原會覆寫目前資料，回到備份時點；工具另保留還原前狀態。備份不包含 `.env`、映像與模型，須另外保管，
本流程是同機同部署還原。完成標準：能重新登入、讀取原工單並正確查詢原文件。
同機有第二家公司時，確認另一家仍可登入且資料不變；不要對正式生產中的資料任意做驗收異動。

### 用完後停止與釋放記憶體

示範或驗收結束、這家公司暫時不用時，執行：

```powershell
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" stop
.\.venv\Scripts\python.exe scripts/company_service.py --deployment "$Deployment" status
```

`stop` 只停止指定公司 project 的容器，保留容器、公司檔案、PostgreSQL 資料與 Qdrant volume。
`status` 也列出停止的容器，確認該公司的服務顯示 `Exited`；命令失敗不能視為已關閉，修正後重跑。
其他公司的容器與主機共用的 Ollama／Docker Desktop 仍可運作。

主機上所有使用者與公司都已結束模型查詢時，再釋放 Ollama 載入的模型：

```powershell
ollama ps
ollama stop gemma4:e2b
ollama ps
```

若使用其他模型標籤，換成 `ollama ps` 顯示且本次用到的名稱。停止後確認該模型已從清單消失；
模型檔仍保留，下次查詢會重新載入。這是主機共用資源，不由單一公司的 `stop` 自動處理。
如要進一步釋放 Docker 的記憶體，先在 Docker Desktop 確認沒有其他工作需要運行，
再從系統匣選單結束 Docker Desktop。

下次使用時，開啟 Docker Desktop 與 Ollama，再對原本的 `$Deployment` 執行第 4 步的
`start`、`status` 及啟動檢查；使用原帳號與資料，不需重新初始化公司。

## 9. 交付簽收與失敗處理

交付紀錄至少包含：基礎 ZIP 檔名與 SHA256、導入人員、日期、主機環境、公司設定、模型版本、
驗收問題與來源頁碼、角色流程結果、備份位置及還原結果。不要將密碼或正式文件放進公開紀錄。
開始前先填妥 [雙人導入安排](../../templates/COMPANY_ACCEPTANCE_RECORD_ZH_TW.md#雙人導入安排)，
兩人各留一份自己的操作紀錄；完成後比對版本與所有必要項目，再共同簽收。

完成導入後再執行：

```powershell
python scripts/verify_template_bundle.py
python scripts/verify_template_bundle.py --root "$Deployment"
```

兩次均須顯示 `PASS`，確認基礎目錄與實際部署的共用檔案沒有被修改。
自己的 `my-company.json`、工具產生的 `.env`／`company.json`／`compose.company.json` 及執行資料不在共用檔案清單內。

| 遇到的問題 | SOP 內的處理方式 |
| --- | --- |
| 設定欄位或設備對照錯誤 | 修正自己的 JSON，重新驗證／預覽 |
| project、目錄或連接埠被使用 | 使用另一組新的部署參數，保留舊資料 |
| Docker 非 Linux containers、映像不存在或 Compose 驗證失敗 | 回到第 2 步啟動 Docker、切換 Linux containers 或完成映像建置，再重跑初始化；不改共用 Compose |
| 模型缺少、服務不可達 | 回到模型準備步驟及 [地端模型說明](LOCAL_OLLAMA_ZH_TW.md)，確認服務、快取與連線設定 |
| 文件無文字、引用不正確或回答錯誤 | 記錄文件與問題；更換支援的文字文件或回報產品問題，不自行改解析程式 |
| 工單指派帳號不存在或停用 | 在使用者管理建立／修正權限，重新做匯入預覽 |
| 需要修改程式或補未寫在 SOP 的指令才能繼續 | 標記導入未通過；由維護者修正共用版本及 SOP，重新發布同一份基礎包 |

**最終簽收標準：兩位導入人員使用同一份基礎包，分別完成兩家公司的全部必要步驟；
中間不修改任何程式、不需要開發者臨場修補。**
