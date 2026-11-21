from decimal import Decimal
from app.reasons import reject
from app.values import scalar
from app.evidence.intake import UNIT_BY_ITEM

def _q(row):
    value=row.get("qty_dec",row.get("qty","0"))
    return Decimal(str(value))

def adjudicate(parsed):
    """把一份共享证据裁决为本期可复核的覆盖结论。

    守恒铁律：同一总测量记录、同一清单项下，各分用量之和不得超过该记录对该项的总测量量；
    一份记录可同时覆盖钢筋与混凝土（同 record_id 多条测量行）。
    未对平（超分/引用无效/无有效测量）的批次不得进入正式签证。
    """
    rows=parsed["rows"];quarantine=list(parsed["quarantine"])
    # record_id -> item -> 测量行
    measurement_map={};images=[];declarations=[];demands=[]
    for row in rows:
        rtype=row["row_type"]
        if rtype=="measurement": measurement_map.setdefault(row["record_id"],{})[row["item"]]=row
        elif rtype=="image": images.append(row)
        elif rtype=="declaration": declarations.append(row)
        else: demands.append(row)

    accepted=[];rejected=[]
    # 分用量按（总测量记录，清单项）归集，再做守恒判断
    allocations={}
    for row in declarations:
        ref=row["record_id"];item=row["item"]
        source=(measurement_map.get(ref) or {}).get(item)
        if ref not in measurement_map:
            entry=reject(row,"UNKNOWN_REFERENCE","申报引用的总测量记录不存在")
            rejected.append(entry);quarantine.append(entry);continue
        if source is None:
            entry=reject(row,"ITEM_OUT_OF_SCOPE","分用量项不在该测量记录覆盖范围内")
            rejected.append(entry);quarantine.append(entry);continue
        if row["unit"]!=source["unit"]:
            entry=reject(row,"UNIT_MISMATCH","分用量单位与总测量记录不一致")
            rejected.append(entry);quarantine.append(entry);continue
        accepted.append(row)
        allocations.setdefault((ref,item),[]).append(row)

    over=[];meas_records=[]
    for ref in sorted(measurement_map):
        for item,source in sorted(measurement_map[ref].items()):
            parts=allocations.get((ref,item),[])
            used=sum((_q(p) for p in parts),Decimal(0))
            total=_q(source)
            status="已覆盖" if used==total else ("部分覆盖" if used<total else "超分")
            record={"record_id":ref,"item":item,"unit":source["unit"],
                    "period":source.get("period",""),"total_qty":str(total),
                    "allocated_qty":str(used),"remaining_qty":str(total-used),
                    "part_count":len(parts),"source_lines":list(source["_sources"]),
                    "status":status}
            if status=="超分": over.append(record)
            meas_records.append(record)

    # 工程项维度的覆盖、需求缺口
    demand_by_item={}
    for d in demands: demand_by_item.setdefault(d["item"],Decimal(0))
    for d in demands: demand_by_item[d["item"]]+=_q(d)
    covered_by_item={}
    for row in accepted: covered_by_item.setdefault(row["item"],Decimal(0))
    for row in accepted: covered_by_item[row["item"]]+=_q(row)
    items=[]
    for item in sorted(set(list(covered_by_item)+list(demand_by_item))):
        covered=covered_by_item.get(item,Decimal(0));demand=demand_by_item.get(item,Decimal(0))
        gap=max(demand-covered,Decimal(0))
        if item not in demand_by_item: status="无需求申报"
        elif covered>=demand: status="已覆盖"
        else: status="覆盖缺口"
        items.append({"item":item,"unit":UNIT_BY_ITEM[item],"covered_qty":str(covered),
                      "demand_qty":str(demand),"gap_qty":str(gap),"status":status})

    unused=[{"record_id":r["record_id"],"item":r["item"],"unit":r["unit"],
             "total_qty":r["total_qty"],"source_lines":r["source_lines"]}
            for r in meas_records if Decimal(r["allocated_qty"])==0]
    unsupported=[{"record_id":i["record_id"],"kind":i.get("kind","image"),
                  "source_lines":list(i["_sources"])} for i in images]

    blocking=[]
    if not measurement_map: blocking.append({"code":"NO_EVIDENCE","detail":"无有效总测量记录"})
    if rejected: blocking.append({"code":"INVALID_ALLOCATION","detail":f"{len(rejected)} 条分用量引用无效"})
    if over: blocking.append({"code":"OVER_ALLOCATION","detail":f"{len(over)} 个测量分项的分用量之和超出总测量量"})
    reconciled=not blocking

    metrics={"measurement_records":len(meas_records),"measurement_documents":len(measurement_map),
             "image_evidence":len(images),"declarations":len(declarations),
             "accepted_allocations":len(accepted),"rejected_allocations":len(rejected),
             "quarantine_sources":len(quarantine),"over_allocated":len(over),
             "unused_sources":len(unused),"item_count":len(items),"reconciled":reconciled,
             "input":parsed["metrics"]["input"],
             "excluded":parsed["metrics"]["duplicate"]+parsed["metrics"]["blank"]+parsed["metrics"]["repeated_headers"]+len(quarantine),
             "blocking_reasons":[b["code"] for b in blocking]}
    result={"metrics":metrics,"blocking":blocking,"measurements":meas_records,
            "item_coverage":items,"allocations":_allocation_view(accepted),
            "unused_sources":unused,"unsupported_sources":unsupported,
            "quarantine":quarantine,"intake":parsed["metrics"]}
    return scalar(result)

def _allocation_view(accepted):
    view=[]
    for row in accepted:
        view.append({"record_id":row["record_id"],"item":row["item"],"period":row.get("period",""),
                     "qty":str(_q(row)),"unit":row["unit"],"source_lines":list(row["_sources"])})
    return sorted(view,key=lambda r:(r["record_id"],r["item"]))
