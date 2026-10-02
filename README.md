# 生產用料追溯系統 MVP

## 技術

- 前端：HTML、CSS、JavaScript
- 後端：FastAPI
- 資料庫：SQLite

## Windows 啟動

1. 安裝 Python 3.10～3.14（已支援 Python 3.14）。
2. 雙擊 `start.bat`。
3. 開啟 <http://127.0.0.1:8000>。

## 手動啟動

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## API 文件

- Swagger UI：<http://127.0.0.1:8000/docs>
- 健康檢查：<http://127.0.0.1:8000/api/health>

## MVP 資料

啟動程式會自動偵測 Python 3.14、3.13、3.12 或 3.11。首次啟動會建立
`production_trace.db`，並建立當日 A、B 生產線測試排程與 BOM。

## 正式環境待辦

- 將排程及 BOM 改由 ERP／Oracle 唯讀 API 提供。
- SQLite 改為正式資料庫。
- 增加登入、角色權限、HTTPS、備份及資料更正流程。
