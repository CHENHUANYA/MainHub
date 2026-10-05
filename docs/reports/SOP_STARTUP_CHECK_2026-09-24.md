# SOP 啟動檢查補強（2026-09-24）

本輪補齊新導入人員從工具安裝到首次登入之間的檢查。原有 PostgreSQL、Qdrant 與部署資料均保留。

## 已完成

- Python 安裝後才執行檔案完整性檢查；修正查詢題目數量描述。
- 新增 `scripts/check_company_deployment.py`：核對掛載隔離及應用程式連接埠，等待 `/ready` 的 PostgreSQL 與向量服務均成功，檢查容器內快取與 Ollama 模型。
- `--probe-model` 會由應用程式容器發出簡短推論，須收到完成且非空的回答；只有列出模型不算推論通過。
- `--report` 保存 UTF-8 JSON，不覆寫既有報告，也不輸出帳密、連線字串或模型回答內容。
- 初始化攔截一般程式占用或作業系統保留的連接埠，發生衝突時不建立部署目錄。
- 驗收表新增雙人安排，明列同一 ZIP、獨立目錄／project／port、證據及未通過處理。
- 修正封裝根目錄 README 的查詢展示說明連結。

## 驗證

- 公司及交付工具相關測試 85 項、42 項子測試通過；新增測試涵蓋非 Docker 占用、依賴失敗、誤連另一家公司、模型未回答與錯誤訊息去敏。
- 最後調整初始化錯誤說明、報告存檔與模型回傳文字型別檢查後，相關 22 項測試通過；Ruff 通過。
- 現有 CNC `mainthub-quality-cnc-final`（8181）與空壓機 `mainthub-quality-air-final`（8182）均六項啟動檢查通過，包含容器實際模型回答。
- 最終封裝工具的 JSON 證據：`outputs/rag-quality-20260924/startup-r2-cnc-final.json` 與 `startup-r2-air-final.json`。

本輪為部署工具與文件檢查，未宣稱重新完成全套角色、還原或十題品質驗收。上一輪完整回歸仍為 994 項 Python、52 項子測試及 29 項 JavaScript。

## 限制及交付

快取存在檢查不等於檢索模型成功載入，也不代表引用或語意正確。正式文件須按 SOP 第 6、7 步驗收。
診斷不建立帳號或資料；推論會使用 Ollama 記憶體與運算資源。輸出報告本身為唯一指定的新檔。

最終基礎包使用 `mainthub-company-template-20260924-startup-r2.zip`，既有封裝保留。
SHA256：`db865da37734150efbe25d9da5b3b536f745b358007a5bf8eb71cca846f89b2c`。
兩份副本各驗證 221 份共用檔案，檢查工具從包內執行；封裝證據為
`outputs/rag-quality-20260924/startup-r2-release-proof.json`。
兩位真人從乾淨環境拿同一份 ZIP 獨立完成 SOP，以及正式公司文件簽收，仍待實際安排與執行。
