REASONS={"BAD_COLUMNS":"列数不匹配","EMPTY_VALUE":"必填值为空","INVALID_NUMBER":"数字格式错误","INVALID_TIME":"时间缺少偏移或格式错误","DUPLICATE_CONFLICT":"同键取值冲突","UNKNOWN_REFERENCE":"引用不存在","STALE_VERSION":"版本已更新","EMPTY_FILE":"文件为空","HEADER_ONLY":"仅有表头","BLANK_ONLY":"全部为空行",
"BAD_ROW_TYPE":"未知记录类型","NEGATIVE_QTY":"用量为负","UNIT_MISMATCH":"计量单位不一致","IMAGE_HAS_QTY":"影像证据不得携带用量","ITEM_OUT_OF_SCOPE":"清单项超出测量记录覆盖范围","OVER_ALLOCATION":"分用量之和超出总测量量","INVALID_ALLOCATION":"分用量引用无效","NO_EVIDENCE":"缺少有效测量记录","COVERAGE_NOT_RECONCILED":"覆盖结论未对平"}
def reject(row, code, detail):
    return {**row,"reason":code,"detail":detail}
def sources(row):
    return row.get("_sources", [row.get("_line",0)])
