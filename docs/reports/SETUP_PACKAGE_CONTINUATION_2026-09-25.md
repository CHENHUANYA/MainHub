# setup 封裝續驗（2026-09-25）

依共用模板計畫續驗原 setup 包。兩家公司啟動、環境設定隔離、批次導入及雙向還原通過；
第一次還原演練遭 Docker 引擎故障中斷，恢復後第二次十二項通過，保留兩次結果。
本輪整體尚未完成：公司 B 回答品質失敗，其完整角色流程與正式交付仍待完成。
未修改基礎包或公司核心程式，未凍結正式交付版，也未宣稱真人 SOP 簽收完成。

## 固定輸入與範圍

- ZIP：`exports/mainthub-company-template-20260924-setup.zip`
- SHA256：`d99c607fca580cff6aadeb687c3ac115152600939f4024822437024aa1568837`
- manifest SHA256：`01e40d59c34f8bab92a83921310892173a67faf06fe17a81619edcc72c36a69d`
- 映像：`mainthub:setup-20260924`，ID `sha256:24472363726619dc95853f015cc700607429c3eb38dcf1cfbcd3f8c53969f6f9`
- 公司 A：保留 `outputs/sop-setup-20260924/company-a`，project `mainthub-sop-setup-a`，埠 8191。
- 公司 B：由 receiver-b 的包內工具新建 `outputs/sop-setup-20260924/company-b`，project `mainthub-sop-setup-b`，埠 8192。

本機原有 Python、Docker、Ollama 及模型快取繼續使用；不是乾淨作業系統安裝測試。
使用 `gemma4:e2b`、`mixedbread-ai/mxbai-embed-large-v1` 與 `cross-encoder/ms-marco-MiniLM-L-6-v2`。
PDF 使用 `outputs/company-workflows-final/` 的 CNC／空壓機 MOCK 資料，不是正式企業文件。

## 已取得的證據

| 項目 | 結果 |
| --- | --- |
| 封裝與兩份接收副本 | ZIP 雜湊一致，共用檔案各 223 份通過 |
| 執行中容器來源 | 兩家公司各 192 份核心檔案與封裝相同 |
| 啟動檢查 | 兩家公司各六項通過，包含容器實際模型非空回答 |
| 瀏覽器批次導入 | 兩家公司各九項通過，含初始密碼變更、公司設定套用、人員預覽／取消／確認、工單去重及履歷 |
| 公司 A 四角色流程 | 十項通過，含真實模型回答、來源頁碼與雜湊、通報派工、維修確認及知識審核 |
| 公司 B 四角色流程 | 回答品質檢查連續兩次失敗；其後流程未執行，不列為通過 |
| 其他公司環境變數 | 雙向載入另一家完整 `.env`，另帶入錯誤 Compose 選項；start／status／restart 均使用目標公司的 project、帳密、Cookie、loopback 埠及掛載 |
| 重啟資料比對 | 上述雙向服務操作前後，目標與另一家的資料庫、文件及向量內容皆相同 |
| 瀏覽器與權限隔離 | 同瀏覽器登入、獨立登出、跨公司帳號及權杖拒絕通過 |
| 備份還原 | 首次因 Docker API 失效中斷；恢復後重跑十二項通過，雙向還原後資料與向量一致、查詢成功 |
| 另一家公司可用性 | 成功重跑期間共 287 次健康探測均成功（150／137），兩個方向的另一家公司資料均不變 |
| 還原後批次履歷 | 兩家公司的人員／工單批次共四筆仍可登入查閱，逐列結果存在 |
| 導入後檔案完整性 | 兩個接收目錄及兩個部署目錄，各 223 份共用檔案皆無變更或缺少 |
| 部署工具及文件相關測試 | 32 項部署測試與 4 項文件測試通過，文件連結及差異格式檢查通過；未宣稱全套回歸重跑 |

包內批次驗收與角色驗收各有私有憑證檔，本輪工程程序讓角色工具沿用已在畫面變更的 MOCK 管理員密碼。
該協調只寫驗收私有資料，沒有修改核心或封裝；亦不能視為真人獨立照 SOP 操作證據。

## 公司 B 回答品質失敗

原問題：

> In the source PDF MOCK-compressor.pdf, what does the training observation say about the gauge reading and reporting to maintenance?

原文件第 1 頁包含「Record the gauge reading.」「Report to maintenance.」。
兩次檢索都把正確第 1 頁排在第一名，embedding 已載入、reranker 有執行，來源 SHA256 與頁碼正確。
模型卻回答第 3 頁的「訓練出席」，未回答儀表讀值與通報維修。

| 嘗試 | 回答 ID | 結果 |
| --- | --- | --- |
| 首次 | `chatcmpl_c566a461d3424441b87488a085d740bd` | `MOCK DATA 訓練出席 (Mock Data Training attendance) (MOCK-compressor.pdf, Page 3)` |
| 相同輸入重測 | `chatcmpl_9e954174006b481781895528a16eb5ff` | `MOCK DATA 訓練出席 (Page 3 \| MOCK-compressor.pdf)` |

此例證明引用 metadata 含正確文件不等於回答內容正確。失敗可重現，不能只重跑取成功樣本，
也不能以先前不同題庫的十題成功取代修正。下一輪須先診斷生成時如何使用相關與無關段落，
將此題與負向題保留為回歸，再重新驗證公司 B 完整角色流程。

## Docker 中斷、恢復與重跑

啟動時 Docker Linux 引擎不可連線，使用 `docker desktop start` 後恢復。
後續雙向還原驗收在公司 A 的第一份 Qdrant 唯讀備份期間，Docker API 回傳 500，
`docker run` 備份程序沒有結束；保留不完整備份，停止該卡住的 CLI 後執行 `docker desktop restart --timeout 120`。
備份工具復原服務的 `compose up` 也因引擎不可用而失敗，原始演練報告為 FAIL。

不完整備份位於 `company-a/backups/company-979940c0188b`，未產生 `manifest.json`，不可用於還原。
第一次未進入演練用資料異動，也未呼叫還原；原有資料目錄與 volumes 均保留。
第一次期間另一家公司共 85 次健康探測，其中 35 次失敗，該次結果保持 FAIL。
引擎重啟後已用包內 `company_service.py` 恢復 A／B，兩家公司再次通過五項啟動檢查
（`recovery-a-20260925.json`、`recovery-b-20260925.json`；這次不含生成探測）。

使用原包內工具與新的證據目錄重跑，仍帶入錯誤的 Compose project、帳密及其他公司環境變數。
第二次十二項通過：雙向備份、重啟、加入 MOCK 異動、完整還原、移除異動及還原後實際模型查詢均完成。
資料庫與檔案還原檢查涵蓋匯入履歷，另以管理員重新登入 API 核對兩家公司各兩筆履歷及逐列結果。
成功重跑的另一家公司健康檢查共 287 次，失敗 0 次；不能用這個結果抹除首次引擎中斷。
Docker API 500 的底層原因未確定，恢復成功不等於根因已修復。

## 證據與後續交付

以下相對路徑以 `outputs/sop-setup-20260924/` 為起點：

- `release-input-20260925.json`：包與映像識別。
- `startup-a-20260925.json`、`startup-b-20260925.json`：啟動檢查。
- `container-integrity-20260925.json`：實際容器來源比對。
- `environment-isolation-20260925.json`：另一家公司環境設定下的雙向服務操作與資料比對；不輸出帳密。
- `evidence-20260925/batch-a/`、`batch-b/`：批次瀏覽器報告與截圖。
- `evidence-20260925/workflow-a/`、`workflow-b/`、`workflow-b-repeat/`：所有角色流程嘗試，包含兩次失敗原文。
- `evidence-20260925/isolation/report.json`：Docker 中斷的原始演練結果。
- `evidence-20260925/isolation-repeat/report.json`：恢復後完整雙向演練 PASS，十二項檢查與 287 次健康探測。
- `report-20260925.json`：所有成功與失敗嘗試、還原後履歷及四個目錄完整性；整體維持 `INCOMPLETE`。
- `handoff-20260925/person-a-acceptance.md`、`person-b-acceptance.md`：兩份待填真人紀錄。

兩位導入人員、乾淨主機與正式核准文件仍待指定。下一步修正公司 B 的生成品質問題，
補完其完整角色流程，再決定交付版本及安排獨立 SOP 驗收；持續保留 Docker 中斷紀錄供追查。
