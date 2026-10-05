# 回答表達與串流原文修正

日期：2026-09-26（臺灣時間；原始 JSON 使用 UTC）。
續接 [2026-09-25 精修紀錄](REFINEMENT_IMPLEMENTATION_2026-09-25.md)，處理漏摘錄與補件不具體的案例。
本報告為 MOCK 工程驗收，不代表正式公司文件或真人導入簽收。

## 程式變更

- 一般維護回答在送出前核對原文摘錄、繁中說明及摘錄對應的檔名／頁碼。摘錄須來自此次檢索文字。
  格式不符最多重試一次；仍不符時回覆未完成提示，快照記為 `provider=answer_guard`、`answer_state=fallback`，不冒充成功模型回答。
- 資料不足時，將空泛補件要求補成對應設備手冊、壓力規格或扭矩規格；不加入操作步驟或數值。
- 一般維護 SSE 在格式檢查完成後才送正文，首次文字延遲包括原始生成及可能的一次重試。
  CNC 明確原文查詢仍逐片段送出。
- 實測發現原生 SSE 對每片段去掉開頭換行，使單獨換行片段消失。改為只整理第一個有效片段前的換行；
  後續換行原樣保存，接收正文與持久化快照一致。
- 品質指南及模板入口說明上述行為，也明列格式檢查不證明翻譯、事實或設備適用性正確。

主要實作：`services/answer_format.py`、`routes/chat_lookup_routes.py`、
`services/chat_streaming.py`、`services/chat_completion.py`。

## 回歸與真實檢索

回歸範圍為 `tests/rag`、公司設定／文件領域、API 回覆契約及部署文件：
**323 項通過，另有 12 項 subtests 通過**。修改檔案 Ruff 與六個來源檔 mypy 通過。
新增測試涵蓋格式修復成功／失敗、最多兩次模型呼叫、錯誤原答不送出、取消不保存、補件不額外呼叫模型及原生 SSE 換行。
後續模板說明修改另重跑部署文件四項，皆通過；不累加成另一個全套測試數。

真實檢索使用 PostgreSQL、Qdrant、主機 Ollama `gemma4:e2b`，每次只啟動一組全新 MOCK 公司。
嵌入模型為 `mixedbread-ai/mxbai-embed-large-v1`；重排模型為 `cross-encoder/ms-marco-MiniLM-L-6-v2`。
中文題仍走既有略過英文重排的路徑；另以英文探測確認重排實際執行，不把該探測冒充中文題的重排結果。

工程映像：`mainthub:answer-format-20260926`。
映像 ID：`sha256:7a224f3f5f0a05aa3ef2353f2e695b28a3cf1e70af256b1f5600d6fb26ea4e28`。
此映像由工作目錄建置，**不是固定 ZIP 的雙公司全流程證據**。

| 題組 | JSON | SSE | 逐句核對 |
| --- | --- | --- | --- |
| 空壓機 | 5/5 | 5/5 | VIOLET、時間戳、Q-17、維護團隊及不足壓力規格均符合來源 |
| 不相關頁面回歸 | 5/5 | 5/5 | 儀表讀數與維護通報均來自第 1 頁，未借用不相關頁 |
| CNC | 5/5 | 5/5 | 保留完整原文、欄位及限制，換行不再黏合；不足扭矩時索取規格 |

全部三十份正文的 MOCK 聲明、來源與快照一致性通過；SSE 均有結束事件及單一回答 ID。
其中十八次走模型回答、十二次走識別碼防護；有界格式重試另計，不能將三十次都稱為模型生成。
三個容器內八個相關檔案均符合記錄的來源雜湊。

證據：[run3 驗收](../../outputs/answer-format-20260925/run3/acceptance.json)、
[三十份回答逐句核對](../../outputs/answer-format-20260925/run3/semantic-review.json)。
逐句核對由 Codex 完成，不等同獨立人員簽收或任意問題正確率。
本輪空壓機／CNC 各零次格式重試，來源對照題組兩次格式重試；皆未超過每次回答一次重試。

## 跨設備補件案例

另起全新公司，匯入 AIR-01 出席紀錄及 AIR-02／E-42 操作訓練段落；詢問 AIR-01 的 E-42。
真實檢索後的 JSON／SSE 均回覆：

> 資料不足：本次檢索內容未提供 AIR-01 的 E-42 應記錄的內容及通報對象。請提供對應設備的核准警報手冊。

兩份回答均有 MOCK 聲明、來源快照及完整結束事件，未抄用 AIR-02 的儀表讀數／通報步驟。
由 Codex 對照兩份原文核對通過。證據：[boundary 報告](../../outputs/answer-format-20260925/boundary/report.json)、
[JSON 原答](../../outputs/answer-format-20260925/boundary/json/report.json)。這是一組特定邊界案例，不擴張為任意設備適用性保證。
run3 與 boundary 結束均確認無運行容器、無載入模型；Desktop 為緊接的固定包驗收暫留，最終收尾另記。

## 失敗紀錄與限制

- [run1](../../outputs/answer-format-20260925/run1/acceptance.json) 的兩題 CNC SSE 因換行消失而未通過；保留原回答，修正後以 run3 原題重驗。
- [run2](../../outputs/answer-format-20260925/run2/acceptance.json) 空壓機通過，後續 grounding 文件匯入時遇到
  `RemoteProtocolError: Server disconnected without sending a response`，未完成該輪。
  容器事後 `OOMKilled=false`、重啟次數 0；退出碼 137 包含清理階段停止行為，不能用此數字推定中斷根因。
  [診斷取樣](../../outputs/answer-format-20260925/run2/interruption-diagnostic.json) 保留；同映像 run3 通過不等同根因已修復。
- 格式檢查為文字及來源核對，沒有新增確定性的跨片段設備關係推理；正式適用性仍須核准文件與審閱。
- Windows PowerShell／Docker Desktop 是本輪操作路徑；Ubuntu WSL Docker 整合與歷史 Docker API 500 原因仍未修復／確定。
