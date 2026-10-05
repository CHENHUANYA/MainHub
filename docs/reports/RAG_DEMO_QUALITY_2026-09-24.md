# CNC／空壓機查詢展示與品質檢查

本次以兩家公司各五題、共十題 **MOCK DATA**，完成真實 `gemma4:e2b` 問答與來源比對。
使用相同核心映像，資料庫、知識庫、文件及帳號獨立；不是正式企業文件或設備操作成效評估。
題庫在測試前固定，修正後沿用相同問題及 PDF 雜湊，保留原始失敗回答。

## 已交付

- [查詢展示 SOP](../guides/RAG_DEMO_ACCEPTANCE_ZH_TW.md)：畫面操作順序、正確來源、資料不足判定及失敗保留方式。
- [導入驗收紀錄表](../../templates/COMPANY_ACCEPTANCE_RECORD_ZH_TW.md)：不同導入人員可直接複製填寫。
- `templates/acceptance.cnc-demo.json` 與 `templates/acceptance.compressor-demo.json`：各含五題與可產生 PDF 的原文。
- `scripts/verify_company_rag_quality.py`：產生示範 PDF／問題卡，或在隔離 demo 部署留下模型回答、引用及檢查結果。

## 發現與共用修正

| 實際問題 | 修正與結果 |
| --- | --- |
| 問 CNC 扭矩、AIR-01／E-42 時，抄出不相關的 CNC 3102 警報 | 只有明確的數字警報查詢使用逐字模式，一般問題改用有來源限制的問答提示詞；原題重跑後說明資料缺口 |
| CNC 解析器丟棄 Explanation／Remedy 等欄位標題，模型自行補 Reaction 或空白欄位 | 保留原文欄位界線，取消強迫套用所有欄位的回答格式；重跑以原文摘錄及來源呈現 |
| 缺資料時仍列出不相關的其他代碼處置 | 通用維修提示詞要求直接說明缺口，不把其他代碼／設備的步驟列為建議檢查 |
| 測試工具把「缺少資訊」判成沒有拒答訊號 | 補上「缺少／未提及」的辨識及反例測試；此為評估器缺陷，不能計為模型錯誤 |
| 測試工具要求中文問題必須呼叫英文 reranker | 保留既有中文排序保護，改以獨立英文檢索探測 reranker，兩者分開記錄 |

這些都是共用產品修正，沒有為某家公司另改一份程式。舊索引不會自動補回已省略的欄位標題，
既有部署的重新匯入步驟見 [模板說明](../guides/COMPANY_TEMPLATE_ZH_TW.md)；本次使用全新索引驗證。

## 最終十題結果

| 題目 | 預期來源／缺口 | 來源與內容比對 |
| --- | --- | --- |
| CNC 3101 | MOCK CNC PDF 第 1 頁 | 保留 Explanation／Remedy，記錄 BLUE 與觀察時間，保留非正式操作聲明 |
| CNC 3102 | MOCK CNC PDF 第 2 頁 | 訓練表與工作表 ID 交給維修團隊，欄位與來源頁碼正確 |
| CNC 3999 | 文件沒有該代碼 | 明確表示沒有 3999 資訊，沒有套用其他警報處置 |
| CNC 主軸扭矩 | 文件未提供 Nm 數值 | 不給猜測數值，要求相應官方文件 |
| CNC 庫問 AIR-01／E-42 | 文件不屬於空壓機 | 指出無對應資訊，沒有使用另一家公司文件 |
| 空壓機 E-42 | MOCK SOP 第 1 頁 | 記錄 VIOLET 與觀察時間，引用正確 |
| 空壓機 E-43 | MOCK SOP 第 2 頁 | 將 Q-17 交給維修團隊，引用正確 |
| 空壓機 E-99 | 文件沒有該代碼 | 直接說明缺少資訊，未借用 E-42／E-43 處置 |
| 空壓機壓力上限 | 文件未提供 bar 數值 | 說明缺少資訊，沒有推測數值 |
| 空壓機庫問 CNC-01／3101 | 文件不屬於 CNC | 說明缺少資訊，沒有使用 CNC 庫來源 |

以上內容比對由 Codex 依原始 PDF 與完整回答審閱，**不是獨立人員或設備專家的簽收**。
空壓機的負向回答簡短，只指出資料不足；後續可改善為同時詢問所需型號及核准文件。
自動結果名稱刻意保留 `GATES_PASS_REVIEW_REQUIRED`，不把詞語或來源檢查當成語意品質分數。

## 證據與執行範圍

相對路徑均以 `outputs/rag-quality-20260924/` 為起點：

| 證據 | 路徑 |
| --- | --- |
| 原始 PDF、問題卡及來源 SHA256 | `cnc-pack/`、`compressor-pack/` |
| 修正前回答 | `cnc-baseline-ready/report.json`、`compressor-baseline/report.json` |
| 第一次修正與評估器誤判 | `cnc-fixed-run/report.json`、`air-fixed-run/report.json` |
| 最終各五題的完整回答與引用 | `cnc-final-run/report.json`、`air-final-run/report.json` |
| 可逐題閱讀的完整回答 | 各最終目錄中的 `review.md` |
| 真實聊天畫面的四題回答及截圖 | `browser-release/report.json` 與同目錄 PNG |
| 兩個實例的共同映像與 187 份核心檔案雜湊 | `runtime-source-proof.json` |
| 基礎包兩份解壓副本與展示包完整性 | `release-proof.json` |

最終部署為 `mainthub-quality-cnc-final`／8181 與 `mainthub-quality-air-final`／8182，
共同使用 `mainthub:quality-20260924-final`，模型為 `gemma4:e2b`，十題測試溫度為 0、輸出上限為 512 tokens。
每家公司另外通過空知識庫回報不可用、另一知識庫請求拒絕、embedding 已載入與英文 reranker 實際執行四項檢查。
中文題目使用既有 BM25／向量／RRF 保護路徑，不宣稱英文 reranker 參與這些中文回答。

另以無頭 Edge 實際登入兩家公司，在聊天畫面各執行一題正向與一題缺少參數查詢，四題均通過來源與回答檢查。
此輪使用畫面原本的溫度 0.7，而非工程測試的 0；截圖也確認頁首讀取各自公司名稱，已移除固定的舊公司品牌。

## 本次交付檔

- 基礎包：`exports/mainthub-company-template-20260924-quality.zip`，220 份共用檔案。
- 展示包：`exports/mainthub-demo-acceptance-20260924.zip`，15 份 PDF／問題卡／紀錄表／前後結果與截圖。

```text
基礎 ZIP SHA256
509f4b680ea23d561d69fd0c0194cd0a16e468056883c33e2224f50a7e069a4b

展示 ZIP SHA256
5c52c5cc77235c105893eecd98adeadf175c3161cad535b6dacf89a2ad7fb6e2
```

同一基礎 ZIP 解壓兩份，兩邊各 220 份共用檔案完整性檢查通過；展示包的 15 份內容亦通過。
兩個實際執行中的公司容器使用相同映像，187 份 Python／前端核心檔案均與本次來源一致。
此處檢查的是檔案一致性與本輪查詢行為，沒有把解壓驗證當成兩位真人的獨立 SOP 演練。

回歸為 **994 項 Python 測試、52 項子測試、29 項 JavaScript 測試通過**；Ruff、mypy 通過。
先前驗收資料及 PostgreSQL 資料未清除，僅停止已完成比較的舊測試應用容器以釋放資源。

## 尚待正式簽收

正式公司應以自己的核准文件及代表性問題驗收，並由兩位不同導入人員使用同一基礎 ZIP，
從支援的乾淨環境只照 SOP 完成。這次開發者自動化及 MOCK 原文審閱不能代替該項簽收。
