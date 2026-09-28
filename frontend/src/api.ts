import type {
  AgentReply,
  ChatTurn,
  ApprovalEvent,
  AuditEvent,
  Batch,
  Check,
  Cockpit,
  Context,
  Credentials,
  Draft,
  ExceptionItem,
  Report,
  Run,
  RunRequest,
  Simulation,
  SimulationInput,
} from './types'

let credentials: Credentials = { service: '', reviewer: '', finance: '' }
const backendOrigin = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
export function setCredentials(value: Credentials) {
  credentials = value
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  human: boolean | 'finance' = false,
): Promise<T> {
  if (!backendOrigin && location.hostname.endsWith('.github.io')) {
    throw new ApiError(
      0,
      'DEPLOYMENT_NOT_CONFIGURED',
      'The cloud backend is not configured yet. Set the GitHub repository variable VITE_API_BASE_URL to the HTTPS backend address and redeploy.',
    )
  }
  const headers = new Headers(options.headers)
  headers.set(
    'X-API-Key',
    human === 'finance' ? credentials.finance : human ? credentials.reviewer : credentials.service,
  )
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(`${backendOrigin}/api/v1${path}`, {
      ...options,
      headers,
      signal: AbortSignal.timeout(90000),
    })
  } catch {
    throw new ApiError(
      0,
      'CONNECTION_ERROR',
      'Could not reach the backend. Check the connection and refresh; the operation may have completed on the server.',
    )
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.error
    throw new ApiError(
      response.status,
      detail?.code || 'REQUEST_FAILED',
      detail?.message
        ? `${detail.message}${detail.details ? ': ' + detail.details.map((d: { message: string }) => d.message).join('; ') : ''}`
        : `Request failed (${response.status}). No success has been confirmed.`,
    )
  }
  if (response.headers.get('content-type')?.includes('text/csv'))
    return (await response.blob()) as T
  return (await response.json()).data as T
}
const post = <T>(path: string, body?: unknown, human: boolean | 'finance' = false) =>
  request<T>(
    path,
    { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) },
    human,
  )
export const api = {
  runs: () => request<Run[]>('/runs?limit=100'),
  batches: () => request<Batch[]>('/imports?limit=100'),
  run: (id: string) => request<Run>(`/runs/${id}`),
  results: (id: string) => request<Check[]>(`/runs/${id}/results`),
  exceptions: (id: string) => request<ExceptionItem[]>(`/runs/${id}/exceptions`),
  drafts: (id: string) => request<Draft[]>(`/runs/${id}/drafts`),
  cockpit: (id: string) => request<Cockpit>(`/runs/${id}/cockpit`),
  simulate: (id: string, input: SimulationInput) => post<Simulation>(`/runs/${id}/simulate`, input),
  history: (id: string) => request<ApprovalEvent[]>(`/drafts/${id}/history`),
  audit: (offset = 0) => request<AuditEvent[]>(`/audit?limit=50&offset=${offset}`),
  importJson: (data: unknown, filename = 'dataset.json') =>
    post<Batch>(`/imports?filename=${encodeURIComponent(filename)}`, data),
  upload: (files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<Batch>('/imports/upload', { method: 'POST', body: form })
  },
  demo: (scenario: string) =>
    request<{ dataset: unknown; policy: Omit<RunRequest, 'batch_id'> }>(`/demo/${scenario}`),
  review: (policy: RunRequest) => post<Report>('/agent/review', policy),
  resume: (id: string) => post<Report>(`/agent/runs/${id}/resume`),
  resolve: (id: string, revision: number, context: Context, reason: string) =>
    post<Check>(
      `/exceptions/${id}/resolve`,
      { expected_revision: revision, context, reason },
      true,
    ),
  correct: (run: string, sku: string, revision: number, context: Context, reason: string) =>
    request<{ result: Check }>(
      `/runs/${run}/skus/${sku}/context`,
      { method: 'PATCH', body: JSON.stringify({ expected_revision: revision, context, reason }) },
      true,
    ),
  edit: (draft: Draft, line: string, quantity: number, unit_price: string, reason: string) =>
    request<Draft>(
      `/drafts/${draft.id}/lines/${line}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ expected_version: draft.version, quantity, unit_price, reason }),
      },
      true,
    ),
  approve: (draft: Draft, comment: string) =>
    post<Draft>(
      `/drafts/${draft.id}/approve`,
      { expected_version: draft.version, comment, confirm: true },
      true,
    ),
  reject: (draft: Draft, comment: string, finance = false) =>
    post<Draft>(
      `/drafts/${draft.id}/reject`,
      { expected_version: draft.version, comment, confirm: true },
      finance ? 'finance' : true,
    ),
  financeApprove: (draft: Draft, comment: string) =>
    request<Draft>(
      `/drafts/${draft.id}/finance-approve`,
      {
        method: 'POST',
        body: JSON.stringify({ expected_version: draft.version, comment, confirm: true }),
      },
      'finance',
    ),
  export: (id: string) => request<Blob>(`/drafts/${id}/export`),
  message: (message: string, run_id?: string, sku_id?: string, history: ChatTurn[] = []) =>
    post<AgentReply>('/agent/message', {
      message,
      run_id: run_id || null,
      sku_id: sku_id || null,
      history: history.slice(-10),
    }),
}
