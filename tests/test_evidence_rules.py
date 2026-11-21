import pytest
from decimal import Decimal
from app.errors import DomainError
from app.evidence.intake import parse
from app.evidence.coverage import adjudicate
from app.evidence import service

HEADER="row_type,record_id,item,period,qty,unit,kind,note\n"

def csv_(rows): return (HEADER+"\n".join(rows)+"\n").encode()

def test_shared_measurement_split_within_total():
    "一份总测量记录拆给钢筋和混凝土，分用量之和不超过总测量量"
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,120,t,,合测记录-钢筋分项",
        "measurement,M-1,混凝土,2026-11,60,m³,,合测记录-混凝土分项",
        "declaration,M-1,钢筋,2026-11,70,t,,钢筋分项",
        "declaration,M-1,混凝土,2026-11,40,m³,,混凝土分项",
        "demand,D-1,钢筋,2026-11,70,t,,钢筋需求",
        "demand,D-2,混凝土,2026-11,40,m³,,混凝土需求",
    ])
    r=service.execute(raw)
    m={(x["record_id"],x["item"]):x for x in r["measurements"]}
    assert m[("M-1","001")]["allocated_qty"]=="70"
    assert (m[("M-1","002")]["total_qty"],m[("M-1","002")]["allocated_qty"],m[("M-1","002")]["remaining_qty"])==("60","40","20")
    assert all(x["status"]!="超分" for x in r["measurements"])
    assert r["metrics"]["reconciled"] is True
    assert r["metrics"]["measurement_documents"]==1

def test_over_allocation_blocks_reconciliation(over_allocation_raw):
    "各分项之和超过总测量量 => 超分，整批未对平"
    r=service.execute(over_allocation_raw)
    m={x["record_id"]:x for x in r["measurements"]}["M-101"]
    assert (m["allocated_qty"],m["remaining_qty"],m["status"])==("115","-15","超分")
    assert r["metrics"]["reconciled"] is False
    assert r["metrics"]["blocking_reasons"]==["OVER_ALLOCATION"]
    with pytest.raises(DomainError) as e: service.gate(r)
    assert e.value.code=="COVERAGE_NOT_RECONCILED" and e.value.status==422

def test_unknown_measurement_reference_rejected():
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,100,t,,合测",
        "declaration,M-9,钢筋,2026-11,10,t,,引用不存在",
    ])
    r=service.execute(raw)
    assert r["metrics"]["reconciled"] is False
    assert any(q.get("reason")=="UNKNOWN_REFERENCE" for q in r["quarantine"])
    assert "INVALID_ALLOCATION" in r["metrics"]["blocking_reasons"]

def test_item_out_of_scope_rejected():
    "分用量项不在测量记录覆盖范围内"
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,100,t,,钢筋测量",
        "declaration,M-1,混凝土,2026-11,20,m³,,越界申报",
    ])
    r=service.execute(raw)
    assert any(q.get("reason")=="ITEM_OUT_OF_SCOPE" for q in r["quarantine"])
    assert r["metrics"]["reconciled"] is False

def test_item_gap_against_demand():
    "已覆盖量可回到原始记录，需求未满足部分列为缺口"
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,100,t,,合测",
        "declaration,M-1,钢筋,2026-11,80,t,,部分领用",
        "demand,D-1,钢筋,2026-11,100,t,,本期需求",
    ])
    r=service.execute(raw)
    assert r["metrics"]["reconciled"] is True
    item=r["item_coverage"][0]
    assert (item["covered_qty"],item["demand_qty"],item["gap_qty"],item["status"])==("80","100","20","覆盖缺口")

def test_image_evidence_is_unsupported_not_coverage(evidence_raw):
    "影像无用量：不构成覆盖，列入未采信来源，且不允许携带用量"
    r=service.execute(evidence_raw)
    assert {u["record_id"] for u in r["unsupported_sources"]}>={"IMG-001","IMG-002"}
    assert r["metrics"]["image_evidence"]==2
    bad=csv_(["image,IMG-1,,,5,t,影像,影像带用量"])
    p=parse(bad)
    assert any(q["reason"]=="IMAGE_HAS_QTY" for q in p["quarantine"])

def test_unused_measurement_listed():
    "未被任何工程项使用的测量记录列入未使用来源"
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,100,t,,已使用",
        "measurement,M-2,混凝土,2026-11,50,m³,,未使用",
        "declaration,M-1,钢筋,2026-11,100,t,,全领",
        "demand,D-1,钢筋,2026-11,100,t,,需求",
    ])
    r=service.execute(raw)
    assert [u["record_id"] for u in r["unused_sources"]]==["M-2"]

def test_intake_duplicates_and_conflicts():
    "完全重复不新增覆盖；同标识冲突隔离"
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,100,t,,首条",
        "measurement,M-1,钢筋,2026-11,100,t,,首条",
        "measurement,M-1,钢筋,2026-11,90,t,,冲突",
    ])
    p=parse(raw)
    assert p["metrics"]["duplicate"]==1
    assert any(q["reason"]=="DUPLICATE_CONFLICT" for q in p["quarantine"])
    assert len(p["rows"])==1

def test_multiple_allocations_same_measurement_are_kept():
    "同一测量记录允许多条分用量拆分并累加守恒"
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,100,t,,合测",
        "declaration,M-1,钢筋,2026-11,60,t,,拆一",
        "declaration,M-1,钢筋,2026-11,40,t,,拆二",
        "demand,D-1,钢筋,2026-11,100,t,,需求",
    ])
    r=service.execute(raw)
    assert r["metrics"]["accepted_allocations"]==2
    assert {x["record_id"]:x for x in r["measurements"]}["M-1"]["status"]=="已覆盖"

def test_bad_header_and_unknown_item():
    with pytest.raises(DomainError) as e: parse(b"row_type,record_id\n")
    assert e.value.code=="BAD_HEADER"
    p=parse(csv_(["measurement,M-1,999,2026-11,30,t,,未登记项"]))
    assert any(q["reason"]=="UNKNOWN_ITEM" for q in p["quarantine"])

def test_source_lines_trace_back(evidence_raw):
    "每条覆盖结论都能回到物理来源行"
    r=service.execute(evidence_raw)
    for m in r["measurements"]: assert m["source_lines"]
    for a in r["allocations"]: assert a["source_lines"]
    assert sum(int(m["allocated_qty"]) for m in r["measurements"] if m["item"]=="001")>=0

def test_negative_qty_quarantined():
    p=parse(csv_(["measurement,M-1,钢筋,2026-11,-1,t,,负用量"]))
    assert any(q["reason"]=="NEGATIVE_QTY" for q in p["quarantine"])

def test_no_measurement_blocks():
    r=adjudicate({"rows":[],"quarantine":[],"metrics":{"input":0,"duplicate":0,"blank":0,"repeated_headers":0}})
    assert r["metrics"]["reconciled"] is False
    assert r["metrics"]["blocking_reasons"]==["NO_EVIDENCE"]

def test_decimal_conservation():
    raw=csv_([
        "measurement,M-1,钢筋,2026-11,0.3,t,,小数合测",
        "declaration,M-1,钢筋,2026-11,0.1,t,,拆一",
        "declaration,M-1,钢筋,2026-11,0.2,t,,拆二",
        "demand,D-1,钢筋,2026-11,0.3,t,,需求",
    ])
    r=service.execute(raw)
    m=r["measurements"][0]
    assert Decimal(m["allocated_qty"])+Decimal(m["remaining_qty"])==Decimal(m["total_qty"])
