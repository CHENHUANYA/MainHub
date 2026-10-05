# 2026-09-23 地端模型與工單匯入驗收

本次完成 `gemma4:e2b` 真實推論、單一隔離容器的 RAG 查詢與重建後查詢，以及工單匯入帳號檢查和跨批次去重。
尚未完成雙公司瀏覽器角色流程、備份還原隔離與完整領域回答品質評估。

## 環境與資料

| 項目 | 實測值 |
| --- | --- |
| Compose project | `mainthub-local-rag` |
| 應用程式 | `http://127.0.0.1:8123`，本次原始碼建置映像 `mainthub:local-acceptance` |
| 業務資料 | 本次隔離目錄的 JSON；另建 PostgreSQL 17.10 驗證遷移與匯入交易 |
| 文字模型 | 主機 Ollama `gemma4:e2b`，模型 digest `7fbdbf8f5e45a75bb122155ed546e765b4d9c53a1285f62fd9f506baa1c5a47e` |
| Embedding | `mixedbread-ai/mxbai-embed-large-v1` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| 模型快取 | 既有 `hf_cache/` 唯讀掛載，`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`RAG_HF_LOCAL_ONLY=true` |
| 向量庫 | 隔離 Qdrant，`compressor_demo` 中 3 筆向量 |
| 公司 | `templates/company.compressor-demo.json`，空壓機模擬工廠 |
| 文件 | `MOCK-compressor.pdf`，3 頁，來自既有雙公司模擬流程產物 |
| 文件 SHA256 | `a1d048791034418a9981650ec043aee71b95b68569c9b1ad4bc954e0320a6a56` |

驗收資料放在 `outputs/local-rag-20260923/`。原有 `AIDC` 容器由 Docker Desktop 自動啟動，未修改其設定或資料。
本次環境沒有執行舊專案的資料遷移；PostgreSQL 檢查使用新建的隔離資料庫。
驗收目錄中的 `.env`、`compose.json` 含本機驗收憑證，均屬 git 忽略的執行產物，不納入模板包。

## 模型與查詢證據

開始時 `ollama list` 已列出 7.2 GB 模型，因此不需重新下載。初次 adapter 實測在 128 token 額度下收到空白內容。
在 Ollama 請求明確指定 `think: false` 後，adapter 於 1.55 秒取得非空繁體中文回答。
此設定依 [Ollama 思考模式文件](https://docs.ollama.com/capabilities/thinking)，將輸出額度留給最終回答。

已透過真實 HTTP API 完成管理員首次改密碼及登入，套用公司設定、匯入 PDF，並提出問題：

> According to the MOCK training document, what should be recorded and who should be notified?

第一筆回答指出應記錄儀表讀數並報告給維護人員，正文引用 `MOCK-compressor.pdf, Page 1`。
回答快照確認 `provider=ollama`、`model=gemma4:e2b`、`answer_state=complete`。
第一筆檢索來源的文件 SHA256、頁碼、section ID 與 locator 均吻合；embedding 載入成功，reranker 實際執行且無錯誤。

新增 `scripts/verify_local_rag.py` 以真實登入和回答快照驗證以上條件。再次查詢 4.02 秒通過，
重新建置並重建容器後 5.39 秒通過。時間為單次本機測量，包含登入及查詢，不能視為效能基準。

| 本機證據檔 | 內容 |
| --- | --- |
| `adapter.json` | adapter 實際回答及耗時 |
| `ingest.json`、`query.json`、`answer-record.json` | 文件匯入、第一筆回答與持久化回答快照 |
| `health.json` | 實際檢索模型執行狀態及來源追蹤覆蓋率 |
| `live-check.json` | 可重跑檢查的完整問題、回答、來源與判定 |
| `after-restart.json` | 容器重建後，同文件查詢通過 |
| `manifest.json` | git 基準、修改中原始碼 SHA256、實際映像 ID、模型版本與測試統計 |

使用的是已有快取的上述模型，不代表 Compose 預設的其他 embedding／reranker 已下載或驗證。
本次問題為英文、回答為繁體中文，且文件明確標示 MOCK DATA；不代表實際設備 SOP 或中文問題集品質已通過。
未做物理斷網測試，也未做 CNC 真實模型問答、完整串流瀏覽器驗收或多使用者負載測試。

## 工單匯入

- 指派欄位只接受存在且啟用中的維修帳號 ID；預覽後帳號停用、刪除或改角色會使確認失敗。
- 同批次及跨批次去重：提供 `source_record_id` 時採來源＋ID，否則採正規化匯入內容。
- 保存不可變 `import_key`、原始檔案 SHA256、列號、來源 ID 與匯入人員；後續編輯／軟刪除不清除識別碼。
- JSON 維持整批原子寫入；PostgreSQL 增加唯一約束，確認時鎖定引用帳號直到交易完成。
- 真實 HTTP 驗證有效維修帳號可匯入、未知帳號在預覽報錯；改檔名及內容後，相同來源 ID 仍被擋下。證據：`http-import.json`。
- PostgreSQL 17.10 從 `20260921_0010` 升級至 `20260923_0011`，保留預先建立的工單；驗證去重、唯一約束及回滾。證據：`postgresql.json`。
- 真實 PostgreSQL 帳號鎖定與預覽後停用檢查通過。證據：`postgresql-accounts.json`。

舊版匯入、已移出工單儲存區的封存資料及永久清除資料不自動回填去重識別碼。
沒有來源 ID 時，內容相同的不同事件需要補 ID；內容變更會被視為新事件。
人員批次建立、完整批次履歷頁面及封存資料去重仍未完成。既有 PostgreSQL 部署需先執行 `alembic upgrade head` 才能使用新程式。

## 回歸

950 項 Python 測試、52 項子測試、21 項 JavaScript 測試全部通過；Ruff 與 mypy（72 個來源檔）通過。
Python 回歸包含兩個匯入入口的既有 Edge 測試，但這些瀏覽器測試使用隔離 API 與角色替身，
不能代替下一階段四種角色的正式登入操作驗收。保留一則既有 Starlette／httpx 棄用提醒。

下一階段從雙公司實際瀏覽器角色流程開始，再驗證雙部署的重啟、備份與還原互不影響。
