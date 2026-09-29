import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { AlertCircle, ArrowUpRight, Check, ChevronRight, Loader2, X } from 'lucide-react'
import type { Check as Result } from './types'

const labels: Record<string, string> = {
  NO_REORDER: 'No reorder',
  REORDER: 'Reorder',
  BLOCKED: 'Blocked',
  NEEDS_ATTENTION: 'Needs attention',
  COMPLETED: 'Check complete',
  CREATED: 'Not checked',
  RUNNING: 'Checking',
  DRAFT: 'Draft',
  NEEDS_REVIEW: 'Needs review',
  FINANCE_REVIEW: 'Finance review',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  VALIDATED: 'Validated',
  VALIDATED_WITH_ISSUES: 'Validation warnings',
  OPEN: 'Open',
  RESOLVED: 'Resolved',
  SUPERSEDED: 'Superseded',
  WARNING: 'Timing warning',
  BLOCKING: 'Blocking',
  SUCCESS: 'Confirmed',
  FAILED: 'Failed',
}
export function Badge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status.toLowerCase()}`}>
      <span className="status-dot" />
      {labels[status] || status}
    </span>
  )
}
export function shortId(id?: string) {
  return id ? id.slice(0, 8).toUpperCase() : '—'
}
export function dateTime(value?: string | null) {
  return value
    ? new Date(value).toLocaleString('en-GB', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'
}
export function money(value: string) {
  const [whole, part = ''] = value.split('.')
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${part.padEnd(2, '0')}`
}
export function number(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString()
}
export function Button({
  children,
  onClick,
  kind = 'primary',
  disabled = false,
  type = 'button',
  className = '',
}: {
  children: ReactNode
  onClick?: () => void
  kind?: 'primary' | 'secondary' | 'ghost' | 'danger'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      className={`button ${kind} ${className}`}
      onClick={onClick}
    >
      {children}
    </button>
  )
}
export function Empty({
  title,
  children,
  action,
}: {
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Check size={26} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  )
}
export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="notice error" role="alert">
      <AlertCircle size={20} />
      <div>
        <strong>Action needs attention</strong>
        <p>{message}</p>
      </div>
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  )
}
export function Loading({ text = 'Loading the latest stored state…' }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <Loader2 className="spin" size={20} />
      {text}
    </div>
  )
}
export function SectionTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="section-title">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  )
}
export function PanelHead({
  title,
  note,
  action,
}: {
  title: string
  note?: string
  action?: ReactNode
}) {
  return (
    <div className="panel-head">
      <div>
        <h2>{title}</h2>
        {note && <p>{note}</p>}
      </div>
      {action}
    </div>
  )
}
export function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
  className = '',
}: {
  title: string
  subtitle?: string
  children: ReactNode
  onClose: () => void
  wide?: boolean
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    ref.current?.focus()
    function key(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab') {
        const nodes = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
        )
        if (!nodes?.length) return
        const first = nodes[0],
          last = nodes[nodes.length - 1]
        if (
          e.shiftKey &&
          (document.activeElement === first || document.activeElement === ref.current)
        ) {
          e.preventDefault()
          last.focus()
        } else if (
          !e.shiftKey &&
          (document.activeElement === last || document.activeElement === ref.current)
        ) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', key)
    return () => {
      document.body.style.overflow = oldOverflow
      document.removeEventListener('keydown', key)
      previous?.focus()
    }
  }, [onClose])
  return (
    <div
      className="modal-shade"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={`modal ${wide ? 'wide' : ''} ${className}`}
      >
        <header>
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button className="icon-button" aria-label="Close dialog" onClick={onClose}>
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  )
}
export function Evidence({ result }: { result: Result }) {
  return (
    <div className="evidence">
      <div className="evidence-top">
        <div>
          <span className="eyebrow">
            {result.sku_id} · {result.context.sku.uom}
          </span>
          <h3>{result.context.sku.description}</h3>
        </div>
        <Badge status={result.status} />
      </div>
      <div className="reason-card">
        <span className="eyebrow">Decision from procurement engine</span>
        <p>{result.decision_reason}</p>
      </div>
      <div className="evidence-stats">
        {[
          ['On hand', result.on_hand],
          ['Valid incoming', result.valid_incoming],
          ['Demand', result.demand_qty],
          ['Projected stock', result.projected_stock],
          ['Raw requirement', result.raw_order_qty],
          ['Final recommendation', result.final_order_qty],
        ].map(([l, v]) => (
          <div key={l}>
            <span>{l}</span>
            <strong>{number(v as number | null)}</strong>
          </div>
        ))}
      </div>
      <h4>Dated stock evidence</h4>
      <p className="muted">
        Only incoming stock on or before each need date is counted. Binding date:{' '}
        {result.evidence.binding_date || 'Not yet calculable'}.
      </p>
      {result.evidence.timeline?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Incoming</th>
                <th>Demand</th>
                <th>Projected</th>
              </tr>
            </thead>
            <tbody>
              {result.evidence.timeline.map((t) => (
                <tr key={t.date}>
                  <td>{t.date}</td>
                  <td>{t.valid_incoming}</td>
                  <td>{t.demand_qty}</td>
                  <td>{t.projected_stock}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">
          Required input is missing or conflicting. Resolve the blocking exception first.
        </p>
      )}
      <h4>Source records</h4>
      <div className="source-grid">
        <div>
          <strong>Inventory snapshot</strong>
          {result.context.inventory.map((i, n) => (
            <p key={n}>
              {i.snapshot_date || 'Date missing'} · {number(i.on_hand)} on hand
            </p>
          ))}
          {!result.context.inventory.length && <p>No inventory supplied</p>}
        </div>
        <div>
          <strong>Open purchase orders</strong>
          {result.context.open_po.map((p, n) => (
            <p key={n}>
              {p.po_number} · {number(p.quantity)} · {p.arrival_date || 'Date missing'} · {p.status}
            </p>
          ))}
          {!result.context.open_po.length && <p>No open PO records</p>}
        </div>
        <div>
          <strong>Commercial rules</strong>
          {result.context.commercial.map((c, n) => (
            <p key={n}>
              {c.supplier_id || 'No supplier'} · price {c.unit_price ?? 'missing'} {c.currency} ·
              MOQ {number(c.moq)} · pack {number(c.pack_multiple)} · lead {number(c.lead_time_days)}{' '}
              days
            </p>
          ))}
        </div>
        <div>
          <strong>Stock policy</strong>
          <p>
            Safety {number(result.context.sku.safety_stock)} · target{' '}
            {number(result.context.sku.target_stock)}
          </p>
        </div>
      </div>
      <div className="reference">
        <ArrowUpRight size={15} />
        <span>
          Decision {result.id} · revision {result.revision}
        </span>
      </div>
    </div>
  )
}
export function TextLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button className="text-link" onClick={onClick}>
      {children}
      <ChevronRight size={15} />
    </button>
  )
}
