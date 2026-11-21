from flask import Blueprint,request,jsonify
from app.errors import DomainError
from app import store as run_store
from app.evidence import service,store as evidence_store

bp=Blueprint("evidence",__name__)
SAMPLES={"shared_evidence.csv","over_allocation.csv"}

def _load_sample(name):
    if name not in SAMPLES: raise DomainError("BAD_SAMPLE","样例不存在",404)
    from app.config import ROOT
    return (ROOT/"sample_data"/name).read_bytes()

@bp.route("/api/coverage",methods=["GET","POST"])
def coverage():
    if request.method=="GET":
        return jsonify({"batches":evidence_store.list_evidence()})
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise DomainError("BAD_BODY","请求需要对象")
    raw=payload.get("csv")
    if raw is not None and not isinstance(raw,str): raise DomainError("BAD_CSV","CSV需要文本")
    data=raw.encode() if raw is not None else _load_sample(payload.get("sample","shared_evidence.csv"))
    return jsonify(service.execute(data))

@bp.post("/api/coverage/upload")
def coverage_upload():
    file=request.files.get("file")
    if not file: raise DomainError("NO_FILE","请选择CSV文件")
    return jsonify(service.execute(file.read()))

@bp.get("/api/coverage/<evidence_id>")
def coverage_detail(evidence_id):
    return jsonify(evidence_store.get_evidence(evidence_id))

@bp.get("/api/coverage/<evidence_id>/raw")
def coverage_raw(evidence_id):
    from flask import Response
    return Response(evidence_store.get_raw_evidence(evidence_id),mimetype="text/csv")

@bp.get("/api/coverage/<evidence_id>/archive")
def coverage_archive(evidence_id):
    evidence=evidence_store.get_evidence(evidence_id)
    return jsonify({"csv":service.export_evidence(evidence)})

@bp.post("/api/runs/<run_id>/certificate/publish")
def publish_certificate(run_id):
    payload=request.get_json(silent=True) or {}
    evidence_id=payload.get("evidence_id")
    if not isinstance(evidence_id,str) or not evidence_id:
        raise DomainError("BAD_EVIDENCE","请提供证据批次ID")
    run=run_store.get(run_id)
    evidence=evidence_store.get_evidence(evidence_id)
    # 发布门：未对平直接 422，不写任何签证记录
    service.gate(evidence)
    return jsonify(service.publish(run,evidence))

@bp.get("/api/runs/<run_id>/certificate")
def certificate_status(run_id):
    run_store.get(run_id)  # run 不存在返回 404
    return jsonify({"active":evidence_store.active_certificate(run_id),
                    "history":evidence_store.certificate_history(run_id),
                    "events":evidence_store.list_events(run_id)})
