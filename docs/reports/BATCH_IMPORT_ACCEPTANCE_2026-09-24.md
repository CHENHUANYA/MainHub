# 人員與工單批次導入驗收

本次完成 PostgreSQL 標準部署的人員 Excel 範本、逐列預覽、確認建立，以及人員／工單批次履歷。
登入頁新增首次改密碼表單，管理員與批次人員不需要另外呼叫 API 完成登入。
操作方式已同步至 [導入 SOP 第 6 步](../guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md#6-建立人員匯入文件與工單)，
正常導入仍只填設定及資料，不修改程式。

## 功能與資料保護

- 人員每批最多 200 筆、1 MB；檢查角色、產線、密碼與重複帳號，不覆寫既有帳號。
- 預覽或取消不寫入帳號與批次；確認前重查設定及帳號，版本改變須重新預覽。
- 成功履歷與人員／工單在同一交易提交。履歷寫入失敗時資料一併回滾，測試已覆蓋兩類匯入。
- 遷移 `20260924_0012` 新增 `import_batches`，保留原有資料，不清除舊 PostgreSQL 部署。
- 履歷只保存檔名、SHA256、執行人員、計數、原始列號、結果及紀錄 ID，不存原始試算表、密碼或密碼雜湊。
- 預覽、取消及未進入確認的格式錯誤沒有履歷；確認失敗另嘗試記錄，資料庫不可用時可能無法記錄。
- 舊匯入不追溯補建，JSON 舊模式未加入人員批次與持久化履歷。

## 真實執行

隔離部署 `mainthub-batch-acceptance`、連接埠 `8151`，使用真實 PostgreSQL、Cookie 登入與無頭 Edge。
模擬人員及工單沒有混入原本公司的部署。

`outputs/batch-import-20260924/browser-verified/report.json` 的 8 項檢查通過：
公司設定畫面套用、範本下載、預覽取消不寫入、只建立有效列、重複帳號拒絕、
新維修人員首次改密碼及履歷權限、工單帳號檢查與跨批去重、重新載入後的逐列履歷。
瀏覽器沒有 JavaScript 例外。

`outputs/batch-import-20260924/restore-report.json` 的 3 項檢查通過：
備份後新增帳號與批次，重啟保留新增紀錄；還原後履歷精確回到備份時點的兩批，
備份後新增的帳號與批次同時消失。還原工具另保留還原前資料，完整資料庫及執行目錄雜湊比對一致。

## 新版基礎包重跑

交付檔：`exports/mainthub-company-template-20260924-batch.zip`，包含 215 份共用檔案。

```text
ZIP SHA256
c40f238e5442367bdf3ddefb2f2fe881ab82564a333fbe0d09170c281fd0ec14

template-manifest.json SHA256
3ae2d5c52c085bc92a21cd5eb878a954cb3f16bd0af36192a80222f9a2fe736e
```

從 ZIP 解壓至 `outputs/batch-import-20260924/receiver`，以包內 Dockerfile 建立新映像，
執行包內初始化工具產生 `package-company`，project 為 `mainthub-batch-package`、連接埠 `8152`。
新部署的資料庫由啟動程序自動建立至 `20260924_0012`，沒有手動補 SQL 或修改包內程式。

包內 `scripts/verify_batch_import.py` 實際執行 **9 項檢查通過**，包含首次管理員改密碼與上述 8 項批次流程。
結果為 `outputs/batch-import-20260924/package-browser/report.json`，截圖同目錄。
完成後解壓目錄與實際部署目錄各 215 份共用檔案均通過完整性檢查，沒有變動或缺漏。
本版未重新宣稱已完成全套双公司模型品質驗收；先前雙公司證據屬 9 月 23 日版本。

## 回歸

973 項 Python 測試、52 項子測試、29 項 JavaScript 測試通過；Ruff 與 mypy 通過。
同時修正快速連續設定寫入可能重用時間戳的問題，以固定時鐘測試確認舊預覽一定失效。

這是開發環境的自動化工程驗收。兩位不同人從乾淨支援環境拿同一基礎包、只照 SOP 操作，
以及 CNC／空壓機領域回答品質與失敗案例，仍是後續驗收項目。
