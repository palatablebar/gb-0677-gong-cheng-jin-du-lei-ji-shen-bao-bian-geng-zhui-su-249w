import csv,io
from app.config import ROOT

def _sample(name): return (ROOT/"sample_data"/name).read_bytes()

def test_coverage_api_runs_sample(client):
    r=client.post("/api/coverage",json={"sample":"shared_evidence.csv"})
    assert r.status_code==200
    body=r.get_json()
    assert body["metrics"]["measurement_records"]==4
    assert body["metrics"]["measurement_documents"]==3
    assert body["metrics"]["reconciled"] is False

def test_coverage_api_idempotent(client):
    a=client.post("/api/coverage",json={"sample":"over_allocation.csv"}).get_json()
    b=client.post("/api/coverage",json={"sample":"over_allocation.csv"}).get_json()
    assert a["evidence_id"]==b["evidence_id"]
    assert len(client.get("/api/coverage").get_json()["batches"])==1

def test_coverage_upload_and_detail(client):
    r=client.post("/api/coverage/upload",
                  data={"file":(io.BytesIO(_sample("shared_evidence.csv")),"e.csv")},
                  content_type="multipart/form-data")
    assert r.status_code==200
    eid=r.get_json()["evidence_id"]
    assert client.get(f"/api/coverage/{eid}").status_code==200
    assert client.get("/api/coverage/missing").status_code==404

def test_raw_evidence_endpoint_returns_original(client):
    eid=client.post("/api/coverage",json={"sample":"shared_evidence.csv"}).get_json()["evidence_id"]
    text=client.get(f"/api/coverage/{eid}/raw").data.decode()
    assert text.startswith("row_type,record_id,item,period,qty,unit,kind,note")

def test_coverage_archive_sections(client):
    eid=client.post("/api/coverage",json={"sample":"shared_evidence.csv"}).get_json()["evidence_id"]
    rows=list(csv.reader(io.StringIO(client.get(f"/api/coverage/{eid}/archive").get_json()["csv"])))
    sections={r[3] for r in rows[1:]}
    assert {"measurement","allocation","item_coverage","unsupported","quarantine"}<=sections

def test_publish_gate_over_http(client):
    run_id=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()["run_id"]
    bad=client.post("/api/coverage",json={"sample":"over_allocation.csv"}).get_json()
    r=client.post(f"/api/runs/{run_id}/certificate/publish",json={"evidence_id":bad["evidence_id"]})
    assert r.status_code==422 and r.get_json()["code"]=="COVERAGE_NOT_RECONCILED"
    assert client.get(f"/api/runs/{run_id}/certificate").get_json()["active"] is None

def test_publish_and_status_over_http(client):
    run_id=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()["run_id"]
    good=("row_type,record_id,item,period,qty,unit,kind,note\n"
          "measurement,M-1,钢筋,2026-11,100,t,,合测\n"
          "declaration,M-1,钢筋,2026-11,100,t,,全领\n"
          "demand,D-1,钢筋,2026-11,100,t,,需求\n").encode()
    eid=client.post("/api/coverage",json={"csv":good.decode()}).get_json()["evidence_id"]
    first=client.post(f"/api/runs/{run_id}/certificate/publish",json={"evidence_id":eid})
    assert first.status_code==200 and first.get_json()["version"]==1
    # 同证据重发不新增版本
    assert client.post(f"/api/runs/{run_id}/certificate/publish",json={"evidence_id":eid}).get_json()["version"]==1
    status=client.get(f"/api/runs/{run_id}/certificate").get_json()
    assert status["active"]["covered_items"][0]["covered_qty"]=="100"
    assert any(e["event"]=="PUBLISHED" for e in status["events"])

def test_publish_unknown_run_or_evidence(client):
    assert client.post("/api/runs/nope/certificate/publish",json={"evidence_id":"x"}).status_code==404
    run_id=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()["run_id"]
    assert client.post(f"/api/runs/{run_id}/certificate/publish",json={"evidence_id":"nope"}).status_code==404
    assert client.post(f"/api/runs/{run_id}/certificate/publish",json={}).status_code==422

def test_coverage_page_renders(client):
    assert client.get("/coverage").status_code==200
    assert client.get("/certificates").status_code==200

def test_coverage_page_batch_selector(client):
    first=client.post("/api/coverage",json={"sample":"shared_evidence.csv"}).get_json()
    second=client.post("/api/coverage",json={"sample":"over_allocation.csv"}).get_json()
    page=client.get(f"/coverage?evidence={second['evidence_id']}").data.decode()
    assert second["evidence_id"] in page and "历史证据批次" in page
    assert client.get("/coverage?evidence=missing").status_code==404
