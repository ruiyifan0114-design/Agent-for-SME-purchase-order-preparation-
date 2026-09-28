import { useMemo, useState } from 'react'
import { Copy, Plus, Save, Trash2 } from 'lucide-react'
import { Button, ErrorNotice, Field, Modal } from './components'

export const datasetTables = [
  'sku_master',
  'supplier_master',
  'supplier_sku',
  'inventory_snapshot',
  'demand',
  'open_po',
] as const

export type DatasetTable = (typeof datasetTables)[number]
export type DatasetRow = Record<string, string | number | boolean | null>
export type EditableDataset = Record<DatasetTable, DatasetRow[]>

type Kind = 'text' | 'number' | 'decimal' | 'date' | 'boolean' | 'status'
type FieldSpec = { key: string; label: string; kind: Kind; required?: boolean; hint?: string }
type TableSpec = { label: string; description: string; fields: FieldSpec[] }

const specs: Record<DatasetTable, TableSpec> = {
  sku_master: {
    label: 'Goods / SKUs',
    description: 'Products and their stock policy. Add every item the Agent should review.',
    fields: [
      { key: 'sku_id', label: 'SKU ID', kind: 'text', required: true },
      { key: 'description', label: 'Description', kind: 'text', required: true },
      { key: 'uom', label: 'Unit', kind: 'text', required: true, hint: 'pcs, box, kg…' },
      { key: 'active', label: 'Active', kind: 'boolean', required: true },
      { key: 'safety_stock', label: 'Safety stock', kind: 'number' },
      { key: 'target_stock', label: 'Target stock', kind: 'number' },
    ],
  },
  supplier_master: {
    label: 'Suppliers',
    description: 'Supplier identity, qualification status and commercial currency.',
    fields: [
      { key: 'supplier_id', label: 'Supplier ID', kind: 'text', required: true },
      { key: 'supplier_name', label: 'Supplier name', kind: 'text', required: true },
      { key: 'approved', label: 'Approved', kind: 'boolean' },
      { key: 'currency', label: 'Currency', kind: 'text', hint: 'SGD' },
    ],
  },
  supplier_sku: {
    label: 'Supplier terms',
    description: 'Map each SKU to its supplier, price, MOQ, pack size and lead time.',
    fields: [
      { key: 'sku_id', label: 'SKU ID', kind: 'text', required: true },
      { key: 'supplier_id', label: 'Supplier ID', kind: 'text' },
      { key: 'approved_for_sku', label: 'Approved for SKU', kind: 'boolean' },
      { key: 'unit_price', label: 'Unit price', kind: 'decimal' },
      { key: 'currency', label: 'Currency', kind: 'text' },
      { key: 'moq', label: 'MOQ', kind: 'number' },
      { key: 'pack_multiple', label: 'Pack multiple', kind: 'number' },
      { key: 'lead_time_days', label: 'Lead time (days)', kind: 'number' },
      { key: 'updated_at', label: 'Updated date', kind: 'date' },
    ],
  },
  inventory_snapshot: {
    label: 'Inventory',
    description: 'Current on-hand stock and the date on which it was counted.',
    fields: [
      { key: 'sku_id', label: 'SKU ID', kind: 'text', required: true },
      { key: 'on_hand', label: 'On hand', kind: 'number' },
      { key: 'snapshot_date', label: 'Snapshot date', kind: 'date' },
    ],
  },
  demand: {
    label: 'Demand',
    description: 'Required quantities and need dates. A SKU may have several demand rows.',
    fields: [
      { key: 'sku_id', label: 'SKU ID', kind: 'text', required: true },
      { key: 'quantity', label: 'Quantity', kind: 'number' },
      { key: 'need_date', label: 'Need date', kind: 'date' },
    ],
  },
  open_po: {
    label: 'Open POs',
    description: 'Incoming supply that may cover demand before its need date.',
    fields: [
      { key: 'sku_id', label: 'SKU ID', kind: 'text', required: true },
      { key: 'po_number', label: 'PO number', kind: 'text', required: true },
      { key: 'quantity', label: 'Quantity', kind: 'number' },
      { key: 'arrival_date', label: 'Arrival date', kind: 'date' },
      { key: 'status', label: 'Status', kind: 'status', required: true },
    ],
  },
}

export function emptyDataset(): EditableDataset {
  return {
    sku_master: [],
    supplier_master: [],
    supplier_sku: [],
    inventory_snapshot: [],
    demand: [],
    open_po: [],
  }
}

function normalize(source?: Record<string, Record<string, unknown>[]>) {
  const result = emptyDataset()
  for (const table of datasetTables) {
    const rows = source?.[table]
    result[table] = Array.isArray(rows)
      ? rows
          .filter((row) => row && typeof row === 'object')
          .map(
            (row) =>
              Object.fromEntries(
                specs[table].fields.map(({ key }) => [key, row[key] ?? null]),
              ) as DatasetRow,
          )
      : []
  }
  return result
}

function newRow(table: DatasetTable): DatasetRow {
  const row: DatasetRow = {}
  for (const field of specs[table].fields) row[field.key] = null
  if (table === 'sku_master') row.active = true
  if (table === 'open_po') row.status = 'OPEN'
  return row
}

function valueFor(kind: Kind, value: string): string | number | boolean | null {
  if (value === '') return null
  if (kind === 'boolean') return value === 'true'
  if (kind === 'number') return Number(value)
  return value
}

export default function DatasetEditor({
  source,
  sourceName,
  onClose,
  onSave,
}: {
  source?: Record<string, Record<string, unknown>[]>
  sourceName?: string
  onClose: () => void
  onSave: (dataset: EditableDataset, filename: string) => Promise<void>
}) {
  const [dataset, setDataset] = useState(() => normalize(source))
  const [table, setTable] = useState<DatasetTable>('sku_master')
  const [filename, setFilename] = useState(
    sourceName
      ? `${sourceName.replace(/\.[^.]+$/, '')}-edited.json`
      : 'manual-procurement-dataset.json',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const skuIds = useMemo(
    () => dataset.sku_master.map((row) => String(row.sku_id || '')).filter(Boolean),
    [dataset.sku_master],
  )
  const supplierIds = useMemo(
    () => dataset.supplier_master.map((row) => String(row.supplier_id || '')).filter(Boolean),
    [dataset.supplier_master],
  )
  const spec = specs[table]

  function update(rowIndex: number, field: FieldSpec, raw: string) {
    setDataset((current) => ({
      ...current,
      [table]: current[table].map((row, index) =>
        index === rowIndex ? { ...row, [field.key]: valueFor(field.kind, raw) } : row,
      ),
    }))
  }

  async function save() {
    if (!dataset.sku_master.length) {
      setError('Add at least one SKU before validating the dataset.')
      setTable('sku_master')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSave(dataset, filename.trim() || 'manual-procurement-dataset.json')
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Dataset validation failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Build procurement dataset"
      subtitle="Add or edit goods and related evidence. Saving creates a new auditable batch."
      onClose={busy ? () => {} : onClose}
      wide
    >
      <div className="modal-body dataset-editor">
        {error && <ErrorNotice message={error} />}
        <div className="dataset-editor-head">
          <Field label="Dataset name">
            <input
              value={filename}
              maxLength={255}
              onChange={(event) => setFilename(event.target.value)}
              aria-label="Dataset name"
            />
          </Field>
          <div className="dataset-summary" aria-label="Dataset record summary">
            {datasetTables.map((name) => (
              <span key={name}>
                <strong>{dataset[name].length}</strong> {specs[name].label}
              </span>
            ))}
          </div>
        </div>

        <div className="dataset-tabs" role="tablist" aria-label="Dataset tables">
          {datasetTables.map((name) => (
            <button
              key={name}
              role="tab"
              aria-selected={table === name}
              className={table === name ? 'active' : ''}
              onClick={() => setTable(name)}
            >
              {specs[name].label} <span>{dataset[name].length}</span>
            </button>
          ))}
        </div>

        <div className="dataset-table-title">
          <div>
            <h3>{spec.label}</h3>
            <p>{spec.description}</p>
          </div>
          <Button
            kind="secondary"
            onClick={() =>
              setDataset((current) => ({
                ...current,
                [table]: [...current[table], newRow(table)],
              }))
            }
          >
            <Plus size={15} /> Add record
          </Button>
        </div>

        {dataset[table].length ? (
          <div className="table-scroll dataset-grid-wrap">
            <table className="dataset-grid">
              <thead>
                <tr>
                  <th>#</th>
                  {spec.fields.map((field) => (
                    <th key={field.key}>
                      {field.label}
                      {field.required ? ' *' : ''}
                    </th>
                  ))}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {dataset[table].map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    <td>{rowIndex + 1}</td>
                    {spec.fields.map((field) => {
                      const value = row[field.key]
                      const list =
                        field.key === 'sku_id'
                          ? 'dataset-skus'
                          : field.key === 'supplier_id'
                            ? 'dataset-suppliers'
                            : undefined
                      return (
                        <td key={field.key}>
                          {field.kind === 'boolean' ? (
                            <select
                              aria-label={`${spec.label} row ${rowIndex + 1} ${field.label}`}
                              value={value == null ? '' : String(value)}
                              onChange={(event) => update(rowIndex, field, event.target.value)}
                            >
                              <option value="">Unknown</option>
                              <option value="true">Yes</option>
                              <option value="false">No</option>
                            </select>
                          ) : field.kind === 'status' ? (
                            <select
                              aria-label={`${spec.label} row ${rowIndex + 1} ${field.label}`}
                              value={String(value || 'OPEN')}
                              onChange={(event) => update(rowIndex, field, event.target.value)}
                            >
                              <option value="OPEN">Open</option>
                              <option value="CLOSED">Closed</option>
                              <option value="CANCELLED">Cancelled</option>
                            </select>
                          ) : (
                            <input
                              aria-label={`${spec.label} row ${rowIndex + 1} ${field.label}`}
                              type={
                                field.kind === 'date'
                                  ? 'date'
                                  : field.kind === 'number' || field.kind === 'decimal'
                                    ? 'number'
                                    : 'text'
                              }
                              min={
                                field.kind === 'number' || field.kind === 'decimal' ? 0 : undefined
                              }
                              step={
                                field.kind === 'decimal'
                                  ? '0.0001'
                                  : field.kind === 'number'
                                    ? '1'
                                    : undefined
                              }
                              list={list}
                              placeholder={field.hint}
                              value={value == null ? '' : String(value)}
                              onChange={(event) => update(rowIndex, field, event.target.value)}
                            />
                          )}
                        </td>
                      )
                    })}
                    <td>
                      <div className="dataset-row-actions">
                        <button
                          className="icon-button"
                          title="Duplicate record"
                          aria-label={`Duplicate ${spec.label} row ${rowIndex + 1}`}
                          onClick={() =>
                            setDataset((current) => ({
                              ...current,
                              [table]: [
                                ...current[table].slice(0, rowIndex + 1),
                                { ...row },
                                ...current[table].slice(rowIndex + 1),
                              ],
                            }))
                          }
                        >
                          <Copy size={15} />
                        </button>
                        <button
                          className="icon-button danger"
                          title="Delete record"
                          aria-label={`Delete ${spec.label} row ${rowIndex + 1}`}
                          onClick={() =>
                            setDataset((current) => ({
                              ...current,
                              [table]: current[table].filter((_, index) => index !== rowIndex),
                            }))
                          }
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <button
            className="dataset-empty"
            onClick={() => setDataset((current) => ({ ...current, [table]: [newRow(table)] }))}
          >
            <Plus size={19} /> Add the first {spec.label.toLowerCase()} record
          </button>
        )}

        <datalist id="dataset-skus">
          {skuIds.map((id) => (
            <option key={id} value={id} />
          ))}
        </datalist>
        <datalist id="dataset-suppliers">
          {supplierIds.map((id) => (
            <option key={id} value={id} />
          ))}
        </datalist>

        <div className="notice soft dataset-policy-note">
          Human approval remains mandatory. PO drafts below SGD 5,000 require Purchasing Manager
          approval; drafts at or above SGD 5,000 additionally require Finance Manager review.
        </div>
        <div className="modal-actions">
          <Button kind="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={busy}>
            <Save size={16} /> {busy ? 'Validating…' : 'Validate & create batch'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
