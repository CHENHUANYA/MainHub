# 9/29 新版安裝包與乾淨安裝驗證

範圍：整合使用者已確認的審核流程與介面修正，從新版 ZIP 建置並驗證全新 MOCK 公司部署。
正式公司手冊與另一位使用者獨立測試保留下一階段，沒有代填真人簽收。

**結果：本版打包與乾淨部署的安裝驗證通過。**

## 固定交付版本

| 項目 | 值 |
| --- | --- |
| ZIP | `mainthub-company-template-20260929-review.zip` |
| SHA256 | `16b087af3aae4c2a89352e89e2762dc4898c51fedebc8afa1fdc3c215dd9f5d2` |
| 共用檔案 | 229 份；包內含更新說明、SOP、正式驗收指南與空白表 |
| manifest SHA256 | 以包內 `template-manifest.json` 與來源完整性紀錄為準 |
| 映像 | `mainthub:review-bundle-20260929` |
| 映像 ID | `sha256:ecb041e07aa5e65cb41bda80420333329ecb1849a56d617f88478b2721b106f1` |
| 全新 project／埠 | `mainthub-review-clean-20260929`／8292 |
| 部署目錄 | `outputs/release-review-20260929/company` |

[下載安裝包](../../deliverables/mainthub-company-template-20260929-review.zip) ·
[SHA256 檔](../../deliverables/mainthub-company-template-20260929-review.sha256) ·
[包內更新說明](../guides/RELEASE_NOTES_2026-09-28_ZH_TW.md)。

ZIP 來源與工作目錄逐檔比對一致；映像從 ZIP 解壓的 `source` 建置，初始化及主要驗證均執行包內工具。
套件不含公司帳密、PDF、資料庫、執行資料、模型快取或歷史報告。
[封裝邊界](../../outputs/release-review-20260929/package.json)、
[執行階段與結果](../../outputs/release-review-20260929/run.json)、
[建置紀錄](../../outputs/release-review-20260929/build.log)。

## 乾淨安裝的範圍

啟動前五個執行資料目錄均為空，Qdrant 專屬 volume 不存在；初始化生成新帳密、資料庫與公司設定。
沒有從既有測試站複製帳號、資料庫、文件索引或向量。
[新安裝證據](../../outputs/release-review-20260929/fresh-install.json)。

主機沿用 Windows PowerShell、Python 3.12.10、Docker Engine 29.2.1、Compose 5.0.2、Ollama 0.34.4，
使用既有 Docker 建置快取與唯讀 Hugging Face 模型快取；不是空白作業系統或首次下載模型的驗證。
模型為 `gemma4:e2b`、`mixedbread-ai/mxbai-embed-large-v1`、`cross-encoder/ms-marco-MiniLM-L-6-v2`。
瀏覽器使用真實背景 Edge；內建 Browser 連線不可用後，改用專案既有 Playwright 工具。

## 本版實測

| 項目 | 結果／證據 |
| --- | --- |
| 啟動、隔離掛載、資料庫／向量服務、快取、Ollama 與實際回覆 | [6/6 通過](../../outputs/release-review-20260929/startup.json) |
| 首次登入改密碼、設定套用、人員／工單預覽取消與匯入、去重、履歷及權限 | [9/9 通過](../../outputs/release-review-20260929/batch/report.json) |
| 四角色登入、查詢、通報、派工、維修、驗證、退回補充、重新送審與核准入庫 | [13/13 通過](../../outputs/release-review-20260929/workflow-approve/report.json) |
| 第二筆完整角色流程與管理員不採用 | [10/10 通過](../../outputs/release-review-20260929/workflow-reject/report.json) |
| 核准／不採用工單唯讀檢視、Escape 焦點返回、四角色 940／390px 無水平溢位與登出 | [13/13 通過](../../outputs/release-review-20260929/ui.json) |
| 容器封裝內容核對 | [221/221 相符](../../outputs/release-review-20260929/container-integrity.json)；8 份 `docs/` 文件依 `.dockerignore` 不進映像 |
| 來源及公司目錄完整性 | 各 229/229 相符；[來源](../../outputs/release-review-20260929/source-integrity.log)、[部署](../../outputs/release-review-20260929/deployment-integrity.log) |
| 停止、原容器再啟動與重新登入 | [通過](../../outputs/release-review-20260929/restart.json)；所有資料表、文件／索引及向量內容雜湊相同，兩笔工單完整查詢結果不變 |

核准工單 `716fc828`：管理員退回後，維修人員在預設看板找到待補充紀錄，新增備註並重新送審；
原 `verified` 狀態與驗證者保留。管理員看到根本原因、實際動作、結果及完整備註，核准後狀態為 `ingested`，真實檢索驗證成功。
第二筆工單以頁內表單不採用，狀態為 `rejected`、仍為已驗證且沒有入庫時間。
兩次流程無頁面 JavaScript 錯誤；補充版面驗證也沒有改動工單。

兩次真實模型回答皆包含原文「Record the gauge reading.」「Report to maintenance.」，
繁中說明保留讀數與通知維護的動作，引用 MOCK PDF 第 1 頁、來源 SHA256 相符，並顯示 MOCK 聲明。
第二次檢索也找到前一筆已核准工單；PDF 原文來源仍存在。
此核對只涵蓋兩次相同 MOCK 問題，沒有重跑舊版完整題庫或正式手冊品質驗收。

相關 Python 回歸 182 項通過，另有 12 個 subtest 通過；JavaScript 回歸 25 項通過。
最終封裝前重跑封裝測試 3 項及修改工具的 Ruff 檢查通過。Python 測試有一項既有 Starlette／httpx 棄用警告，未影響測試結果。

## 失敗紀錄與修正

9/28 候選包啟動及首次改密碼通過，但舊驗證工具過早點選管理員導覽，後續又使用已更名的下載連結。
已補載入完成等待、展開式匯入區與目前按鈕名稱，將修正納入 9/29 新包；未以候選包的通過結果替代最終包。
候選失敗紀錄保留：[初次](../../outputs/release-review-20260928/batch/report.json)、
[按鈕名稱](../../outputs/release-review-20260928/batch-retry1/report.json)。

最終包附加的唯讀版面腳本，第一次誤在預設「待處理項目」尋找已審核工單；
改用畫面「全部」篩選後通過，產品與 ZIP 均未修改。
[該次紀錄](../../outputs/release-review-20260929/ui-attempt1.json) 保留為 FAIL。

重啟附加檢查第一次把審核 POST 回應與後續 GET 回應整份比較，因 `updated_at`、時區格式與新增審核歷程不同而失敗；
當次資料庫、檔案及向量前後雜湊已相同。改用重啟前後同一 GET 端點的完整回應比較後通過，沒有排除工單欄位或修改產品。
[第一次紀錄](../../outputs/release-review-20260929/restart-attempt1.json)、
[端點回應差異](../../outputs/release-review-20260929/restart-response-diff.json) 與最終重跑分開保留。

## 收尾

9/28 候選部署及 9/29 最終驗證部署的三個容器均已停止，資料、容器與 volume 保留。
既有 `http://127.0.0.1:8281` 測試站仍正常；本輪沒有更新該站映像或操作該站資料。
Docker Desktop 與 Ollama 為原測試站共用服務，保留運行。

再次啟動本輪驗證公司可在專案根目錄執行：

```powershell
python outputs/release-review-20260929/source/scripts/company_service.py --deployment outputs/release-review-20260929/company start
python outputs/release-review-20260929/source/scripts/check_company_deployment.py --deployment outputs/release-review-20260929/company
```

登入網址為 `http://127.0.0.1:8292/login`，測試憑證只保存在該部署的私有檔案，未放進交付 ZIP 或公開報告。

## 後續

下一階段換核准的正式公司手冊，確認設備適用關係、逐题答案與引用，再請另一位使用者獨立操作並記錄卡住的步驟。
正式簽收沿用包內空白表，實際文件、人員、結果與簽名保持待填。
9/26 雙公司備份還原及完整題庫仍屬歷史版本證據；本版沒有宣告重做雙公司或正式資料驗收。
