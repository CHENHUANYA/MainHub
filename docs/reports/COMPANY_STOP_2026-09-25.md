# 公司停止操作與資源回收

日期：2026-09-25。

`company_service.py` 新增 `stop`，沿用指定部署自己的 `.env`、Compose 檔與 project，
停止該公司的容器並保留資料與 volume。`status` 改為包含已停止的容器，方便確認關閉結果。
停止失敗時以非零狀態結束，明確表示尚未確認關閉，不輸出可能含帳密的 Compose 錯誤內容。

使用方式：

```powershell
python scripts/company_service.py --deployment "公司部署目錄" stop
python scripts/company_service.py --deployment "公司部署目錄" status
```

[公司導入 SOP](../guides/COMPANY_DEPLOYMENT_SOP_ZH_TW.md#用完後停止與釋放記憶體) 已補上停止、
檢查狀態、卸載 Ollama 模型及下次啟動的步驟。Ollama 與 Docker Desktop 是主機共用服務，
單一公司的 `stop` 不會自動關閉它們；所有使用者結束查詢後再釋放模型與結束 Docker Desktop。

## 驗證與封裝

- 公司初始化／環境隔離、啟動檢查、封裝與部署文件相關測試共 **32 項通過**，Ruff 通過。
- CLI 測試覆蓋四種操作，確認 shell 中另一公司的 project／密碼不會覆蓋指定部署，
  並確認停止失敗不宣稱成功、不洩漏錯誤中的帳密。
- 新包解壓兩份，各 **225 份共用檔案**完整性通過，兩份的 CLI 均可載入並提供 `stop`。
- 與上一輪 citation 包逐檔比較，只有 `scripts/company_service.py` 和公司導入 SOP 變動。
  應用程式、RAG 提示詞與識別碼防護均相同；沒有沿用前輪結果宣稱本 ZIP 已完成實機驗收。

新包：[mainthub-company-template-20260925-stop.zip](../../exports/mainthub-company-template-20260925-stop.zip)

SHA256：`57bece99fea3d1231611fe79aa96650689409a1bc20cc181f6a7e965dca2580b`

封裝差異與完整性證據：[report.json](../../outputs/company-stop-20260925/report.json)。
本輪驗證到 Docker 命令邊界，**沒有啟動 Docker、重新建置映像或執行真實容器停止演練**。
結束時確認 Docker Desktop／backend 程序不存在，`ollama ps` 沒有載入模型。

兩位獨立導入人員、主機與正式文件仍待提供。前輪 RAG 實機驗證與其限制保留在
[回答品質修正紀錄](RAG_GROUNDING_FIX_2026-09-25.md)，正式 SOP 簽收仍未完成。
