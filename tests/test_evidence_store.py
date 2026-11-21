import pytest
from app import store as run_store
from app.errors import DomainError
from app.evidence import service,store

HEADER="row_type,record_id,item,period,qty,unit,kind,note\n"
def csv_(rows): return (HEADER+"\n".join(rows)+"\n").encode()
RECONCILED=csv_([
    "measurement,M-1,钢筋,2026-11,100,t,,合测",
    "declaration,M-1,钢筋,2026-11,100,t,,全领",
    "demand,D-1,钢筋,2026-11,100,t,,需求",
])
@pytest.fixture
def run_id(client):
    return client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()["run_id"]

def test_same_evidence_rerun_creates_no_new_batch(evidence_raw):
    "同一证据重跑不新增覆盖批次"
    a=service.execute(evidence_raw);b=service.execute(evidence_raw)
    assert a["evidence_id"]==b["evidence_id"]
    assert len(store.list_evidence())==1

def test_raw_evidence_never_rewritten(evidence_raw):
    e=service.execute(evidence_raw)
    assert store.get_raw_evidence(e["evidence_id"])==evidence_raw.decode("utf-8-sig")

def test_gate_blocks_unreconciled_publish(run_id,over_allocation_raw):
    run=run_store.get(run_id)
    evidence=service.execute(over_allocation_raw)
    with pytest.raises(DomainError) as e: service.publish(run,evidence)
    assert e.value.code=="COVERAGE_NOT_RECONCILED"
    assert store.active_certificate(run_id) is None

def test_publish_idempotent_same_evidence(run_id):
    run=run_store.get(run_id)
    evidence=service.execute(RECONCILED)
    first=service.publish(run,evidence);second=service.publish(run,evidence)
    assert first["certificate_id"]==second["certificate_id"]
    assert first["version"]==second["version"]==1
    assert len(store.certificate_history(run_id))==1

def test_republish_supersedes_old_version(run_id):
    "换证据再发布：旧版保留为 superseded，新版 active，版本递增"
    run=run_store.get(run_id)
    service.publish(run,service.execute(RECONCILED))
    raw2=RECONCILED.replace("100,t,,全领".encode(),"90,t,,部分".encode())
    second=service.publish(run,service.execute(raw2))
    history=store.certificate_history(run_id)
    assert second["version"]==2
    assert [(h["version"],h["status"]) for h in history]==[(2,"active"),(1,"superseded")]
    assert store.active_certificate(run_id)["version"]==2
    # 缺口不进入签证
    assert store.active_certificate(run_id)["gaps"][0]["gap_qty"]=="10"

def test_failed_publish_keeps_old_version(run_id):
    "发布事务失败时整体回滚，旧版保持 active，事件留痕"
    run=run_store.get(run_id)
    service.publish(run,service.execute(RECONCILED))
    raw2=RECONCILED.replace("100,t,,全领".encode(),"80,t,,部分".encode())
    def boom(db): raise RuntimeError("模拟发布中断")
    with pytest.raises(RuntimeError):
        store.publish_certificate(run_id,service.execute(raw2)["evidence_id"],
                                  service.certificate_payload(run,service.execute(raw2)),boom)
    active=store.active_certificate(run_id)
    assert active["version"]==1  # 旧版保留
    events=store.list_events(run_id)
    assert any(e["event"]=="PUBLISH_FAILED" for e in events)
    assert all(e["event"]!="PUBLISHED" or "version=1" in e["detail"] for e in events)

def test_in_transaction_failure_rolls_back(run_id,monkeypatch):
    "事务内部写入失败：with db 整体回滚，旧版仍为 active"
    run=run_store.get(run_id)
    service.publish(run,service.execute(RECONCILED))
    raw2=RECONCILED.replace("100,t,,全领".encode(),"60,t,,部分".encode())
    def broken_log(*a,**k): raise RuntimeError("事件库写入失败")
    monkeypatch.setattr(store,"_log",broken_log)
    with pytest.raises(RuntimeError):
        service.publish(run,service.execute(raw2))
    active=store.active_certificate(run_id)
    assert active["version"]==1
    history=store.certificate_history(run_id)
    assert len(history)==1 and history[0]["status"]=="active"

def test_only_one_active_certificate(run_id):
    run=run_store.get(run_id)
    service.publish(run,service.execute(RECONCILED))
    raw2=RECONCILED.replace("100,t,,全领".encode(),"70,t,,部分".encode())
    service.publish(run,service.execute(raw2))
    active=[h for h in store.certificate_history(run_id) if h["status"]=="active"]
    assert len(active)==1

def test_missing_evidence_404():
    with pytest.raises(DomainError) as e: store.get_evidence("nope")
    assert e.value.status==404

def test_evidence_payload_carries_manifest(evidence_raw):
    e=service.execute(evidence_raw)
    assert len(e["manifest"]["input_sha256"])==64
    assert e["manifest"]["rule_version"]

def test_gb18030_raw_evidence_roundtrip():
    "历史编码的原始证据按原编码留存，不被改写"
    header="row_type,record_id,item,period,qty,unit,kind,note\n"
    raw=(header+"measurement,M-1,钢筋,2026-11,100,t,,合测\n").encode("gb18030")
    e=service.execute(raw)
    assert e["manifest"]["encoding"]=="gb18030"
    assert store.get_raw_evidence(e["evidence_id"]).encode("gb18030")==raw
    # 裁决结果中的中文正常
    assert e["measurements"][0]["record_id"]=="M-1" and e["measurements"][0]["item"]=="001"
