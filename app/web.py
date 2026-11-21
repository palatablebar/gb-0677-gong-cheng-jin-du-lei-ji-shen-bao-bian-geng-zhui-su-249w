from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        stage=run["stages"][index]
        rows=stage["rows"]
        columns=[['claim_id', 'item', 'period', 'cumulative_qty', 'previous_qty', 'change_id', 'reported'], ['claim_id', 'item', 'unit', 'cumulative_qty', 'previous_qty'], ['claim_id', 'period', 'approved_change', 'unit_price'], ['claim_id', 'period', 'cumulative_qty', 'approved_previous', 'increment_qty', 'gross_amount'], ['claim_id', 'item', 'gross_amount', 'retention', 'advance_recovery', 'expected'], ['claim_id', 'item', 'expected', 'reported', 'difference', 'status'], ['claim_id', 'period', 'expected', 'status']][index]
        labels={'claim_id': '申报编号', 'item': '清单项', 'period': '申报周期', 'cumulative_qty': '本次累计量', 'previous_qty': '前审累计量', 'change_id': '变更单', 'reported': '申报净额', 'unit': '单位', 'approved_change': '已批变更', 'unit_price': '单价 / 元', 'approved_previous': '修订前审量', 'increment_qty': '本期工程量', 'gross_amount': '本期总额', 'retention': '质保金', 'advance_recovery': '预付款扣回', 'expected': '实算净额', 'difference': '净额差异', 'status': '结论', 'gross_total': '本期总额合计', 'net_total': '实算净额合计'}
        for key,label in {'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'differences': '差异项', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'sha256': '校验摘要', 'ready': '可归档'}.items(): labels.setdefault(key,label)
        extra={}
        if index==6:
            from app.evidence import store as evidence_store
            batches=evidence_store.list_evidence()
            extra["coverage_evidence"]=evidence_store.get_evidence(batches[0]["evidence_id"]) if batches else None
            extra["active_certificate"]=evidence_store.active_certificate(run["run_id"])
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,columns=columns[:12],history=store.history(),labels=labels,**extra)
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
    def coverage_page():
        from flask import render_template,request
        from app.evidence import store as evidence_store
        batches=evidence_store.list_evidence()
        selected=request.args.get("evidence")
        if selected:
            current=evidence_store.get_evidence(selected)
        elif batches:
            current=evidence_store.get_evidence(batches[0]["evidence_id"])
        else:
            from app.evidence import service
            from app.config import ROOT
            current=service.execute((ROOT/"sample_data"/"shared_evidence.csv").read_bytes())
            batches=evidence_store.list_evidence()
        active_cert=None;cert_events=[]
        latest_run=store.latest()
        if latest_run:
            active_cert=evidence_store.active_certificate(latest_run["run_id"])
            cert_events=evidence_store.list_events(latest_run["run_id"])
        return render_template("coverage.html",title=TITLE,short=SHORT,modules=MODULES,index=-1,
                               evidence=current,batches=batches,active_cert=active_cert,
                               cert_events=cert_events,latest_run=latest_run)
    app.add_url_rule("/coverage",endpoint="page_coverage",view_func=coverage_page)
