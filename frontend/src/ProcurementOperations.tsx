import { useState } from 'react'
import { api } from './api'
import type { Draft } from './types'

/** Human-entered events only; all quantity and matching calculations run on the backend. */
export default function ProcurementOperations({ draft, refresh }: { draft: Draft; refresh: () => void }) {
  const [operation, setOperation] = useState('receipt')
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  const status = draft.lifecycle_status || 'DRAFT'
  const savedRate = Number(draft.exchange_rate)
  const defaultRate = Number.isFinite(savedRate) && savedRate > 0 ? String(draft.exchange_rate) : '1'
  const canReceive = ['SENT', 'DELAYED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'RETURNED'].includes(status)
  return <details className="procurement-operations">
    <summary>Receiving & procurement records</summary>
    <p className="muted">Record actions completed by your team. Marking a PO sent does not contact the supplier.</p>
    <form onSubmit={async event => {
      event.preventDefault()
      const values = new FormData(event.currentTarget)
      const value = (key: string) => String(values.get(key) || '')
      setPending(true); setMessage(''); setFailed(false)
      try {
        if (operation === 'matrix') {
          const result = await api.matrixApprove(draft, value('reason'), value('role') === 'finance')
          setMessage(`Matrix step recorded: ${result.approved_step.required_role}. Complete any remaining steps before final PO approval.`)
        } else if (operation === 'lifecycle') {
          await api.lifecycle(draft.id, value('status'), value('reason'))
          setMessage('PO status updated.')
        } else if (operation === 'receipt') {
          await api.receipt(draft.id, {
            external_id: value('reference'), received_at: new Date(value('date') + 'T12:00:00Z').toISOString(),
            lines: [{ po_line_id: value('line'), quantity: Number(value('quantity')),
              rejected_quantity: Number(value('rejected')), returned_quantity: Number(value('returned')) }],
          })
          setMessage('Goods receipt saved. Quantities and PO status have been recalculated.')
        } else {
          const line = draft.lines.find(item => item.id === value('line'))!
          const result = await api.invoice(draft.id, {
            supplier_id: draft.supplier_id, invoice_number: value('reference'), invoice_date: value('date'),
            currency: draft.currency, exchange_rate: value('fx'), exchange_rate_date: value('fxDate'),
            exchange_rate_source: value('fxSource'),
            lines: [{ po_line_id: line.id, sku_id: line.sku_id,
              quantity: Number(value('quantity')), unit_price: value('price') }],
          })
          setMessage(result.status === 'MATCHED' ? 'Invoice saved: three-way match passed.' :
            'Invoice saved with matching exceptions: ' + [...new Set(result.matches.flatMap(match =>
              match.trace.result.exceptions))].map(code => code.replaceAll('_', ' ').toLowerCase()).join(', ') + '.')
        }
        refresh()
      } catch (error) {
        setFailed(true); setMessage(error instanceof Error ? error.message : 'Unable to save record.')
      } finally { setPending(false) }
    }}>
      <fieldset disabled={pending}>
        <div className="procurement-operation-fields">
          <label>Record type<select value={operation} onChange={event => { setOperation(event.target.value); setMessage('') }}>
            <option value="receipt">Goods receipt / return</option>
            <option value="invoice">Supplier invoice (one line)</option>
            <option value="lifecycle">PO status</option>
            <option value="matrix">Approval matrix step</option>
          </select></label>
          {operation === 'matrix' ? <>
            <label>Review comment<input name="reason" required minLength={3} maxLength={2000} /></label>
            <label>Reviewer connection<select name="role"><option value="purchasing">Purchasing</option><option value="finance">Finance</option></select></label>
            <label><input type="checkbox" required /> I reviewed this PO and explicitly approve the next matrix step.</label>
            <button className="button secondary" type="button" onClick={async () => {
              try {
                const plan = await api.approvalPlan(draft.id)
                setFailed(false)
                setMessage(plan.result.steps.length ? 'Required approval sequence: ' + plan.result.steps.map(step =>
                  step.required_role === step.acting_role ? step.required_role : `${step.required_role} (delegated to ${step.acting_role})`).join(' → ') : 'This run has no additional approval-matrix steps.')
              } catch (error) { setFailed(true); setMessage(error instanceof Error ? error.message : 'Unable to load approval plan.') }
            }}>View approval requirements</button>
          </> : operation === 'lifecycle' ? <>
            <label>New status<select name="status" required>
              {status === 'DRAFT' && draft.status === 'APPROVED' && <option value="SENT">Sent manually</option>}
              {['SENT', 'PARTIALLY_RECEIVED'].includes(status) && <option value="DELAYED">Delayed</option>}
              {['DRAFT', 'SENT', 'PARTIALLY_RECEIVED', 'DELAYED'].includes(status) && <option value="CANCELLED">Cancelled</option>}
            </select></label>
            <label>Reason<input name="reason" required maxLength={2000} /></label>
          </> : <>
            <label>Document reference<input name="reference" required maxLength={100} /></label>
            <label>Document date<input name="date" type="date" required /></label>
            <label>PO line<select name="line" required>{draft.lines.map(line =>
              <option key={line.id} value={line.id}>{line.sku_id} · {line.open_quantity ?? line.quantity} open</option>)}</select></label>
            <label>{operation === 'receipt' ? 'Delivered quantity' : 'Invoice quantity'}<input name="quantity" type="number" min={operation === 'receipt' ? 0 : 1} step="1" required /></label>
            {operation === 'receipt' ? <>
              <label>Rejected quantity<input name="rejected" type="number" min="0" step="1" defaultValue="0" required /></label>
              <label>Returned quantity<input name="returned" type="number" min="0" step="1" defaultValue="0" required /></label>
            </> : <>
              <label>Invoice unit price ({draft.currency})<input name="price" type="number" min="0.0001" step="0.0001" required /></label>
              <label>Recorded FX rate<input name="fx" type="number" min="0.00000001" step="0.00000001" defaultValue={defaultRate} required /></label>
              <label>FX date<input name="fxDate" type="date" defaultValue={draft.exchange_rate_date || ''} required /></label>
              <label>FX source<input name="fxSource" defaultValue={draft.exchange_rate_source || ''} required maxLength={100} /></label>
            </>}
          </>}
        </div>
        {operation === 'receipt' && !canReceive && <p>Mark the approved PO as sent before recording receipt.</p>}
        <button className="button secondary" type="submit" disabled={
          !draft.lines.length || (operation === 'receipt' && !canReceive) ||
          (operation === 'lifecycle' && ['RECEIVED', 'RETURNED', 'CANCELLED'].includes(status))
        }>{pending ? 'Saving…' : 'Save record'}</button>
      </fieldset>
    </form>
    {message && <p role={failed ? 'alert' : 'status'}>{message}</p>}
  </details>
}
