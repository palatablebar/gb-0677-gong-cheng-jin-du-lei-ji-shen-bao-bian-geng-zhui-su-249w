# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 共享证据覆盖（M8）

| 方法与路径 | 说明 |
|---|---|
| `POST /api/coverage` | 提交证据 CSV（`csv` 文本或 `sample`），裁决覆盖并落库；同源重跑返回同一批次，不新增覆盖 |
| `POST /api/coverage/upload` | multipart 上传证据文件（字段 `file`） |
| `GET /api/coverage` | 历史证据批次列表 |
| `GET /api/coverage/<evidence_id>` | 覆盖结论详情（测量分项、分用量、工程项覆盖、缺口、未采信来源、阻断原因） |
| `GET /api/coverage/<evidence_id>/raw` | 原始证据原样取回，按原编码留存，不参与任何改写 |
| `GET /api/coverage/<evidence_id>/archive` | 覆盖证据导出（measurement/allocation/item_coverage/unused/unsupported/quarantine 分段） |
| `POST /api/runs/<run_id>/certificate/publish` | 发布正式签证；未对平返回 422 `COVERAGE_NOT_RECONCILED`；同证据重发幂等，换证据则旧版 superseded、新版 active |
| `GET /api/runs/<run_id>/certificate` | 当前有效签证、历史版本与发布/失败事件 |

发布门只放行 `metrics.reconciled=true` 的结论；签证载荷仅含已覆盖量，缺口在 `gaps` 单列、不进入签证。发布在单事务内完成旧版置失效与新版生效，任一步失败整体回滚并保留旧版。
