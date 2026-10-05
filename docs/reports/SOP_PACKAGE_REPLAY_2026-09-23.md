# 同一份基礎包的導入重跑紀錄

## 交付目標

不同導入人員拿同一份基礎包，依 [公司導入 SOP](../guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md)
填設定、建立帳號及匯入公司文件，過程不修改程式。需要開發者臨場補程式或補未記錄指令時，
應修正共用版本與 SOP，不能將公司專用修補當作導入已完成。

本次是同一台既有主機上的自動化重跑，使用全新解壓目錄、資料庫、帳號及 Qdrant volume。
沿用主機既有 Python 套件、Docker 建置快取、Ollama 及檢索模型快取；不是乾淨作業系統安裝測試，
也不是兩位獨立人員的操作試驗。這兩項不可由本報告推論已完成。

## 固定輸入

基礎 ZIP：`exports/mainthub-company-template-20260923-sop.zip`

```text
ZIP SHA256
225ae2c183339144af1189ecb5cc22b4d8c10444bfba2c3b4f10c113c4ee4ab2

template-manifest.json SHA256
750e058e0822500763703d162f6e514e25b990202e446bb322e373ddbb75e606
```

包內包含 SOP、設定範例、部署初始化、備份還原及驗收工具，以及 209 份共用檔案的 SHA256 清單。
包內 README 與 SOP 連結均已檢查；沒有包含公司正式資料、帳密、備份或模型快取。
`scripts/verify_template_bundle.py` 可在解壓後及完成導入後檢查共用檔案，
允許另建公司設定及執行資料，能偵測共用檔案缺少或被修改。
清單用於比對檔案一致性，不是數位簽章或防竄改認證。

| 項目 | 接收目錄 A | 接收目錄 B |
| --- | --- | --- |
| 解壓位置 | `receiver-a` | `receiver-b` |
| 公司設定副本 | CNC demo | 空壓機 demo |
| 產生的部署目錄 | `receiver-a-deployment` | `receiver-b-deployment` |
| Compose project | `mainthub-sop-cnc` | `mainthub-sop-compressor` |
| 本機連接埠 | 8141 | 8142 |
| 共用檔案 | 209 份相同 | 209 份相同 |
| 核心程式變更 | 無 | 無 |

相對位置以 `outputs/sop-replay-20260923/` 為起點。
兩邊使用從解壓內容建置的相同 `mainthub:sop-20260923` 映像。
測試輸入為既有 MOCK PDF，不是包內附帶的正式文件；正式導入須準備自己的文件。

## 操作證據

1. 從同一 ZIP 解壓兩次，分別檢查包內檔案完整性。
2. 複製包內公司範例為各自的 `my-company.json`，指定獨立 project、目錄及連接埠。
3. 執行各接收目錄中原封不動的初始化工具，產生新部署與獨立帳密。
4. 啟動各部署，不手動改 Compose、不手動補 SQL。
5. 執行包內 MOCK 驗收工具：透過真實 API 建帳號與匯入文件，透過 Edge 完成四種角色流程。
   CNC 與空壓機各 10 項通過，包含 Ollama、PDF 頁碼／雜湊、知識核准及真實檢索。
6. 使用包內雙向隔離驗收工具執行重啟、備份及還原，12 項檢查全數通過。
   另一家全程資料不變，共 208 次健康檢查均成功（兩輪分別 99、109 次）。
7. 還原後重新檢查兩個基礎目錄及兩個部署目錄，四者的 209 份共用檔案皆無缺少、無變更。

證據目錄：

- `preparation.json`：ZIP 雜湊及兩份解壓結果。
- `integrity-after-workflow.json`：基礎與部署目錄的檔案一致性。
- `integrity-after-restore.json`：完整還原後的四個目錄檢查，皆為 PASS。
- `evidence/cnc/report.json`、`evidence/compressor/report.json`：角色流程與 RAG 證據。
- `evidence/isolation/report.json`：雙向隔離與備份還原結果。
- `report.json`：整體 PASS、ZIP 雜湊、來源一致性、角色流程及隔離結果摘要。

相關測試：53 項及 12 項子測試通過；另通過 Ruff 與差異格式檢查。

## 尚待交付驗收

兩位不依賴開發者即時協助的導入人員，需在支援環境拿同一個已核對 SHA256 的 ZIP，
只依 SOP 完成公司設定至備份還原，並記錄遇到的阻礙。新主機的工具／套件／模型安裝也須實際走過。
本次自動化角色操作不能取代首次改密碼、設定填寫及畫面導入的真人易用性驗收。
資料不足回答、來源排序及實際公司文件品質仍須另行評估。
