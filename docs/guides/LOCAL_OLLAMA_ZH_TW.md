# 地端 Ollama 與 Gemma 4

MaintHub 已移除學校 API 的連線程式、金鑰設定、供應者切換與專用測試指令。
回答只交給 Ollama，預設模型統一為 `gemma4:e2b`。
本機服務失敗會回報不可用；串流中斷仍會保留既有來源引用與錯誤說明，不會切換外部供應者。

## 模型準備

先在可下載模型的環境準備 Ollama 與模型；若部署主機斷網，事先移入模型檔案。

```powershell
ollama pull gemma4:e2b
ollama list
ollama run gemma4:e2b
```

使用的模型標籤是 [`gemma4:e2b`](https://ollama.com/library/gemma4:e2b)。
首次下載模型與安裝套件需要網路，之後本機文字推論不需要學校 API、API 金鑰或外部 LLM。

## 執行設定

`.env`、`.env.example` 與 Compose 的模型預設已同步。
直接在主機執行 Python 時，設定：

```powershell
$env:OLLAMA_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "gemma4:e2b"
python -m uvicorn main:app --host 127.0.0.1 --port 8100
```

Docker 容器連到同一台主機的 Ollama，`.env` 使用：

```dotenv
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=gemma4:e2b
```

需要讓 Docker 容器能連線到主機的 Ollama 服務。修改設定後重建應用程式：

```powershell
docker compose up -d --build --force-recreate alarm_rag
```

`host.docker.internal` 表示容器所在主機。部署時不要將 `OLLAMA_URL` 指向外部服務。
舊的 `LLM_PROVIDER` 或學校 API 環境變數不再啟用任何供應者切換。
既有歷史回答的來源紀錄不會被改寫；新生成回答記錄為 `ollama` 與實際本機模型名稱。

## RAG 仍需要本機檢索模型

Gemma 4 負責回答文字，既有 embedding 與 reranker 模型仍負責檢索和排序。
保留或事先準備 `hf_cache/`，並維持：

```dotenv
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
RAG_HF_LOCAL_ONLY=true
```

用 `python scripts/model_cache.py check` 確認快取。模型、文件、索引、資料庫與向量儲存都需在
部署主機或受控內網備妥。安裝 Gemma 4 不會自動建立文件索引。

## 驗證

先從主機執行唯讀檢查（不會下載或載入模型，也不會發送聊天內容）：

```powershell
python scripts/preflight_check.py --ollama-url http://127.0.0.1:11434 --require-ollama-model --require-model-cache
```

`--ollama-url` 只覆寫這次檢查的地址，不會修改應用程式設定。從 Docker 容器執行時，
省略此參數即可檢查 `.env` 的 `OLLAMA_URL`。主機檢查通過仍需確認容器能連到 Ollama。
檢查會分別列出 Ollama 服務是否可達、設定模型是否已安裝，以及 RAG 模型快取是否齊全。
省略 `--require-ollama-model` 時，服務或模型未備妥列為警告；正式驗收會視為失敗。
模型已安裝不代表推論已通過，仍需完成下列實際查詢測試。

應用程式對 Ollama 明確傳入 `think: false`，將受限輸出額度用於最終回答。
2026-09-23 實測發現，未指定此值時 `gemma4:e2b` 在 128 token 測試可回傳空白內容；
關閉思考後，同一 adapter 能取得非空回答。參考 [Ollama 思考模式說明](https://docs.ollama.com/capabilities/thinking)。

預設不檢查 n8n。只有 `COMPOSE_PROFILES` 包含 `automation` 或加上 `--with-automation`，
才會檢查 n8n 金鑰、連接埠與工作流程。新的模板尚未產生資料或備份目錄時列為提醒，
不要求保留前一家公司的資料。若使用自訂 `DB_PATH`，索引簽章檢查也會使用該目錄。
`standalone_acceptance.py` 和 `local_validation_bundle.py` 同樣接受 `--ollama-url` 與
`--with-automation`；未啟用 n8n 時，預設備份驗收不要求 `n8n_data`。

1. `ollama list` 應列出 `gemma4:e2b`。
2. 用 `ollama run gemma4:e2b` 確認能取得回答。
3. 管理員查看 `/health/details`，確認 `llm_provider` 為 `ollama`、`ollama_model` 為 `gemma4:e2b`。
4. 匯入文件後，在查詢與聊天頁確認回答能回溯來源；模型切換後需另行評估回答品質。

地端推論的程式改造不等同防火牆或完整斷網部署驗收；本版本沒有新增外部模型備援。
Ollama 檢查與聊天連線不使用系統的 HTTP 代理環境變數，直接連到設定的 Ollama 地址。

## 可重跑的真實查詢檢查

先完成管理員首次改密碼、公司設定及 PDF 匯入。使用已匯入的原始 PDF，提供預期頁碼及問題：

```powershell
$env:ACCEPTANCE_ADMIN_PASSWORD = "<管理員目前密碼>"
python scripts/verify_local_rag.py --base-url http://127.0.0.1:8123 --collection compressor_demo --question "According to the MOCK training document, what should be recorded and who should be notified?" --source-file outputs/company-workflows-final/compressor/MOCK-compressor.pdf --page 1 --output outputs/local-rag-new-check.json
Remove-Item Env:ACCEPTANCE_ADMIN_PASSWORD
```

範例檔由 `scripts/verify_company_workflows.py` 產生；請依實際檔案位置調整。每次輸出使用新檔名。
可重複提供 `--required-answer-term` 檢查必要文字。工具透過真實登入、查詢 API 與回答快照，檢查
Ollama 模型與回答狀態、第一筆檢索來源的檔名／頁碼／SHA256，以及 embedding／reranker 執行狀態。
備援回答、空白回答、引用不符或模型未載入都會使檢查失敗；報告不保存密碼與登入 token。
此工具不建立帳號、不匯入文件；查詢會產生正常的回答與稽核紀錄。

這項檢查提供單次查詢證據，不能取代雙公司流程、還原隔離與領域回答品質驗收。
