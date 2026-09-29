export type Status = 'NO_REORDER' | 'REORDER' | 'BLOCKED'
export interface Run {
  id: string
  batch_id: string
  status: string
  as_of: string
  horizon: number
  currency: string
  warehouse: string
  inventory_max_age_days: number
  commercial_max_age_days: number
  expected_sku_count: number
  processed_count: number
  reorder_count: number
  no_reorder_count: number
  blocked_count: number
  created_at: string
}
export type RunRequest = Pick<
  Run,
  | 'batch_id'
  | 'as_of'
  | 'horizon'
  | 'currency'
  | 'warehouse'
  | 'inventory_max_age_days'
  | 'commercial_max_age_days'
>
export interface SKU {
  sku_id: string
  description: string
  uom: string
  active: boolean
  safety_stock: number | null
  target_stock: number | null
}
export interface Supplier {
  supplier_id: string
  supplier_name: string
  approved: boolean | null
  currency: string | null
}
export interface Commercial {
  sku_id: string
  supplier_id: string | null
  approved_for_sku: boolean | null
  unit_price: string | null
  currency: string | null
  moq: number | null
  pack_multiple: number | null
  lead_time_days: number | null
  updated_at: string | null
}
export interface Inventory {
  sku_id: string
  on_hand: number | null
  snapshot_date: string | null
}
export interface Demand {
  sku_id: string
  quantity: number | null
  need_date: string | null
}
export interface Incoming {
  sku_id: string
  po_number: string
  quantity: number | null
  arrival_date: string | null
  status: string
}
export interface Context {
  sku: SKU
  suppliers: Supplier[]
  commercial: Commercial[]
  inventory: Inventory[]
  demand: Demand[]
  open_po: Incoming[]
}
export interface Check {
  id: string
  run_id: string
  sku_id: string
  status: Status
  revision: number
  context: Context
  on_hand: number | null
  valid_incoming: number | null
  demand_qty: number | null
  projected_stock: number | null
  raw_order_qty: number | null
  final_order_qty: number | null
  decision_reason: string
  evidence: {
    timeline?: {
      date: string
      valid_incoming: number
      demand_qty: number
      projected_stock: number
    }[]
    moq?: number
    pack_multiple?: number
    binding_date?: string
    need_date?: string
    expected_delivery_date?: string
    supplier_id?: string
  }
}
export interface ExceptionItem {
  id: string
  run_id: string
  result_id: string
  code: string
  severity: string
  message: string
  required_field: string
  required_action: string
  status: string
  created_at: string
  resolved_value: unknown
}
export interface Line {
  id: string
  result_id: string
  result_revision: number
  sku_id: string
  description: string
  uom: string
  quantity: number
  unit_price: string
  amount: string
  need_date: string
  expected_delivery_date: string
}
export interface Draft {
  id: string
  run_id: string
  po_number: string
  supplier_id: string
  supplier_name: string
  currency: string
  warehouse: string
  order_date: string
  status: string
  version: number
  total: string
  reviewer: string | null
  approved_at: string | null
  finance_reviewer: string | null
  finance_approved_at: string | null
  requires_finance_review: boolean
  approval_stage: 'PURCHASING' | 'FINANCE' | 'COMPLETE'
  lines: Line[]
}
export interface Batch {
  id: string
  filename: string
  status: string
  source_hash: string
  created_at: string
  raw_data: Record<string, Record<string, unknown>[]>
  issues: {
    code: string
    message: string
    table?: string
    row?: number
    field?: string
    original?: string
  }[]
}
export interface AuditEvent {
  id: string
  tool_name: string
  actor: string
  status: string
  input: unknown
  output: unknown
  error: string | null
  created_at: string
}
export interface ApprovalEvent {
  id: string
  action: string
  actor: string
  comment: string
  version: number
  created_at: string
  snapshot: unknown
}
export interface Report {
  run: Run
  drafts: Draft[]
  exceptions: ExceptionItem[]
  next_action: string
}
export interface AgentReply {
  message: string
  action: 'NONE' | 'RUN' | 'DRAFTS' | 'PRICE' | 'EXPLAIN' | 'BRIEF' | 'INSIGHTS' | 'NAVIGATE'
  page?: 'dashboard' | 'intelligence' | 'data' | 'skus' | 'exceptions' | 'drafts' | 'audit'
  sku_id?: string | null
  unit_price?: string | null
  provider: string
  tools_used?: string[]
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface DecisionMetrics {
  total_skus: number
  reorder: number
  no_reorder: number
  blocked: number
  decision_completion: number
  recommendation_value: string
  approved_value?: string
  approval_progress?: number
  supplier_count: number
  warning_count: number
  spend_by_supplier: { supplier_id: string; value: string }[]
}

export interface DecisionChange {
  sku_id: string
  before_status: string
  after_status: string
  before_qty: number | null
  after_qty: number | null
  reason: string
}

export interface Cockpit {
  run_id: string
  as_of: string
  currency: string
  metrics: DecisionMetrics
  comparison: {
    previous_run_id: string | null
    changes: DecisionChange[]
    summary: { status_changes?: number; quantity_changes?: number }
  }
}

export interface SimulationInput {
  horizon?: number
  demand_percent: number
  safety_stock_percent: number
  lead_time_delta_days: number
}

export interface Simulation {
  run_id: string
  inputs: SimulationInput
  baseline: DecisionMetrics
  scenario: DecisionMetrics
  changes: DecisionChange[]
  disclaimer: string
}
export type WorkspaceRole = 'owner' | 'procurement' | 'purchasing' | 'finance' | 'viewer'
export interface Workspace {
  id: string
  organization_id: string
  organization_name: string
  name: string
  business_entity: string
  warehouse: string
  currency: string
  finance_threshold: string
  role: WorkspaceRole | 'service'
}
export interface WorkspaceMember {
  id: string
  workspace_id: string
  user_id: string | null
  email: string
  display_name: string
  role: WorkspaceRole
  created_at: string
}
