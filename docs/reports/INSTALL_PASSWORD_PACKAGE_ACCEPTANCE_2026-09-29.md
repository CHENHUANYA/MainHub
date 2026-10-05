# 密碼修正版安裝包驗證

狀態：最終包安裝驗證進行中，尚未宣告交付通過。

本版整合已確認的管理員審核流程、自行更改密碼、臨時密碼強制設定、登入字體及中文提示。
使用者在 8281 測試站回覆密碼流程成功；以下另從交付 ZIP 解壓，建立全新 MOCK 公司驗證安裝。
正式公司手冊與另一位使用者獨立測試仍保留下一階段。

## 固定版本

| 項目 | 值 |
| --- | --- |
| ZIP | `mainthub-company-template-20260929-password.zip` |
| SHA256 | `48f458e91981d7582c3a6679d66478a10a0667240ce98f8e57a7fe26b26e12c1` |
| 共用來源檔案 | 232 份，另含根目錄 README 與 manifest |
| 映像 | `mainthub:password-final-20260929` |
| 映像 ID | `sha256:fcf6bf5c3b134ba7d45140c69d9a4c7e33a360f09f2b2e6ff7992d101a55e0f7` |
| project／埠 | `mainthub-password-final-20260929`／8294 |
| 部署目錄 | `outputs/release-password-final-20260929/company` |

[安裝包](../../deliverables/mainthub-company-template-20260929-password.zip) ·
[SHA256](../../deliverables/mainthub-company-template-20260929-password.sha256) ·
[更新說明](../guides/RELEASE_NOTES_2026-09-28_ZH_TW.md)。

## 安裝範圍與環境

ZIP 來源與封裝時工作目錄逐檔相符，映像直接從解壓的 source 建置；初始化與主要驗證執行包內工具。
五個執行資料目錄在啟動前均為空，專屬 Qdrant volume 原先不存在；建立全新的 PostgreSQL、帳號、文件索引與向量。
套件不含公司帳密、PDF、資料庫、執行資料、模型或历史報告。
沿用主機的 Python、Docker Desktop、Ollama、Docker 建置快取及唯讀模型快取，並非空白作業系統的首次安裝。
使用 `gemma4:e2b`、`mixedbread-ai/mxbai-embed-large-v1` 與 `cross-encoder/ms-marco-MiniLM-L-6-v2`。

主機既有 Docker 測試網路用盡預設位址池；核對現有 Docker 網段與 Windows 路由後，
僅在本次生成的 compose 設定指定 `10.203.94.0/24`，未更動 ZIP、公司共用程式、其他網路或原測試站。
這是本機環境調整，不代表未處理該主機限制時可以直接啟動。
見 [新安裝證據](../../outputs/release-password-final-20260929/fresh-install.json)、
[封裝紀錄](../../outputs/release-password-final-20260929/package.json)、
[網路調整](../../outputs/release-password-final-20260929/network-adjustment.json)。

## 候選失敗與修正

候選第一次啟動因 Docker 位址池已滿而失敗；指定獨立網段後，啟動、首次登入與批次匯入通過。
候選審核驗證走到退回補充時，工具的選擇條件同時找到工單卡片與查看按鈕；已改為限定工單卡片。
也修正正式驗收指南仍指向舊 ZIP 的連結，修正均納入上述最終包；候選結果不替代最終包驗證。
候選檔案及 FAIL 報告留在 `outputs/release-password-20260929/`，該部署已停止並保留資料。

## 驗證結果

待最終包流程完成後補入，執行中紀錄見 [run.json](../../outputs/release-password-final-20260929/run.json)。
