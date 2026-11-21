import csv,io,hashlib
from app.errors import DomainError
from app.values import scalar
from app.evidence.intake import parse,evidence_id,EVIDENCE_RULE_VERSION,EVIDENCE_COLUMNS
from app.evidence.coverage import adjudicate
from app.evidence import store

def execute(raw):
    parsed=parse(raw)
    conclusion=adjudicate(parsed)
    batch_id=evidence_id(raw)
    conclusion["evidence_id"]=batch_id
    conclusion["manifest"]={"input_sha256":hashlib.sha256(raw).hexdigest(),
                            "rule_version":EVIDENCE_RULE_VERSION,
                            "columns":EVIDENCE_COLUMNS,
                            "encoding":parsed["metrics"]["encoding"]}
    # 按检测出的编码原样留存（utf-8-sig 同时去 BOM），GB18030 文件不会被破坏
    raw_text=raw.decode(parsed["metrics"]["encoding"])
    return store.save_evidence(batch_id,conclusion,raw_text,
                               conclusion["manifest"]["input_sha256"],EVIDENCE_RULE_VERSION)

def gate(evidence):
    """签证发布门：未对平的覆盖结论不能进入正式签证。"""
    if not evidence["metrics"]["reconciled"]:
        codes=",".join(evidence["metrics"]["blocking_reasons"])
        raise DomainError("COVERAGE_NOT_RECONCILED",f"覆盖结论未对平（{codes}），不能发布正式签证",422)

def certificate_payload(run,evidence):
    """正式签证只携带已覆盖量；缺口作为未覆盖部分列明，不并入签证。"""
    gate(evidence)
    covered=[{"item":i["item"],"unit":i["unit"],"covered_qty":i["covered_qty"]}
             for i in evidence["item_coverage"]]
    gaps=[{"item":i["item"],"unit":i["unit"],"gap_qty":i["gap_qty"]}
          for i in evidence["item_coverage"] if i["status"]=="覆盖缺口"]
    return {"run_id":run["run_id"],"evidence_id":evidence["evidence_id"],
            "covered_items":covered,"gaps":gaps,
            "input_sha256":evidence["manifest"]["input_sha256"],
            "rule_version":EVIDENCE_RULE_VERSION,"decision":run.get("decision")}

def publish(run,evidence,before_publish=None):
    payload=certificate_payload(run,evidence)
    return store.publish_certificate(run["run_id"],evidence["evidence_id"],payload,before_publish)

def export_evidence(evidence):
    """证据导出：覆盖、缺口、未采信来源各自分列，全部可回到物理来源行。"""
    stream=io.StringIO(newline="");w=csv.writer(stream)
    meta=evidence["manifest"]
    w.writerow(["evidence_id","input_sha256","rule_version","section","record_id",
                "item","qty","unit","status","source_lines","reason","detail"])
    for m in evidence["measurements"]:
        w.writerow([evidence["evidence_id"],meta["input_sha256"],meta["rule_version"],
                    "measurement",m["record_id"],m["item"],m["allocated_qty"],m["unit"],
                    m["status"],m["source_lines"],"",""])
    for a in evidence["allocations"]:
        w.writerow([evidence["evidence_id"],meta["input_sha256"],meta["rule_version"],
                    "allocation",a["record_id"],a["item"],a["qty"],a["unit"],
                    "已采信",a["source_lines"],"",""])
    for i in evidence["item_coverage"]:
        w.writerow([evidence["evidence_id"],meta["input_sha256"],meta["rule_version"],
                    "item_coverage","",i["item"],i["covered_qty"],i["unit"],
                    i["status"],[],"",f"需求 {i['demand_qty']} / 缺口 {i['gap_qty']}"])
    for u in evidence["unused_sources"]:
        w.writerow([evidence["evidence_id"],meta["input_sha256"],meta["rule_version"],
                    "unused",u["record_id"],u["item"],u["total_qty"],u["unit"],
                    "未使用来源",u["source_lines"],"",""])
    for u in evidence["unsupported_sources"]:
        w.writerow([evidence["evidence_id"],meta["input_sha256"],meta["rule_version"],
                    "unsupported",u["record_id"],"","","",
                    u["kind"],u["source_lines"],"","影像/申报材料无用量，不构成覆盖"])
    for q in evidence["quarantine"]:
        w.writerow([evidence["evidence_id"],meta["input_sha256"],meta["rule_version"],
                    "quarantine",q.get("record_id",""),q.get("item",""),
                    q.get("qty",""),q.get("unit",""),"未采信",q.get("_sources",[]),
                    q.get("reason",""),q.get("detail","")])
    return "﻿"+stream.getvalue()
