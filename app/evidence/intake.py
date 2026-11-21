import csv,io,hashlib
from app.errors import DomainError
from app.reasons import reject
from app.values import number
from app.modules.m2_billitems.rules import ITEMS

EVIDENCE_COLUMNS=["row_type","record_id","item","period","qty","unit","kind","note"]
ROW_TYPES={"measurement","image","declaration","demand"}
# 统一后的清单项 -> 计量单位（与 M2 清单映射一致）
UNIT_BY_ITEM={"001":"t","002":"m³"}
EVIDENCE_RULE_VERSION="2026.11.21-ev1"

def decode(raw):
    for encoding in ("utf-8-sig","gb18030"):
        try: return raw.decode(encoding),encoding
        except UnicodeDecodeError: continue
    raise DomainError("ENCODING","无法识别文件编码")

def canonical_item(code):
    item=ITEMS.get((code or "").strip())
    if item is None: raise DomainError("UNKNOWN_ITEM","清单项未登记")
    return item

def evidence_id(raw):
    # 与主流水线同思路：同源同参（证据域无参数）重跑得到同一批次
    return hashlib.sha256(raw+EVIDENCE_RULE_VERSION.encode()).hexdigest()[:20]

def parse(raw):
    """解析共享证据申报 CSV，保留每个物理来源行，不静默丢弃。"""
    text,encoding=decode(raw)
    if not text: raise DomainError("EMPTY_FILE","文件为空")
    if not text.strip(): raise DomainError("BLANK_ONLY","全部为空行")
    stream=csv.reader(io.StringIO(text,newline=""))
    header=next(stream,None)
    if header!=EVIDENCE_COLUMNS: raise DomainError("BAD_HEADER","证据表头不匹配")
    rows=[];bad=[];seen={};duplicate=blank=repeated=count=0
    try:
        for cells in stream:
            count+=1;line=stream.line_num
            if not cells or not any(c.strip() for c in cells): blank+=1;continue
            if cells==header: repeated+=1;continue
            row={"_line":line,"_sources":[line],"_raw":cells}
            if len(cells)!=len(header):
                bad.append(reject(row,"BAD_COLUMNS","列数不匹配"));continue
            row.update(dict(zip(header,[x.strip() for x in cells])))
            rtype=row["row_type"]
            if rtype not in ROW_TYPES:
                bad.append(reject(row,"BAD_ROW_TYPE","未知记录类型"));continue
            if not row["record_id"]:
                bad.append(reject(row,"EMPTY_VALUE","记录标识为空"));continue
            # 图片证据无用量，数量与单位必须留空；其余行必须带量
            if rtype=="image":
                if row["qty"].strip() or row["unit"].strip():
                    bad.append(reject(row,"IMAGE_HAS_QTY","影像证据不得携带用量"));continue
            else:
                try: qty=number(row["qty"])
                except DomainError as e: bad.append(reject(row,e.code,e.message));continue
                if qty<0:
                    bad.append(reject(row,"NEGATIVE_QTY","用量不能为负"));continue
                if not row["unit"].strip():
                    bad.append(reject(row,"EMPTY_VALUE","计量单位为空"));continue
                row["qty_dec"]=qty
            # 涉及清单项的行，归一化项编码与单位
            if rtype in {"measurement","declaration","demand"}:
                try:
                    item=canonical_item(row["item"]);row["item"]=item
                except DomainError as e:
                    bad.append(reject(row,e.code,e.message));continue
                if row["unit"].strip() and row["unit"]!=UNIT_BY_ITEM[item]:
                    bad.append(reject(row,"UNIT_MISMATCH","计量单位与清单项不一致"));continue
            # 测量记录按 记录+清单项 唯一（同一记录可覆盖多个清单项）；
            # 影像与需求按类型+标识唯一；分用量申报天然允许同一测量记录多条拆分，不做唯一约束
            if rtype in {"measurement","image","demand"}:
                key=(rtype,row["record_id"],row.get("item","")) if rtype=="measurement" else (rtype,row["record_id"])
                if key in seen:
                    previous=seen[key]
                    if cells==previous["_raw"]: duplicate+=1
                    else: bad.append(reject(row,"DUPLICATE_CONFLICT","同类型同标识取值冲突"))
                    continue
                seen[key]=row
            rows.append(row)
    except csv.Error: raise DomainError("BAD_CSV","引号未闭合或文件损坏")
    if count==0: raise DomainError("HEADER_ONLY","仅有表头")
    if not rows and not bad: raise DomainError("BLANK_ONLY","全部为空行")
    metrics={"input":count,"accepted":len(rows),"quarantine":len(bad),
             "duplicate":duplicate,"blank":blank,"repeated_headers":repeated,"encoding":encoding}
    return {"rows":rows,"quarantine":bad,"metrics":metrics}
