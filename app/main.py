from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR.parent / "production_trace.db"
STATIC_DIR = BASE_DIR / "static"

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def batch_code(material_code: str, expiry_date: date, received_date: date) -> str:
    return f"{material_code}-{expiry_date:%Y%m%d}-{received_date:%Y%m%d}"


def init_db() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS products (
      product_code TEXT PRIMARY KEY,
      product_name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bom_details (
      product_code TEXT NOT NULL,
      material_code TEXT NOT NULL,
      material_name TEXT NOT NULL,
      ratio REAL NOT NULL CHECK (ratio > 0),
      PRIMARY KEY (product_code, material_code),
      FOREIGN KEY (product_code) REFERENCES products(product_code)
    );
    CREATE TABLE IF NOT EXISTS production_schedules (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      production_date TEXT NOT NULL,
      production_line TEXT NOT NULL,
      product_code TEXT NOT NULL,
      planned_weight REAL NOT NULL CHECK (planned_weight > 0),
      status TEXT NOT NULL DEFAULT 'pending',
      UNIQUE (production_date, production_line, product_code),
      FOREIGN KEY (product_code) REFERENCES products(product_code)
    );
    CREATE TABLE IF NOT EXISTS production_records (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      schedule_id INTEGER NOT NULL UNIQUE,
      product_batch TEXT NOT NULL UNIQUE,
      actual_weight REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'completed',
      completed_at TEXT NOT NULL,
      FOREIGN KEY (schedule_id) REFERENCES production_schedules(id)
    );
    CREATE TABLE IF NOT EXISTS material_usages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      production_record_id INTEGER NOT NULL,
      material_code TEXT NOT NULL,
      material_name TEXT NOT NULL,
      standard_weight REAL NOT NULL,
      FOREIGN KEY (production_record_id) REFERENCES production_records(id)
    );
    CREATE TABLE IF NOT EXISTS material_usage_lots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      material_usage_id INTEGER NOT NULL,
      expiry_date TEXT NOT NULL,
      received_date TEXT NOT NULL,
      material_batch TEXT NOT NULL,
      used_weight REAL NOT NULL CHECK (used_weight > 0),
      UNIQUE (material_usage_id, material_batch),
      FOREIGN KEY (material_usage_id) REFERENCES material_usages(id)
    );
    CREATE TABLE IF NOT EXISTS drafts (
      schedule_id INTEGER PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY (schedule_id) REFERENCES production_schedules(id)
    );
    CREATE TABLE IF NOT EXISTS audit_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      action TEXT NOT NULL,
      target_type TEXT NOT NULL,
      target_id INTEGER,
      detail TEXT,
      created_at TEXT NOT NULL
    );
    """
    with db() as conn:
        conn.executescript(schema)
        products = [
            ("P001", "冷凍豬肉水餃"), ("P002", "冷凍韭菜水餃"),
            ("P101", "香菇雞肉丸"), ("P102", "黑胡椒肉排"),
        ]
        boms = [
            ("P001", "M001", "麵粉", .38), ("P001", "M002", "豬肉", .34),
            ("P001", "M003", "高麗菜", .24), ("P001", "M004", "調味料", .04),
            ("P002", "M001", "麵粉", .38), ("P002", "M002", "豬肉", .31),
            ("P002", "M005", "韭菜", .27), ("P002", "M004", "調味料", .04),
            ("P101", "M101", "雞肉", .72), ("P101", "M102", "香菇", .12),
            ("P101", "M103", "澱粉", .11), ("P101", "M104", "調味料", .05),
            ("P102", "M105", "豬肉", .82), ("P102", "M103", "澱粉", .10),
            ("P102", "M106", "黑胡椒醬", .08),
        ]
        conn.executemany("INSERT OR IGNORE INTO products VALUES (?, ?)", products)
        conn.executemany("INSERT OR IGNORE INTO bom_details VALUES (?, ?, ?, ?)", boms)
        day = date.today().isoformat()
        schedules = [
            (day, "A", "P001", 500), (day, "A", "P002", 320),
            (day, "B", "P101", 420), (day, "B", "P102", 280),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO production_schedules
               (production_date, production_line, product_code, planned_weight)
               VALUES (?, ?, ?, ?)""",
            schedules,
        )
        conn.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="生產用料追溯 API", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class LotInput(BaseModel):
    expiry_date: date
    received_date: date
    used_weight: float = Field(gt=0)


class MaterialInput(BaseModel):
    material_code: str
    lots: list[LotInput] = Field(min_length=1)


class RecordInput(BaseModel):
    actual_weight: float = Field(gt=0)
    materials: list[MaterialInput] = Field(min_length=1)


class DraftInput(BaseModel):
    materials: list[dict]


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/schedules")
def schedules(
    production_date: date,
    production_line: str = Query(min_length=1, max_length=20),
):
    with db() as conn:
        rows = conn.execute(
            """SELECT s.*, p.product_name
               FROM production_schedules s
               JOIN products p ON p.product_code = s.product_code
               WHERE s.production_date = ? AND s.production_line = ?
               ORDER BY s.id""",
            (production_date.isoformat(), production_line),
        ).fetchall()
        result = []
        for row in rows:
            bom = conn.execute(
                """SELECT material_code, material_name, ratio
                   FROM bom_details WHERE product_code = ?
                   ORDER BY material_code""",
                (row["product_code"],),
            ).fetchall()
            result.append({
                "id": row["id"],
                "production_date": row["production_date"],
                "production_line": row["production_line"],
                "product_code": row["product_code"],
                "product_name": row["product_name"],
                "planned_weight": row["planned_weight"],
                "status": row["status"],
                "bom": [{
                    **dict(item),
                    "standard_weight": round(row["planned_weight"] * item["ratio"], 3),
                } for item in bom],
            })
        return result


@app.get("/api/records/{schedule_id}/draft")
def get_draft(schedule_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT payload, updated_at FROM drafts WHERE schedule_id = ?",
            (schedule_id,),
        ).fetchone()
    if not row:
        return {"draft": None}
    return {"draft": json.loads(row["payload"]), "updated_at": row["updated_at"]}


@app.put("/api/records/{schedule_id}/draft")
def save_draft(schedule_id: int, payload: DraftInput):
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM production_schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, "找不到生產排程")
        stamp = now_iso()
        conn.execute(
            """INSERT INTO drafts (schedule_id, payload, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(schedule_id) DO UPDATE SET
                 payload = excluded.payload, updated_at = excluded.updated_at""",
            (schedule_id, payload.model_dump_json(), stamp),
        )
        conn.commit()
    return {"saved": True, "updated_at": stamp}


@app.post("/api/records/{schedule_id}/complete", status_code=201)
def complete_record(schedule_id: int, payload: RecordInput):
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            schedule = conn.execute(
                """SELECT s.*, p.product_name
                   FROM production_schedules s
                   JOIN products p ON p.product_code = s.product_code
                   WHERE s.id = ?""",
                (schedule_id,),
            ).fetchone()
            if not schedule:
                raise HTTPException(404, "找不到生產排程")
            if schedule["status"] == "completed":
                raise HTTPException(409, "此生產品項已完成")

            bom_rows = conn.execute(
                "SELECT * FROM bom_details WHERE product_code = ?",
                (schedule["product_code"],),
            ).fetchall()
            bom = {row["material_code"]: row for row in bom_rows}
            supplied = {item.material_code for item in payload.materials}
            if supplied != set(bom):
                raise HTTPException(422, "原料項目與 BOM 不一致")

            product_batch = (
                schedule["production_date"].replace("-", "")
                + f"-{schedule['production_line']}-{schedule['product_code']}"
            )
            cur = conn.execute(
                """INSERT INTO production_records
                   (schedule_id, product_batch, actual_weight, completed_at)
                   VALUES (?, ?, ?, ?)""",
                (schedule_id, product_batch, payload.actual_weight, now_iso()),
            )
            record_id = cur.lastrowid
            for material in payload.materials:
                source = bom[material.material_code]
                standard = round(schedule["planned_weight"] * source["ratio"], 3)
                usage_id = conn.execute(
                    """INSERT INTO material_usages
                       (production_record_id, material_code, material_name, standard_weight)
                       VALUES (?, ?, ?, ?)""",
                    (record_id, source["material_code"], source["material_name"], standard),
                ).lastrowid
                seen = set()
                for lot in material.lots:
                    code = batch_code(material.material_code, lot.expiry_date, lot.received_date)
                    if code in seen:
                        raise HTTPException(422, f"{material.material_code} 有重複批號")
                    seen.add(code)
                    conn.execute(
                        """INSERT INTO material_usage_lots
                           (material_usage_id, expiry_date, received_date, material_batch, used_weight)
                           VALUES (?, ?, ?, ?, ?)""",
                        (usage_id, lot.expiry_date.isoformat(), lot.received_date.isoformat(),
                         code, lot.used_weight),
                    )
            conn.execute(
                "UPDATE production_schedules SET status = 'completed' WHERE id = ?",
                (schedule_id,),
            )
            conn.execute("DELETE FROM drafts WHERE schedule_id = ?", (schedule_id,))
            conn.execute(
                """INSERT INTO audit_logs
                   (action, target_type, target_id, detail, created_at)
                   VALUES ('complete', 'production_record', ?, ?, ?)""",
                (record_id, product_batch, now_iso()),
            )
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise HTTPException(409, "資料重複或狀態已更新") from exc
        except Exception:
            conn.rollback()
            raise
    return {"id": record_id, "product_batch": product_batch, "status": "completed"}


@app.get("/api/trace")
def trace(
    q: str = "",
    type: Literal["all", "product", "material"] = "all",
):
    needle = f"%{q.strip()}%"
    product_filter = """(
      p.product_code LIKE ? OR p.product_name LIKE ? OR r.product_batch LIKE ?
    )"""
    material_filter = """EXISTS (
      SELECT 1 FROM material_usages mu2
      JOIN material_usage_lots ml2 ON ml2.material_usage_id = mu2.id
      WHERE mu2.production_record_id = r.id
        AND (mu2.material_code LIKE ? OR mu2.material_name LIKE ? OR ml2.material_batch LIKE ?)
    )"""
    if not q.strip():
        where, params = "1=1", []
    elif type == "product":
        where, params = product_filter, [needle] * 3
    elif type == "material":
        where, params = material_filter, [needle] * 3
    else:
        where, params = f"({product_filter} OR {material_filter})", [needle] * 6

    with db() as conn:
        rows = conn.execute(
            f"""SELECT r.*, s.production_date, s.production_line,
                       p.product_code, p.product_name
                FROM production_records r
                JOIN production_schedules s ON s.id = r.schedule_id
                JOIN products p ON p.product_code = s.product_code
                WHERE {where}
                ORDER BY r.completed_at DESC
                LIMIT 200""",
            params,
        ).fetchall()
        result = []
        for row in rows:
            materials = conn.execute(
                """SELECT id, material_code, material_name, standard_weight
                   FROM material_usages WHERE production_record_id = ?
                   ORDER BY id""",
                (row["id"],),
            ).fetchall()
            material_result = []
            for material in materials:
                lots = conn.execute(
                    """SELECT expiry_date, received_date, material_batch, used_weight
                       FROM material_usage_lots WHERE material_usage_id = ?
                       ORDER BY id""",
                    (material["id"],),
                ).fetchall()
                material_result.append({
                    "material_code": material["material_code"],
                    "material_name": material["material_name"],
                    "standard_weight": material["standard_weight"],
                    "lots": [dict(lot) for lot in lots],
                })
            result.append({
                "id": row["id"],
                "production_date": row["production_date"],
                "production_line": row["production_line"],
                "product_code": row["product_code"],
                "product_name": row["product_name"],
                "product_batch": row["product_batch"],
                "actual_weight": row["actual_weight"],
                "completed_at": row["completed_at"],
                "materials": material_result,
            })
    return result
