# SME Procurement Agent

前后端已完成联调：提供采购概览、数据导入、SKU 检查、异常修正、采购单审批、审计页面和 Agent 面板。详见 [前端启动与演示](frontend/README.md) 和 [开发状态](docs/DEVELOPMENT_STATUS.md)。

基于 `biz module` 的采购 Agent MVP：导入合成数据 → 校验 → 全量 SKU 检查 → 异常修正和重算 → 按供应商生成草稿 → 人工审批 → CSV 导出。业务状态和审计保存在 PostgreSQL。

## 快速启动

Docker Compose（需 Docker 引擎已启动）：

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec api python -m backend.demo --date 2026-09-27
```

前端页面 `http://localhost:8000`；交互文档 `http://localhost:8000/docs`。Docker 镜像同时构建前端。
Compose 等待数据库健康、执行迁移后启动 API，数据库使用持久卷。

本地 Python 3.12+、uv 和 PostgreSQL：

```powershell
uv sync --locked
Copy-Item .env.example .env
# 在 .env 设置 PostgreSQL DATABASE_URL
uv run alembic upgrade head
uv run python -m backend.demo --date 2026-09-27
uv run uvicorn backend.main:app --reload
```

本地开发前端另开终端，在 `frontend` 目录执行 `npm ci`、`npm run dev`，访问 `http://127.0.0.1:5173`。若希望由后端统一提供页面，先执行 `npm run build`，再启动后端，访问 8000 端口。

本次已创建项目 `.venv`。当前终端没有 python 命令时，也可直接执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

`/health` 检查进程，`/ready` 检查数据库与迁移表。正式 schema 由 Alembic 管理，应用不自动建表。

## 凭证与人工审批

所有 `/api/v1` 接口要求 `X-API-Key`，开发默认值见 `.env.example`。

| 身份 | 配置 | 能力 |
| --- | --- | --- |
| 服务 / Agent | `API_KEY` | 导入、检查、草稿、查询、导出已审批单据 |
| 人工审核人 | `REVIEWER_API_KEY` | 以上能力 + 修正异常/来源、修改数量/价格、审批/拒绝 |

两种 Key 必须不同。审核人身份来自服务端 `REVIEWER_NAME`，不接受任意请求姓名。审批要求 `confirm: true` 和当前 `expected_version`。Agent 没有自动审批路径。这是单审核人 MVP 鉴权；外部部署应更换默认 Key 并接入团队身份系统和 HTTPS。

## 演示

`demo/` 提供六个 CSV、同内容的 `dataset.json` 和本次 PostgreSQL 实测 `run-report.json`。固定输入日期为 **2026-09-27**；报告中的 ID 只对应本次演示运行。

商品名称/UOM 与 SUP-A/B/C 复用业务模板；所有数值都是合成示例，币种使用测试标识 **XTS**，不代表实际公司币种。金额为税前金额。

```powershell
# 按今天生成新 CSV/JSON，不写数据库
uv run python -m backend.demo --write-files demo-local
# 导入并运行，故意保留商业/库存异常
uv run python -m backend.demo
# 无故意设置的异常
uv run python -m backend.demo --clean
```

演示预期：10 SKU / 3 供应商；`REORDER=6`、`NO_REORDER=1`、`BLOCKED=3`。CLI 不会批准采购单。

## 前端最短调用链

1. `POST /api/v1/imports`，body 为 `demo/dataset.json`；或 `/imports/upload` 上传 CSV/Excel。
2. 检查批次 `status` 为 `VALIDATED` 或 `VALIDATED_WITH_ISSUES`。结构错误保存为 `REJECTED`，不能继续运行。
3. `POST /api/v1/agent/review`，使用下方显式参数；返回摘要、草稿和异常。
4. 人工修正异常后自动重算对应 SKU；调用 Agent resume 同步草稿。
5. 人工审核草稿，使用审核人 Key 调用 approve，之后 export 下载 CSV。

```json
{
  "batch_id": "替换为导入返回的 id",
  "as_of": "2026-09-27",
  "horizon": 14,
  "currency": "XTS",
  "warehouse": "SYNTHETIC-WH-1",
  "inventory_max_age_days": 1,
  "commercial_max_age_days": 30
}
```

上述参数是明确的合成演示配置。实际运行必须显式传入，系统没有替团队决定实际币种或数据时效阈值。审批 body：

```json
{
  "expected_version": 3,
  "confirm": true,
  "comment": "人工已检查数量、价格和交期风险"
}
```

使用刚读取的草稿 `version`，不可固定使用示例值。数量/价格、默认供应商或来源重算都会使相关采购单回到 `NEEDS_REVIEW`，清除当前审批信息，保留历史。

## 输入契约

每批必须包含六张表；无需求或无在途也要提供空表/数组，不能把缺失文件误当成零需求。

| 表 / CSV 文件名 / Excel sheet | 字段 |
| --- | --- |
| `sku_master` | sku_id, description, uom, active, safety_stock, target_stock |
| `supplier_master` | supplier_id, supplier_name, approved, currency |
| `supplier_sku` | sku_id, supplier_id, approved_for_sku, unit_price, currency, moq, pack_multiple, lead_time_days, updated_at |
| `inventory_snapshot` | sku_id, on_hand, snapshot_date |
| `demand` | sku_id, quantity, need_date |
| `open_po` | sku_id, po_number, quantity, arrival_date, status |

multipart 字段为 `files`：六个 UTF-8 CSV，或者包含六个同名 sheet 的 `.xlsx`。支持原始模板文件名 `supplier_master_template.csv`、`sku_supplier_map_template.csv` 和列别名 `sku`、`default_supplier_id`、映射表的 `approved`。description/UOM 由 SKU 主表提供。业务设计工作簿是规范文件，不是六张交易表的上传文件。

日期为 `YYYY-MM-DD`，数量为非负整数，价格最多四位小数；行金额四舍五入到两位后求和。上传最多 10 MiB，每表最多 50,000 行。占位文本、NaN、非法数字规范化为 null，并记录原值/位置，需要该值的 SKU 进入 BLOCKED。主表重复 ID、未知 SKU、缺表或结构错误使批次 REJECTED。重复库存保留，检查时产生 DUPLICATE/CONFLICTING_INVENTORY。

open_po.quantity 是未收货的剩余数量，demand 是未履行需求。过去到货日期的 OPEN PO 需要人工确认；CLOSED/CANCELLED 不计入在途。

## 库存规则

运行截止 `as_of + horizon`，含截止日。按需求日期和截止日计算累计在途、累计需求；过去未履行需求仍计入。

```text
projected(day) = on_hand + incoming(arrival <= day) - demand(need <= day)
binding = projected 最低的日期
若 binding.projected < safety_stock：
  raw = target_stock - binding.projected
  final = ceil(max(raw, moq) / pack_multiple) * pack_multiple
否则 NO_REORDER
```

结果的 projected_stock / valid_incoming / demand_qty 对应 binding 日期，`evidence.timeline` 保存各日期计算。晚到订单不能掩盖早期缺货，到货等于需求日时可计入。UAT 示例 raw=36/MOQ=50/pack=10 → 50，raw=63 → 70。

MOQ 和 pack 必须显式提供，不适用时分别填 0、1。`LATE_OPEN_PO`、`LEAD_TIME_RISK` 为人工可见警告；缺少库存、价格、默认映射、供应商批准或数据过期为阻塞。

## 分层与状态

```text
backend/
  api/       REST、身份边界、请求响应
  agent/     唯一 ProcurementAgent，按存储状态选择下一步
  skills/    五个业务工作流
  tools/     原子动作、事务、审计
  domain/    Pydantic、导入规范化、确定性计算
  models/    14 张 SQLAlchemy 表
  db/        PostgreSQL session
migrations/  Alembic 固定版本迁移
tests/       域规则、UAT、HTTP、PostgreSQL 并发测试
```

Agent 为可恢复的确定性工作流 Agent，不依赖 LLM/key。可在后续增加自然语言入口，但数量、日期、金额、审批状态仍由 domain/tools 决定。

运行创建时冻结来源上下文，后续导入不修改旧运行。采购单行引用结果及 revision；历史评估保存在日志中。人工来源修正仅作用于指定运行/SKU，不改写原始导入。失败先回滚，再独立记录 FAILED；数据库完全不可用时返回错误和服务日志，不报假成功。

每个 run 的写操作使用 PostgreSQL 行锁；run+supplier 唯一约束、每结果唯一 PO 行与版本检查防止重复草稿和过期审批。重复 `/check` 只处理未完成 SKU，显式 `/rerun` 才重算并使相关审批失效。

接口详情见 [docs/api.md](docs/api.md)，业务映射见 [docs/business-decisions.md](docs/business-decisions.md)。正常 JSON 为 `{"data": ...}`，错误为 `{"error": {"code": ..., "message": ...}}`；CSV 为文件响应。

## 测试

```powershell
uv run pytest -q
uv run ruff check backend tests migrations
# 先创建独立、可清空的 procurement_test 数据库
$env:TEST_DATABASE_URL = 'postgresql+psycopg://procurement:procurement@localhost:5432/procurement_test'
uv run pytest -q
uv run alembic check
```

测试库名必须以 `_test` 结尾；测试创建/删除其中的测试表。SQLite 仅为快速测试替身，默认跳过 PostgreSQL 行锁并发用例。

本次 PostgreSQL 16.15 完整测试、迁移 upgrade/downgrade/upgrade、`alembic check` 和合成数据运行均通过。Docker 配置提供 PostgreSQL 17，但本机 Docker 引擎未就绪，镜像构建未实测。上游 TestClient 有弃用提醒，不影响当前测试结果。

范围：单仓、单币种、默认供应商；不连接真实 ERP、不联系供应商、不发送订单。草稿落库是内部工作状态，最终订单只有审批后才可导出。不同 run 是独立评审，导出不会自动变成下一批的 open PO，下次导入应包含已确认的剩余在途订单。
