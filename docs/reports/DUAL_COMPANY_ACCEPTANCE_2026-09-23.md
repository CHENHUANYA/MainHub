# 雙公司 PostgreSQL／地端模型部署驗收

日期：2026-09-23。資料均為 MOCK，並非正式企業資料或設備操作指引。

## 環境與結果

| 項目 | CNC | 空壓機 |
| --- | --- | --- |
| Compose project | `mainthub-cnc-acceptance` | `mainthub-air-acceptance` |
| 本機入口 | `http://127.0.0.1:8131` | `http://127.0.0.1:8132` |
| 獨立目錄 | `outputs/dual-company-20260923/cnc` | `outputs/dual-company-20260923/compressor` |
| PostgreSQL 資料庫及使用者 | `mainthub_cnc_acceptance` | `mainthub_air_acceptance` |
| 知識庫 | `cnc_manual` | `compressor_demo` |
| Qdrant volume | `mainthub-cnc-acceptance_qdrant` | `mainthub-air-acceptance_qdrant` |
| 角色瀏覽器流程 | 通過 | 通過 |
| 重啟與完整還原 | 通過 | 通過 |
| 操作另一家公司時的健康檢查 | 101 次，全數成功 | 112 次，全數成功 |

兩者均使用 PostgreSQL、Qdrant、主機 Ollama `gemma4:e2b`，模型快取以唯讀掛載共用。
實際檢索模型為 `mixedbread-ai/mxbai-embed-large-v1` 與 `cross-encoder/ms-marco-MiniLM-L-6-v2`。
應用映像為 `mainthub:local-acceptance`，驗收時映像 ID：
`sha256:6d9991dabc09121b425c720971d3dfb85b508d5ce64ad5153da4593411ddf276`。
兩家使用相同核心；公司差異由設定、文件、帳號及獨立儲存決定。

## 真實角色流程

`scripts/verify_company_deployment.py` 使用本機無頭 Microsoft Edge 與真正登入 Cookie，沒有替換 API、模型或向量服務。
內建瀏覽器工具回報不可用，改以 Python Playwright 控制已安裝的 Edge。

每家公司包含 4 種角色登入，以及以下 6 個業務檢查：

1. 操作員查詢，確認真實 Ollama、完整回答快照、正確 PDF／頁碼／SHA256、embedding 與 reranker。
2. 通報異常並產生連結工單。
3. 主管指派該公司的維修帳號。
4. 維修人員接續處理並填寫原因、動作、結果，完成維修。
5. 操作員確認修復，知識保持待審核。
6. 管理員核准後，知識入庫並通過真正檢索驗證。

PDF 為既有的 `MOCK-cnc.pdf` 與 `MOCK-compressor.pdf`。初次 CNC 流程證據為
`outputs/dual-company-20260923/evidence/cnc-03/report.json`，空壓機為 `air-02/report.json`。
最終重跑與六階段截圖分別存於同目錄下的 `cnc-final-02/`、`air-final-02/`。
兩組最終報告均為 PASS；`07-admin-approved-refreshed.png` 另記錄重新登入、篩選該工單後的已入庫畫面。
首次流程後已有核准工單進入知識庫，因此最終引用檢查要求正確 PDF 被列入引用，並記錄其排序，
不要求 PDF 永遠排第一；回答仍須包含儀表讀數與通知維修的中英文關鍵內容。
單文件驗收工具預設仍維持第一筆引用必須正確的嚴格規則。

## 登入、重啟與還原隔離

`outputs/dual-company-20260923/evidence/isolation-02/report.json` 的 12 項檢查通過：

- 資料庫名稱、使用者、密碼、金鑰、Cookie、掛載、網路與連接埠分離；後端服務不公開主機連接埠。
- 同一個 Edge context 同時登入兩家公司，重整仍登入；登出一家公司不影響另一家。
- A 的帳密與 Token 不能登入 B，反方向也相同。
- 每家公司各自重啟全部三個服務，資料表內容、文件與向量內容保持一致。
- 停止單家應用程式及 Qdrant 後備份 PostgreSQL、文件／BM25 與 Qdrant volume。
- 備份後新增 MOCK 資料庫設定與檔案，再實際還原；確認異動消失，資料表與檔案回到備份狀態。
- 還原後逐筆向量／payload 雜湊相同，並再次取得 Ollama 完整回答及 PDF 第一頁引用。
- 全程監測另一家，每秒一次 HTTP 健康探測；前後比較全部 14 張資料表、文件與向量雜湊均一致。

備份各自保存於：

- CNC：`cnc/backups/company-1ab8f562a20f/`
- 空壓機：`compressor/backups/company-72116473a789/`

路徑以 `outputs/dual-company-20260923/` 為起點。還原前狀態另存 `backups/before-restore-*`。
上述備份是還原演練時的快照，早於最後一次瀏覽器重跑新增的工單。
備份包含實際驗收帳號與紀錄，不放進分享部署包。原 `.env` 及簽章金鑰須另行保存。
此驗收涵蓋同機同部署的完整還原，尚未涵蓋異地還原、容錯切換或高併發容量。

## 本次發現及修正

1. 前端仍傳 `updated_by`、`accepted_by`、`completed_by`、`verified_by`，被後端的伺服器歸屬規則拒絕。
   改由後端記錄登入身分；維運編輯補上版本欄位，畫面人員欄位改為唯讀。新增 5 項 JavaScript 回歸。
2. Cookie 不按連接埠隔離，固定名稱導致同一瀏覽器登入 B 後 A 變成 401。
   新增可驗證的 `SESSION_COOKIE_NAME`，每家由初始化工具配置不同名稱，實際同時登入驗證通過。
3. Windows bind mount 的 Qdrant 在重啟後發生 `OutputTooSmall`，向量 scroll 回傳 500。
   改用專屬命名磁碟區，從既有文件重建索引；其後雙向重啟及完整還原均通過。
   [官方文件](https://qdrant.tech/documentation/common-errors/)說明 Windows 共享掛載不完全相容 POSIX，建議命名磁碟區。
4. 瀏覽器驗收曾在管理頁初始化前點擊導覽，改為等資料渲染後再操作，保留原失敗截圖。
5. 已核准工單可能排在原始 PDF 之前；`cnc-04/`、`cnc-05/` 保留此案例。
   正確 PDF 仍在引用中，但泛化問法可能回覆工單內容；來源排序與回答品質仍須專門評估。
6. 重跑相同 MOCK 代碼與維修內容時，知識去重正確拒絕第二次核准；`cnc-final/` 保存拒絕證據。
   之後的驗收每次使用不同 MOCK 情境代碼；另修正驗收關鍵詞只接受英文、誤判正確中文回答的問題。

## PostgreSQL 舊資料

未刪除既有 PostgreSQL volumes，也未清空舊帳號或工單。初始化工具要求新目錄與新 project，
同名既存 Qdrant volume 也會拒絕，避免默默沿用舊公司資料。此次僅更動新的 MOCK 驗收部署。

## 後續範圍

完整回歸為 959 項 Python 測試、52 項子測試、26 項 JavaScript 測試通過；Ruff、mypy 與差異格式檢查通過。
更新後分享包為 `exports/mainthub-company-template-20260923-dual-deployment.zip`，包含 207 份來源檔及導入 README，
不包含實際資料、測試證據、備份或密碼。

人員批次建立預覽、完整匯入履歷頁面，以及兩領域的資料不足／失敗回答評估仍待完成。
本報告證明工程流程與部署隔離，不代表任意設備文件或正式維修建議均已達品質標準。
