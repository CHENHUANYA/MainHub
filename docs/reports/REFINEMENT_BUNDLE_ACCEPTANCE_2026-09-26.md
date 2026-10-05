# 同一精修包雙公司工程驗收

日期：2026-09-26。範圍：Windows PowerShell、Docker Desktop Linux containers、MOCK 公司。
本報告對應固定包的工程重跑；正式公司文件與兩位人員的獨立導入尚未簽收。
**結果：工程驗收通過。**使用者本輪指定先完成工程驗收；正式資料與真人簽收保持待辦。

## 固定版本

| 項目 | 值 |
| --- | --- |
| 來源包 | `mainthub-company-template-20260926-refinement.zip` |
| ZIP SHA256 | `074f9a113f7eab65e33f8d95287044ad0124cb043b50647bb482ae8b756aa84c` |
| 共用檔案 | 226 份；兩份解壓副本完整性檢查通過 |
| 檔案清單 SHA256 | `437e9a9fdba0b83f6c2cca5ba12de7a82e6d65e51a3e2671c4da9e6e54c1f351` |
| 映像標籤 | `mainthub:refinement-bundle-20260926` |
| 映像 ID | `sha256:29c0af2de3bb2a064c14270d28fa8cd3e968d26ecbe0067fd1cc95a53d23f1d8` |

[下載固定來源包](../../deliverables/mainthub-company-template-20260926-refinement.zip)。
映像實際從包內 `source-a` 建置；各公司由自己的解壓副本初始化，沒有修改共用程式。
生成模型為 `gemma4:e2b`；本機已有的唯讀檢索快取使用 `mixedbread-ai/mxbai-embed-large-v1` 與
`cross-encoder/ms-marco-MiniLM-L-6-v2`。不代表在空白主機重新下載過模型。

## 環境失敗與恢復

第一輪停在 CNC 啟動。Docker 回報 `all predefined address pools have been fully subnetted`：
主機累積的測試 Compose 網路占滿預設子網，尚未啟動應用程式。
[第一輪報告](../../outputs/bundle-refinement-20260926/report.json) 與
[已遮蔽機密的錯誤紀錄](../../outputs/bundle-refinement-20260926/startup-failure.txt) 保留為失敗。

確認沒有運行容器後，只對本輪已驗完且停止的 `mainthub-format3-compressor`、
`mainthub-format3-grounding`、`mainthub-format3-cnc`、`mainthub-format-boundary` 執行 Compose down，
未使用 `--volumes`。四組專屬網路與停止容器移除，PostgreSQL bind 目錄、文件、索引及四個 Qdrant volume 保留。
[恢復紀錄](../../outputs/bundle-refinement-20260926/network-pool-recovery.json) 記錄移除前容器 ID／狀態及 volume 保留檢查。
未清理其他歷史公司或變更 Docker 位址池設定。

釋出網路後使用**原 ZIP、原 SHA256、原映像 ID**與全新部署目錄重跑。
這項原因已明確；它與上一輪文件上傳連線中斷、較早的 Docker API 500 及 Ubuntu 整合問題分開記錄。

## 證據入口

最新重跑：[雙公司完整報告](../../outputs/bundle-refinement-20260926-retry1/report.json)。
最終結果以該報告及下列完成紀錄為準，不能用第一輪失敗或歷史 setup／citation／stop 包的通過結果替代。

## 單公司完成紀錄

| 範圍 | CNC 公司 | 空壓機公司 |
| --- | --- | --- |
| project／連接埠 | `mainthub-refinement-r1-cnc`／8281 | `mainthub-refinement-r1-compressor`／8282 |
| 啟動檢查 | 5/5 | 5/5 |
| 瀏覽器批次匯入 | 9/9 | 9/9 |
| 瀏覽器角色流程 | 10/10 | 10/10 |
| 題庫 JSON／SSE | 5/5、5/5 | 5/5、5/5 |
| 停止、查看 exited、原容器啟動 | 通過 | 通過 |
| 停止前後資料／檔案／向量雜湊 | 相同 | 相同 |
| 公司目錄共用檔案 | 226/226 不變 | 226/226 不變 |
| 容器內封裝檔案（含前端） | 220/220 相符 | 220/220 相符 |

啟動檢查核對隔離掛載、資料庫／向量服務、模型快取及 Ollama 模型可用性；實際推論在後續題庫及角色流程執行。
容器核對排除 `.dockerignore` 明列的六份操作文件；映像本身沒有包含這些文件。
角色流程以真實無頭 Edge 完成四種角色登入、來源查詢、通報、派工、維修、確認及知識核准入庫，沒有瀏覽器 JavaScript 錯誤。
批次檢查包括首次改密碼、預覽／取消、錯誤列拒絕、確認、跨批次去重、履歷及一般帳號無權讀管理員履歷。

停止演練每家均保留五個帳號、三份文件及三筆版本、兩張工單、兩筆批次履歷、十二份回答快照與四個向量點。
比較範圍是完整資料表內容、文件／索引檔案及向量內容雜湊，不只是筆數。

本包二十份題庫回答已由 Codex 對照原文逐句核對，另見
[本包回答審閱](../../outputs/bundle-refinement-20260926-retry1/semantic-review.json)。
沒有借用前一工程映像的三十份回答代替本包重跑；前一輪額外的 grounding／跨設備題組仍分開保留於
[回答精修報告](ANSWER_FORMAT_REFINEMENT_2026-09-26.md)。

## 雙公司還原與隔離

[隔離報告](../../outputs/bundle-refinement-20260926-retry1/isolation/report.json) **十二項通過**：
獨立資料庫、憑證、Cookie、掛載及私有服務連接埠；同瀏覽器同時登入／獨立登出；跨公司帳號及權杖拒絕；
兩個方向的重啟、完整備份、受控變更後還原，以及還原後真實模型查詢。

| 還原目標 | 另一家公司健康探測 | 另一家資料／檔案／向量 |
| --- | --- | --- |
| CNC | 空壓機 162 次，失敗 0 | 雜湊不變 |
| 空壓機 | CNC 149 次，失敗 0 | 雜湊不變 |

合計 311 次探測均為 HTTP 200。目標公司的備份後測試設定／檔案已移除，備份內資料恢復通過內容核對。
兩次還原後回答皆摘錄 `Record the gauge reading.`、`Report to maintenance.`，
繁中說明保留讀數及維護對象，引用各自 `MOCK-workflow-*.pdf` 第 1 頁並保留 MOCK 聲明與相同快照。
Codex 對照原文核對通過，非真人簽收。

## 收尾及限制

最終報告確認沒有運行容器、Ollama 載入模型清單為空，Docker Desktop 已停止。
兩家新版驗收公司的容器、資料目錄、備份與 volume 保留，可依同一服務腳本下次啟動。
本輪資料與資源檢查不代表整台主機卡頓已解決。
只有雙公司隔離階段同時開兩組服務；其餘測試各自啟停。
收尾取樣另見 [resource-final.json](../../outputs/bundle-refinement-20260926-retry1/resource-final.json)。

本次操作路徑固定 Windows PowerShell；Ubuntu WSL Docker 整合沒有補驗／修復。
明確解決的是本輪測試網路占滿子網池；先前上傳連線中斷及歷史 Docker API 500 根因仍未確定。
ZIP 不包含正式帳密、執行資料、文件或模型快取；檔案邊界核對見
[package-boundary.json](../../outputs/bundle-refinement-20260926-retry1/package-boundary.json)。

## 尚待正式驗收

兩份已預填相同 ZIP、SHA256、映像的簽收表均標記待驗收，必要操作沒有代填通過：
[CNC 待驗收表](../../deliverables/acceptance-20260926/cnc-pending.md)、
[空壓機待驗收表](../../deliverables/acceptance-20260926/compressor-pending.md)。
正式公司核准文件、設備適用關係、審閱人員、兩位獨立導入人員及乾淨環境仍待提供。
