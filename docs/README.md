# MaintHub 文件導覽

日常操作從 [專案 README](../README.md) 開始；詳細內容依需求查閱下列文件。

| 需求 | 文件 |
| --- | --- |
| 自行改密碼、首次設定與管理員臨時密碼的人工操作 | [密碼測試指南](guides/PASSWORD_ACCEPTANCE_ZH_TW.md) |
| 9/29 測試站新增密碼功能與工程驗證（尚未納入原 ZIP） | [密碼流程修正](reports/PASSWORD_WORKFLOWS_2026-09-29.md) |
| 現有功能的待完善項目、優先順序與完成標準 | [現有功能待完善清單](plans/CURRENT_REFINEMENT_CHECKLIST_ZH_TW.md) |
| 目前交付 ZIP、SHA256、全新安裝、登入與審核流程結果 | [9/29 安裝包驗證](reports/INSTALL_PACKAGE_ACCEPTANCE_2026-09-29.md) |
| 本版整合的審核流程、介面及驗證工具修正 | [包內更新說明](guides/RELEASE_NOTES_2026-09-28_ZH_TW.md) |
| 歷史 9/26 精修包、SHA256、映像及雙公司重跑結果 | [同包工程驗收](reports/REFINEMENT_BUNDLE_ACCEPTANCE_2026-09-26.md) |
| 漏摘錄、具體補件、CNC 串流換行與三十份回答核對 | [回答表達精修](reports/ANSWER_FORMAT_REFINEMENT_2026-09-26.md) |
| 拿同一份基礎包、照步驟導入公司，不修改程式 | [公司導入 SOP](guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md) |
| 同一個 ZIP 解壓兩份、共用檔案不變的重跑證據 | [SOP 封裝重跑](reports/SOP_PACKAGE_REPLAY_2026-09-23.md) |
| setup 包啟動、環境設定隔離及本輪未通過項目 | [2026-09-25 setup 續驗](reports/SETUP_PACKAGE_CONTINUATION_2026-09-25.md) |
| 歷史 citation 包：無關段落回答修正、代碼防護與資源關閉紀錄 | [2026-09-25 回答品質修正](reports/RAG_GROUNDING_FIX_2026-09-25.md) |
| 歷史 stop 包：指定公司停止、保留資料與封裝紀錄 | [2026-09-25 公司停止操作](reports/COMPANY_STOP_2026-09-25.md) |
| 公司設定、文件解析與雙公司模擬驗證 | [共用模板導入說明](guides/COMPANY_TEMPLATE_ZH_TW.md) |
| Ollama、`gemma4:e2b` 與離線模型快取 | [地端模型設定](guides/LOCAL_OLLAMA_ZH_TW.md) |
| 真實地端推論、引用、重建及工單匯入驗證 | [2026-09-23 驗收紀錄](reports/LOCAL_RAG_ACCEPTANCE_2026-09-23.md) |
| 四種角色實際登入、雙 PostgreSQL 部署與還原隔離 | [雙公司部署驗收](reports/DUAL_COMPANY_ACCEPTANCE_2026-09-23.md) |
| 人員批次預覽、首次改密碼、匯入履歷與還原 | [批次導入驗收](reports/BATCH_IMPORT_ACCEPTANCE_2026-09-24.md) |
| CNC／空壓機問題卡、正確來源與失敗案例展示 | [查詢品質展示 SOP](guides/RAG_DEMO_ACCEPTANCE_ZH_TW.md) |
| 十題真實模型結果、原始失敗與修正證據 | [MOCK 查詢品質紀錄](reports/RAG_DEMO_QUALITY_2026-09-24.md) |
| 不同導入人員填寫操作與查詢結果 | [導入驗收紀錄表](../templates/COMPANY_ACCEPTANCE_RECORD_ZH_TW.md) |
| 正式文件、設備適用證據、五題審閱與雙人簽收準備 | [正式公司驗收準備](guides/FORMAL_ACCEPTANCE_PREPARATION_ZH_TW.md) |
| 環境設定、部署、備份與還原 | [部署說明](guides/DEPLOYMENT.md) |
| 目前完成項目、剩餘工作與驗收條件 | [共用模板實作計畫](plans/REUSABLE_COMPANY_TEMPLATE_PLAN_ZH_TW.md) |
| 架構與程式流程 | [專案程式導讀](guides/GRADUATION_PROJECT_WALKTHROUGH_ZH_TW.md) |

## 驗證與維運工具

- [雙公司模擬後端流程](../scripts/verify_company_workflows.py)：產出隔離測試資料與結果報告。
- [部署前檢查](../scripts/preflight_check.py)：檢查設定、Ollama 與模型快取。
- [真實地端查詢檢查](../scripts/verify_local_rag.py)：登入查詢、驗證模型回答快照與指定文件頁碼。
- [本機資料備份工具](../scripts/data_maintenance.py)：備份、驗證與還原相關操作。
- [PostgreSQL 備份工具](../scripts/postgresql_backup.py)：需指定實際容器與資料庫參數。
- [模板封裝工具](../scripts/export_company_template.py)：排除公司正式資料與帳密。
- [獨立部署初始化](../scripts/init_company_deployment.py)：新資料目錄、帳密、Cookie 與專屬 Qdrant volume。
- [公司服務操作](../scripts/company_service.py)：使用公司自己的設定啟動、查看含已停止容器的狀態、重啟及停止；保留資料，不接受 shell 殘留的其他公司密碼或 Compose project。
- [公司啟動檢查](../scripts/check_company_deployment.py)：核對掛載與連接埠、等待資料庫及向量服務、從容器實際呼叫模型；可保存不含帳密的 JSON 報告。
- [完整公司備份及還原](../scripts/company_runtime_backup.py)：PostgreSQL、文件、索引及向量儲存的一致性備份。

工具參數以各指令的 `--help` 為準。測試產物保存在指定的 `outputs/` 或 `tests_tmp/` 目錄，
不代表正式部署或模型品質已通過驗收。

## 文件維護

操作文件放在 `docs/guides/`，進度與設計放在 `docs/plans/`。
更新功能時同步修正說明與計畫；入口連結應指向目前專案中實際存在的檔案。
