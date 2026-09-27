import { useState } from 'react'
import type { FormEvent } from 'react'
import { AlertTriangle, Check, Loader2, Plus, Trash2 } from 'lucide-react'
import { Badge, Button, ErrorNotice, Field, money, Modal, shortId } from './components'
import type {
  Batch,
  Check as Result,
  Context,
  Credentials,
  Draft,
  ExceptionItem,
  Line,
  RunRequest,
} from './types'

function useSubmit(action: () => Promise<void>) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  return {
    busy,
    error,
    submit: async (e: FormEvent) => {
      e.preventDefault()
      setBusy(true)
      setError('')
      try {
        await action()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Operation failed')
      } finally {
        setBusy(false)
      }
    },
  }
}
export function RunForm({
  batches,
  initial,
  onSubmit,
  onClose,
}: {
  batches: Batch[]
  initial?: Partial<RunRequest>
  onSubmit: (r: RunRequest) => Promise<void>
  onClose: () => void
}) {
  const valid = batches.filter((b) => b.status.startsWith('VALIDATED'))
  const [value, setValue] = useState<RunRequest>({
    batch_id: valid[0]?.id || '',
    as_of: new Date().toLocaleDateString('en-CA'),
    horizon: 14,
    currency: '',
    warehouse: '',
    inventory_max_age_days: 1,
    commercial_max_age_days: 30,
    ...initial,
  })
  const state = useSubmit(() => onSubmit(value))
  const change = (key: keyof RunRequest, v: string | number) =>
    setValue((prev) => ({ ...prev, [key]: v }))
  return (
    <Modal
      title="Run daily procurement check"
      subtitle="Confirm the input batch and stock-review policy."
      onClose={state.busy ? () => {} : onClose}
    >
      <form onSubmit={state.submit} className="modal-body">
        <div className="notice soft">
          <Check size={18} />
          <p>
            All active SKUs will be checked. Valid lines become drafts; blocked items remain
            visible. No orders are approved automatically.
          </p>
        </div>
        <Field label="Input batch">
          <select
            required
            value={value.batch_id}
            onChange={(e) => change('batch_id', e.target.value)}
          >
            {valid.map((b) => (
              <option key={b.id} value={b.id}>
                {b.filename} · {shortId(b.id)}
              </option>
            ))}
          </select>
        </Field>
        <div className="form-grid">
          <Field label="Review date">
            <input
              required
              type="date"
              value={value.as_of}
              onChange={(e) => change('as_of', e.target.value)}
            />
          </Field>
          <Field label="Horizon (days)">
            <input
              required
              type="number"
              min={1}
              max={365}
              value={value.horizon}
              onChange={(e) => change('horizon', Number(e.target.value))}
            />
          </Field>
          <Field label="Currency" hint="Must match the supplier data. XTS is synthetic.">
            <input
              required
              pattern="[A-Z]{3}"
              maxLength={3}
              placeholder="e.g. XTS"
              value={value.currency}
              onChange={(e) => change('currency', e.target.value.toUpperCase())}
            />
          </Field>
          <Field label="Warehouse">
            <input
              required
              maxLength={100}
              placeholder="Ship-to / warehouse"
              value={value.warehouse}
              onChange={(e) => change('warehouse', e.target.value)}
            />
          </Field>
          <Field label="Inventory max age (days)">
            <input
              required
              type="number"
              min={0}
              max={3650}
              value={value.inventory_max_age_days}
              onChange={(e) => change('inventory_max_age_days', Number(e.target.value))}
            />
          </Field>
          <Field label="Commercial max age (days)">
            <input
              required
              type="number"
              min={0}
              max={3650}
              value={value.commercial_max_age_days}
              onChange={(e) => change('commercial_max_age_days', Number(e.target.value))}
            />
          </Field>
        </div>
        <p className="muted">
          The thresholds above are configurable review policy, not assumed company rules.
        </p>
        {state.error && <ErrorNotice message={state.error} />}
        <div className="modal-actions">
          <Button kind="secondary" onClick={onClose} disabled={state.busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={state.busy || !valid.length}>
            {state.busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}{' '}
            {state.busy ? 'Checking all SKUs…' : 'Start check'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

type Column = {
  key: string
  label: string
  type?: 'number' | 'price' | 'date' | 'boolean' | 'status'
}
const sections: { key: Exclude<keyof Context, 'sku'>; label: string; cols: Column[] }[] = [
  {
    key: 'inventory',
    label: 'Inventory snapshots',
    cols: [
      { key: 'on_hand', label: 'On hand', type: 'number' },
      { key: 'snapshot_date', label: 'Snapshot date', type: 'date' },
    ],
  },
  {
    key: 'commercial',
    label: 'Default supplier mapping',
    cols: [
      { key: 'supplier_id', label: 'Supplier ID' },
      { key: 'approved_for_sku', label: 'Approved for SKU', type: 'boolean' },
      { key: 'unit_price', label: 'Unit price', type: 'price' },
      { key: 'currency', label: 'Currency' },
      { key: 'moq', label: 'MOQ', type: 'number' },
      { key: 'pack_multiple', label: 'Pack multiple', type: 'number' },
      { key: 'lead_time_days', label: 'Lead time (days)', type: 'number' },
      { key: 'updated_at', label: 'Commercial updated date', type: 'date' },
    ],
  },
  {
    key: 'suppliers',
    label: 'Supplier master',
    cols: [
      { key: 'supplier_id', label: 'Supplier ID' },
      { key: 'supplier_name', label: 'Supplier name' },
      { key: 'approved', label: 'Supplier approved', type: 'boolean' },
      { key: 'currency', label: 'Currency' },
    ],
  },
  {
    key: 'demand',
    label: 'Unfulfilled demand',
    cols: [
      { key: 'quantity', label: 'Demand quantity', type: 'number' },
      { key: 'need_date', label: 'Need date', type: 'date' },
    ],
  },
  {
    key: 'open_po',
    label: 'Open purchase orders',
    cols: [
      { key: 'po_number', label: 'PO number' },
      { key: 'quantity', label: 'Remaining quantity', type: 'number' },
      { key: 'arrival_date', label: 'Arrival date', type: 'date' },
      { key: 'status', label: 'PO status', type: 'status' },
    ],
  },
]
export function CorrectionForm({
  result,
  exception,
  price,
  onSave,
  onClose,
}: {
  result: Result
  exception?: ExceptionItem
  price?: string
  onSave: (context: Context, reason: string) => Promise<void>
  onClose: () => void
}) {
  const [context, setContext] = useState<Context>(() => {
    const c = structuredClone(result.context)
    if (price && c.commercial[0]) c.commercial[0].unit_price = price
    return c
  })
  const [reason, setReason] = useState('')
  const state = useSubmit(() => onSave(context, reason))
  const focus = exception?.required_field.split('.')[0]
  function update(
    key: Exclude<keyof Context, 'sku'>,
    index: number,
    field: string,
    value: unknown,
  ) {
    setContext((old) => {
      const copy = structuredClone(old)
      ;(copy[key] as unknown as Record<string, unknown>[])[index][field] = value
      return copy
    })
  }
  function add(key: Exclude<keyof Context, 'sku'>) {
    setContext((old) => {
      const copy = structuredClone(old)
      const row: Record<string, unknown> = { sku_id: result.sku_id }
      sections
        .find((s) => s.key === key)!
        .cols.forEach((c) => {
          row[c.key] = c.type === 'boolean' ? false : c.type === 'status' ? 'OPEN' : null
        })
      if (key === 'suppliers') delete row.sku_id
      ;(copy[key] as unknown as Record<string, unknown>[]).push(row)
      return copy
    })
  }
  function remove(key: Exclude<keyof Context, 'sku'>, index: number) {
    if (
      window.confirm(
        'Remove this source row from the proposed correction? Changes are applied only when you save.',
      )
    )
      setContext((old) => ({ ...old, [key]: old[key].filter((_, i) => i !== index) }))
  }
  return (
    <Modal
      title={exception ? 'Resolve exception' : 'Correct source evidence'}
      subtitle={`${result.sku_id} · ${result.context.sku.description} · revision ${result.revision}`}
      wide
      onClose={state.busy ? () => {} : onClose}
    >
      <form className="modal-body" onSubmit={state.submit}>
        {exception && (
          <div className="notice warning">
            <AlertTriangle size={19} />
            <div>
              <strong>{exception.code}</strong>
              <p>{exception.message}</p>
              <small>Required field: {exception.required_field}</small>
            </div>
          </div>
        )}
        <p className="muted">
          Correct the source records below. Saving reruns this SKU and invalidates any previous
          approval on affected drafts.
        </p>
        {sections.map((section) => (
          <details
            key={section.key}
            open={focus === section.key || (!exception && section.key === 'commercial')}
            className="source-section"
          >
            <summary>
              {section.label}
              <span>{context[section.key].length} records</span>
            </summary>
            {(context[section.key] as unknown as Record<string, unknown>[]).map((row, index) => (
              <div className="source-row" key={index}>
                <div className="form-grid">
                  {section.cols.map((col) => (
                    <Field key={col.key} label={col.label}>
                      {col.type === 'boolean' ? (
                        <select
                          value={row[col.key] === null ? '' : String(row[col.key])}
                          onChange={(e) =>
                            update(
                              section.key,
                              index,
                              col.key,
                              e.target.value === '' ? null : e.target.value === 'true',
                            )
                          }
                        >
                          <option value="">Not confirmed</option>
                          <option value="true">Yes — approved</option>
                          <option value="false">No</option>
                        </select>
                      ) : col.type === 'status' ? (
                        <select
                          value={String(row[col.key] || 'OPEN')}
                          onChange={(e) => update(section.key, index, col.key, e.target.value)}
                        >
                          {['OPEN', 'CLOSED', 'CANCELLED'].map((v) => (
                            <option key={v}>{v}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={
                            col.type === 'number' ? 'number' : col.type === 'date' ? 'date' : 'text'
                          }
                          inputMode={col.type === 'price' ? 'decimal' : undefined}
                          min={0}
                          step={1}
                          value={row[col.key] == null ? '' : String(row[col.key])}
                          placeholder="Missing value"
                          onChange={(e) =>
                            update(
                              section.key,
                              index,
                              col.key,
                              e.target.value === ''
                                ? null
                                : col.type === 'number'
                                  ? Number(e.target.value)
                                  : col.key === 'currency'
                                    ? e.target.value.toUpperCase()
                                    : e.target.value,
                            )
                          }
                        />
                      )}
                    </Field>
                  ))}
                </div>
                <button
                  type="button"
                  className="remove-row"
                  onClick={() => remove(section.key, index)}
                >
                  <Trash2 size={14} />
                  Remove row
                </button>
              </div>
            ))}
            <button type="button" className="text-link add-row" onClick={() => add(section.key)}>
              <Plus size={15} />
              Add {section.label.toLowerCase()} record
            </button>
          </details>
        ))}
        <details open={focus === 'sku'} className="source-section">
          <summary>Stock policy</summary>
          <div className="form-grid source-row">
            {(['safety_stock', 'target_stock'] as const).map((key) => (
              <Field key={key} label={key === 'safety_stock' ? 'Safety stock' : 'Target stock'}>
                <input
                  type="number"
                  min={0}
                  value={context.sku[key] ?? ''}
                  onChange={(e) =>
                    setContext((old) => ({
                      ...old,
                      sku: {
                        ...old.sku,
                        [key]: e.target.value === '' ? null : Number(e.target.value),
                      },
                    }))
                  }
                />
              </Field>
            ))}
          </div>
        </details>
        <Field label="Reason for correction">
          <textarea
            required
            minLength={3}
            maxLength={2000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="What was confirmed or corrected?"
          />
        </Field>
        {state.error && <ErrorNotice message={state.error} />}
        <div className="modal-actions">
          <Button kind="secondary" onClick={onClose} disabled={state.busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={state.busy}>
            {state.busy && <Loader2 className="spin" size={16} />}Save & recheck SKU
          </Button>
        </div>
      </form>
    </Modal>
  )
}
export function EditLineForm({
  draft,
  line,
  onSave,
  onClose,
}: {
  draft: Draft
  line: Line
  onSave: (q: number, p: string, r: string) => Promise<void>
  onClose: () => void
}) {
  const [quantity, setQuantity] = useState(line.quantity),
    [price, setPrice] = useState(line.unit_price),
    [reason, setReason] = useState('')
  const state = useSubmit(() => onSave(quantity, price, reason))
  return (
    <Modal
      title="Edit purchase order line"
      subtitle={`${line.sku_id} · ${line.description}`}
      onClose={state.busy ? () => {} : onClose}
    >
      <form className="modal-body" onSubmit={state.submit}>
        <div className="notice warning">
          <AlertTriangle size={18} />
          <p>
            Changing quantity or price resets this PO to Needs review. The backend will validate
            MOQ, pack size and recalculate the totals.
          </p>
        </div>
        <div className="form-grid">
          <Field label="Order quantity">
            <input
              required
              type="number"
              min={1}
              step={1}
              value={quantity}
              onChange={(e) => setQuantity(Number(e.target.value))}
            />
          </Field>
          <Field label={`Unit price (${draft.currency})`}>
            <input
              required
              inputMode="decimal"
              pattern="[0-9]+(\.[0-9]{1,4})?"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Reason for edit">
          <textarea
            required
            minLength={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        {state.error && <ErrorNotice message={state.error} />}
        <div className="modal-actions">
          <Button kind="secondary" onClick={onClose} disabled={state.busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={state.busy}>
            Save & require review
          </Button>
        </div>
      </form>
    </Modal>
  )
}
export function ReviewForm({
  draft,
  reject,
  onSave,
  onClose,
}: {
  draft: Draft
  reject: boolean
  onSave: (comment: string) => Promise<void>
  onClose: () => void
}) {
  const [comment, setComment] = useState(''),
    [confirmed, setConfirmed] = useState(false)
  const state = useSubmit(() => onSave(comment))
  return (
    <Modal
      title={reject ? 'Reject this purchase order?' : 'Approve this purchase order?'}
      subtitle={`${draft.supplier_name} · PO-${shortId(draft.id)}`}
      onClose={state.busy ? () => {} : onClose}
    >
      <form className="modal-body" onSubmit={state.submit}>
        <div className="review-total">
          <span>
            {draft.lines.length} lines · pre-tax · {draft.currency}
          </span>
          <strong>{money(draft.total)}</strong>
          <Badge status={draft.status} />
        </div>
        <Field label="Review comment">
          <textarea
            required
            maxLength={2000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Record your review and any timing considerations."
          />
        </Field>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            {reject
              ? 'I confirm that this draft should be rejected.'
              : 'I have reviewed the source evidence, quantities, prices and timing warnings. I explicitly approve this version.'}
          </span>
        </label>
        {state.error && <ErrorNotice message={state.error} />}
        <div className="modal-actions">
          <Button kind="secondary" onClick={onClose} disabled={state.busy}>
            Keep as is
          </Button>
          <Button
            kind={reject ? 'danger' : 'primary'}
            type="submit"
            disabled={!confirmed || state.busy}
          >
            {state.busy && <Loader2 className="spin" size={16} />}Confirm{' '}
            {reject ? 'rejection' : 'approval'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
export function ConnectionForm({
  value,
  onSave,
  onClose,
}: {
  value: Credentials
  onSave: (v: Credentials) => void
  onClose: () => void
}) {
  const [form, setForm] = useState(value)
  return (
    <Modal
      title="Workspace connection"
      subtitle="Backend access credentials for this browser tab."
      onClose={onClose}
    >
      <form
        className="modal-body"
        onSubmit={(e) => {
          e.preventDefault()
          onSave(form)
        }}
      >
        <Field label="Service access key">
          <input
            required
            type="password"
            autoComplete="off"
            value={form.service}
            onChange={(e) => setForm({ ...form, service: e.target.value })}
          />
        </Field>
        <Field label="Human reviewer access key">
          <input
            required
            type="password"
            autoComplete="off"
            value={form.reviewer}
            onChange={(e) => setForm({ ...form, reviewer: e.target.value })}
          />
        </Field>
        <p className="muted">
          Use the workspace credentials from your backend configuration. Your DeepSeek provider key
          stays on the server and does not belong in these fields. Access keys are kept in this
          tab’s session only.
        </p>
        <div className="modal-actions">
          <Button kind="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">Save connection</Button>
        </div>
      </form>
    </Modal>
  )
}
