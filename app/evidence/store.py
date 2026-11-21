import json,sqlite3
from datetime import datetime,timezone
from app.config import DATA_DIR
from app.errors import DomainError

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS evidence_batches(
        id TEXT PRIMARY KEY,payload TEXT NOT NULL,raw_text TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,rule_version TEXT NOT NULL,created_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS certificates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,evidence_id TEXT,
        version INTEGER NOT NULL,status TEXT NOT NULL CHECK(status IN ('active','superseded')),
        payload TEXT NOT NULL,created_at TEXT NOT NULL)""")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_cert_per_run ON certificates(run_id) WHERE status='active'")
    db.execute("""CREATE TABLE IF NOT EXISTS certificate_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,event TEXT NOT NULL,
        detail TEXT NOT NULL,created_at TEXT NOT NULL)""")
    return db

def save_evidence(batch_id,payload,raw_text,input_sha256,rule_version):
    # INSERT OR IGNORE：同源重跑只复用既有批次，不新增覆盖
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO evidence_batches(id,payload,raw_text,input_sha256,rule_version,created_at) VALUES (?,?,?,?,?,?)",
                   (batch_id,json.dumps(payload,ensure_ascii=False),raw_text,input_sha256,rule_version,
                    datetime.now(timezone.utc).isoformat()))
    return get_evidence(batch_id)

def get_evidence(batch_id):
    with connect() as db:
        row=db.execute("SELECT payload FROM evidence_batches WHERE id=?",(batch_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","证据批次不存在",404)
    return json.loads(row[0])

def get_raw_evidence(batch_id):
    """原始证据原样取回，不参与任何改写。"""
    with connect() as db:
        row=db.execute("SELECT raw_text FROM evidence_batches WHERE id=?",(batch_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","证据批次不存在",404)
    return row[0]

def list_evidence():
    with connect() as db:
        rows=db.execute("SELECT id,payload,created_at FROM evidence_batches ORDER BY rowid DESC").fetchall()
    return [{"evidence_id":i,"reconciled":json.loads(p)["metrics"]["reconciled"],
             "measurement_records":json.loads(p)["metrics"]["measurement_records"],
             "item_count":json.loads(p)["metrics"]["item_count"],"created_at":t} for i,p,t in rows]

def active_certificate(run_id):
    with connect() as db:
        row=db.execute("SELECT id,version,payload,created_at FROM certificates WHERE run_id=? AND status='active'",(run_id,)).fetchone()
    if not row: return None
    payload=json.loads(row[2])
    return {"certificate_id":row[0],"version":row[1],"created_at":row[3],**payload}

def certificate_history(run_id):
    with connect() as db:
        rows=db.execute("SELECT id,version,status,payload,created_at FROM certificates WHERE run_id=? ORDER BY id DESC",(run_id,)).fetchall()
    return [{"certificate_id":r[0],"version":r[1],"status":r[2],"created_at":r[4],**json.loads(r[3])} for r in rows]

def _log(db,run_id,event,detail):
    db.execute("INSERT INTO certificate_events(run_id,event,detail,created_at) VALUES (?,?,?,?)",
               (run_id,event,detail,datetime.now(timezone.utc).isoformat()))

def publish_certificate(run_id,evidence_id,run_payload,before_publish=None):
    """正式签证发布（发布门由 service.gate / certificate_payload 先行校验）。

    事务：旧版先置 superseded、新版置 active；任一步失败整体回滚，旧版保留可用。
    幂等：同一 run + 同一证据批次重复发布，直接返回当前 active 版本，不产生新版本。
    before_publish 仅供测试注入事务前故障；事务内部故障由 with db 自动回滚。
    """
    db=connect()
    try:
        existing=db.execute("SELECT id,version,payload FROM certificates WHERE run_id=? AND status='active'",(run_id,)).fetchone()
        if existing and json.loads(existing[2]).get("evidence_id")==evidence_id:
            return {"certificate_id":existing[0],"version":existing[1],**json.loads(existing[2])}
        if before_publish is not None: before_publish(db)  # 测试注入的故障点
        with db:
            if existing:
                db.execute("UPDATE certificates SET status='superseded' WHERE id=?",(existing[0],))
                version=existing[1]+1
            else:
                version=1
            payload={"run_id":run_id,"evidence_id":evidence_id,
                     "run_decision":run_payload.get("decision"),
                     "covered_items":run_payload["covered_items"],
                     "gaps":run_payload["gaps"],
                     "input_sha256":run_payload["input_sha256"],
                     "rule_version":run_payload["rule_version"]}
            db.execute("INSERT INTO certificates(run_id,evidence_id,version,status,payload,created_at) VALUES (?,?,?, 'active',?,?)",
                       (run_id,evidence_id,version,json.dumps(payload,ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat()))
            _log(db,run_id,"PUBLISHED",f"version={version},evidence={evidence_id}")
        row=db.execute("SELECT id,version,payload FROM certificates WHERE run_id=? AND status='active'",(run_id,)).fetchone()
        return {"certificate_id":row[0],"version":row[1],**json.loads(row[2])}
    except Exception:
        db.rollback()
        try:
            with connect() as log_db:
                _log(log_db,run_id,"PUBLISH_FAILED","发布事务回滚，旧版保留")
        except Exception:
            pass  # 留痕失败不得掩盖原始异常
        raise
    finally:
        db.close()

def list_events(run_id):
    with connect() as db:
        rows=db.execute("SELECT event,detail,created_at FROM certificate_events WHERE run_id=? ORDER BY id",(run_id,)).fetchall()
    return [{"event":e,"detail":d,"created_at":t} for e,d,t in rows]
