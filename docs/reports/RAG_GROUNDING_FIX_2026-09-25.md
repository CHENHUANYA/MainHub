# 回答品質修正與工程候選包

日期：2026-09-25。範圍：MOCK 文件的回答相關性、識別碼防護、引用檢查及角色流程重驗。
本紀錄不代表正式公司文件品質合格，也不代替兩位獨立人員從乾淨主機照 SOP 導入的簽收。

## 修正內容

前一輪公司 B 的原英文題要求記錄儀表讀值並通報維修，模型卻連續回答第 3 頁的訓練出席內容。
正確第 1 頁已在檢索結果中，問題出在生成階段；原題、原 PDF 與失敗證據均保留。

- 共用一般維護提示詞要求先引用直接相關的原文，再回答，並列出實際檔名及頁碼。
  CNC 警報逐字查詢與診斷專用提示詞維持各自用途。
- 新增 `services/evidence_guard.py`：所問的明確識別碼若未出現在本次檢索原文或警報 metadata，
  直接說明缺少對應資料。檔名不算設備適用性的證據，也不把一般數量當成警報碼。
- 串流及非串流使用相同防護；保存 `provider=evidence_guard`、空白模型欄位及完整回答快照。
  這類結果不計為 Ollama 回答。
- 驗收正向題同時核對回答正文的檔名／頁碼及檢索來源，避免只有 metadata 正確卻仍判定通過。
- 增加三頁 `grounding` 回歸包，涵蓋原英文問題、中文問題、缺少壓力值、未知警報及其他設備。

## 凍結的工程候選版

| 項目 | 結果 |
| --- | --- |
| ZIP | [mainthub-company-template-20260925-citation.zip](../../exports/mainthub-company-template-20260925-citation.zip) |
| SHA256 | `dc510bc1848f2f89997dad077af18857ac7c2b234f0bbb127beeb9c3da3ef83c` |
| 共用檔案 | 225 份；目前工作目錄與封裝內容一致 |
| 映像 | `mainthub:citation-20260925` |
| 映像 ID | `sha256:8f430f75b4698c3a0135afabbaa5e766c78f7a58e18c1891ef9b7aa099c50000` |
| 映像內容 | 193 份核心程式／前端檔案與封裝雜湊一致 |

兩份解壓副本、三個升級部署與兩個新建混合檢索部署，各 225 份共用檔案均通過完整性檢查。
完整檔案結果見 [final-integrity.json](../../outputs/evidence-guard-20260925/final-integrity.json)。
此雜湊檢查用於偵測內容變動，不是簽章認證。帳密與公司 runtime 資料未納入共用包。
已準備新版 [兩份待填導入紀錄](../../outputs/evidence-guard-20260925/handoff/status.json)，目前均未簽收。

## 驗證結果

相關 Python 回歸 **252 項通過**，涵蓋 `tests/rag`、公司文件設定、模板匯出、API 契約及部署文件。
修改的 Python 檔案 Ruff 通過；識別碼防護、提示詞與查詢路由的 mypy 三個檔案通過。
這是本次相關範圍的回歸，不與前輪測試數相加當作全套結果。文件更新後四項部署文件測試與新增連結檢查通過。

| 最終候選版檢查 | 結果與證據 |
| --- | --- |
| CNC 品質五題，乾淨獨立 PostgreSQL／Qdrant | 五題及四項環境控制通過；[hybrid-cnc](../../outputs/evidence-guard-20260925/final-evidence/hybrid-cnc/report.json) |
| 空壓機 SOP 品質五題 | 五題及環境控制通過；[air-quality-quality](../../outputs/evidence-guard-20260925/final-evidence/air-quality-quality/report.json) |
| 原三頁 PDF 品質五題，乾淨獨立 PostgreSQL／Qdrant | 五題及四項環境控制通過；[hybrid-air](../../outputs/evidence-guard-20260925/final-evidence/hybrid-air/report.json) |
| CNC 瀏覽器角色流程 | 十項通過；[workflow-cnc](../../outputs/evidence-guard-20260925/final-evidence/workflow-cnc/report.json) |
| 空壓機瀏覽器角色流程 | 十項通過；[workflow-air](../../outputs/evidence-guard-20260925/final-evidence/workflow-air/report.json) |
| 串流防護、回答快照與來源標記 | 八項通過；[streaming-guard-final.json](../../outputs/evidence-guard-20260925/streaming-guard-final.json) |

上述三組共十五題均通過檢查；品質結果仍標示 `GATES_PASS_REVIEW_REQUIRED`，不是語意品質評分。
每套五題含三次實際 Ollama 呼叫（兩題有答案、一題缺參數）與兩次識別碼防護拒答。
CNC 及原題補驗使用 SOP 已指定且本機有快取的
`mixedbread-ai/mxbai-embed-large-v1`／`cross-encoder/ms-marco-MiniLM-L-6-v2`。
中文問題依既有規則不跑英文 reranker；英文探測單獨驗證 reranker，不混稱所有回答都使用它。

瀏覽器驗證使用既有 MOCK 部署，先統一更新為同一份候選包的共用檔案與映像，再完成登入、查詢、
通報、派工、維修、確認與知識審核。這是工程升級回歸，**不是**兩位導入人員的新主機驗收。
本版未重新執行完整雙向備份還原；前輪十二項還原檢查屬於 setup 包，詳見
[setup 續驗](SETUP_PACKAGE_CONTINUATION_2026-09-25.md)。

## 保留的失敗與補驗

- 原 setup 包的公司 B 答錯頁結果保留於 `outputs/sop-setup-20260924/evidence-20260925/workflow-b*`。
- 第一版提示詞雖改善原題，仍曾對 E-99／其他設備借用不相符內容；因此加入識別碼防護。
  同一階段也發現回答省略頁碼，促成正文引用檢查及明確來源格式。
- 中間版本空壓機 SOP 的 E-43 題漏頁碼，結果保留在
  `outputs/evidence-guard-20260925/evidence/air-quality/report.json`。
- [final-acceptance.json](../../outputs/evidence-guard-20260925/final-acceptance.json) 仍為 FAIL：
  角色流程已加入核准工單文件，品質工具依規則拒絕混合文件庫，未清除資料或改寫失敗結果。
  CNC 品質在該次跳過，空壓機品質在案例執行前停止；之後以新部署分別補驗。
- 首次乾淨補驗的工程腳本誤指定未快取的檢索模型，五題回答各自通過，但 embedding／reranker 控制失敗。
  [final-clean-quality.json](../../outputs/evidence-guard-20260925/final-clean-quality.json) 保留為 FAIL。
  修正工程測試參數後使用另一組新部署，結果另存，不覆蓋原始紀錄。
- 初次串流測試的 PowerShell 管線破壞中文編碼；其失敗紀錄保留。
  後續使用 UTF-8 Python 檔驗證問題原文、完整 SSE 與持久化回答一致。

## 邊界與待驗收事項

識別碼防護只檢查本次檢索片段，不能證明整個知識庫沒有資料，也不能證明片段彼此相關。
目前公司設定中的設備對照不視為文件內容證據：若通用手冊未寫設備識別碼，即使已設定對照，
明問該設備仍可能被保守拒答。更廣泛的設備別名及通用手冊適用性需另有資料與驗收案例。

逐句檢視已完成案例時，核心動作／缺少參數的判斷與引用可對回 MOCK 原文；
但小模型仍不保證每次完成所有表達要求，例如先摘錄再翻譯、額外索取核准資料、完整重述 MOCK 標記。
部分正向答案只給英文原句。自動詞語與引用檢查不能取代正式文件的逐句審閱。

兩位獨立導入人員、乾淨主機及正式核准文件尚未指定；正式 SOP 簽收仍未完成。

## Docker／WSL 與資源回收

本機 Windows Docker CLI 的 Linux 引擎可執行測試；Ubuntu 內的 Docker 指令仍不可用，
不能宣稱截圖中的 Ubuntu WSL 整合已修復。未重裝或取消註冊 Ubuntu，也未重建公司資料。
導入 SOP 已補充 Windows 引擎與 Ubuntu 整合的區別，參考
[Docker WSL 說明](https://docs.docker.com/desktop/features/wsl/)。

依使用者要求，先停止先前用完的 25 個 MOCK 容器，最終補驗一次只啟動一家公司，
並在每組驗證的 `finally` 關閉服務。完成時確認沒有任何運行中的容器、Ollama 沒有載入模型，
再關閉 Docker Desktop；保留容器、資料目錄、volume 與證據。
最終關閉狀態見 [final-cleanup.json](../../outputs/evidence-guard-20260925/final-cleanup.json)。
