import { useEffect, useState, type FormEvent } from 'react'
import { Building2, Check, Pencil, Plus, Trash2, Users } from 'lucide-react'

import { api } from './api'
import { Button } from './components'
import type { Workspace, WorkspaceMember, WorkspaceRole } from './types'

const emptyWorkspace = {
  organization_name: '',
  name: '',
  business_entity: '',
  warehouse: '',
  currency: 'SGD',
  finance_threshold: '5000',
}

export function WorkspaceManager({
  workspaces,
  active,
  onSelect,
  onReload,
}: {
  workspaces: Workspace[]
  active: Workspace | null
  onSelect: (id: string) => void
  onReload: (selectId?: string) => Promise<void>
}) {
  const [create, setCreate] = useState(!workspaces.length)
  const [editing, setEditing] = useState(false)
  const [deleting, setDeleting] = useState<Workspace | null>(null)
  const [form, setForm] = useState(emptyWorkspace)
  const [edit, setEdit] = useState<Workspace | null>(active)
  const [members, setMembers] = useState<WorkspaceMember[]>([])
  const [invite, setInvite] = useState({ email: '', display_name: '', role: 'viewer' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function loadMembers(workspace = active) {
    if (!workspace || workspace.role !== 'owner') return setMembers([])
    try {
      setMembers(await api.members(workspace.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load members')
    }
  }

  useEffect(() => {
    setEdit(active)
    void loadMembers(active)
  }, [active?.id])
  useEffect(() => {
    if (!workspaces.length) {
      setCreate(true)
      setEditing(false)
      setDeleting(null)
    }
  }, [workspaces.length])

  function select(workspace: Workspace) {
    setCreate(false)
    setEditing(false)
    setDeleting(null)
    onSelect(workspace.id)
  }
  function beginEdit(workspace: Workspace) {
    setCreate(false)
    setDeleting(null)
    setEdit(workspace)
    setEditing(true)
    onSelect(workspace.id)
  }
  function beginDelete(workspace: Workspace) {
    setCreate(false)
    setEditing(false)
    setDeleting(workspace)
    onSelect(workspace.id)
  }

  async function submitWorkspace(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const created = await api.createWorkspace(form)
      setCreate(false)
      setForm(emptyWorkspace)
      await onReload(created.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to create workspace')
    } finally {
      setBusy(false)
    }
  }

  async function saveWorkspace(event: FormEvent) {
    event.preventDefault()
    if (!edit) return
    setBusy(true)
    setError('')
    try {
      await api.updateWorkspace(edit)
      setEditing(false)
      await onReload(edit.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to update workspace')
    } finally {
      setBusy(false)
    }
  }

  async function deleteWorkspace() {
    if (!deleting) return
    setBusy(true)
    setError('')
    try {
      await api.deleteWorkspace(deleting.id)
      setDeleting(null)
      await onReload()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to delete workspace')
    } finally {
      setBusy(false)
    }
  }

  async function addMember(event: FormEvent) {
    event.preventDefault()
    if (!active) return
    setBusy(true)
    setError('')
    try {
      await api.inviteMember(active.id, invite)
      setInvite({ email: '', display_name: '', role: 'viewer' })
      await loadMembers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to add member')
    } finally {
      setBusy(false)
    }
  }

  async function changeRole(member: WorkspaceMember, role: WorkspaceRole) {
    if (!active) return
    setBusy(true)
    setError('')
    try {
      await api.updateMember(active.id, member.id, role)
      await loadMembers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to update member')
    } finally {
      setBusy(false)
    }
  }

  async function remove(member: WorkspaceMember) {
    if (!active) return
    setBusy(true)
    setError('')
    try {
      await api.removeMember(active.id, member.id)
      await loadMembers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to remove member')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="workspace-manager">
      {error && <p className="auth-error workspace-error">{error}</p>}
      <aside className="workspace-rail">
        <div className="workspace-list">
          {workspaces.map((workspace) => (
            <div
              className={`workspace-item ${workspace.id === active?.id ? 'active' : ''}`}
              key={workspace.id}
            >
              <button className="workspace-select" onClick={() => select(workspace)}>
                <span>
                  <Building2 size={17} />
                </span>
                <span>
                  <strong>{workspace.business_entity}</strong>
                  <small>
                    {workspace.warehouse} · {workspace.role}
                  </small>
                </span>
                {workspace.id === active?.id && <Check size={15} />}
              </button>
              {workspace.role === 'owner' && (
                <div className="workspace-item-actions">
                  <button
                    aria-label={`Edit ${workspace.name}`}
                    onClick={() => beginEdit(workspace)}
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    aria-label={`Delete ${workspace.name}`}
                    onClick={() => beginDelete(workspace)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
        <button
          className="new-workspace"
          onClick={() => {
            setCreate(true)
            setEditing(false)
            setDeleting(null)
          }}
        >
          <Plus size={16} /> Create workspace
        </button>
      </aside>

      <div className="workspace-detail">
        {create ? (
          <form className="workspace-form compact" onSubmit={submitWorkspace}>
            <div className="workspace-detail-head">
              <div>
                <span>NEW WORKSPACE</span>
                <h3>Create a business workspace</h3>
              </div>
            </div>
            <div className="workspace-fields three">
              <label>
                Organization
                <input
                  required
                  value={form.organization_name}
                  onChange={(e) => setForm({ ...form, organization_name: e.target.value })}
                />
              </label>
              <label>
                Workspace name
                <input
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </label>
              <label>
                Business entity
                <input
                  required
                  value={form.business_entity}
                  onChange={(e) => setForm({ ...form, business_entity: e.target.value })}
                />
              </label>
              <label>
                Warehouse
                <input
                  required
                  value={form.warehouse}
                  onChange={(e) => setForm({ ...form, warehouse: e.target.value })}
                />
              </label>
              <label>
                Currency
                <input
                  required
                  maxLength={3}
                  value={form.currency}
                  onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
                />
              </label>
              <label>
                Finance threshold
                <input
                  required
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.finance_threshold}
                  onChange={(e) => setForm({ ...form, finance_threshold: e.target.value })}
                />
              </label>
            </div>
            <div className="workspace-form-actions">
              {!!workspaces.length && (
                <Button kind="secondary" onClick={() => setCreate(false)}>
                  Cancel
                </Button>
              )}
              <Button disabled={busy} type="submit">
                Create workspace
              </Button>
            </div>
          </form>
        ) : active ? (
          <>
            <section className="workspace-summary">
              <div className="workspace-detail-head">
                <div>
                  <span>ACTIVE WORKSPACE</span>
                  <h3>{active.name}</h3>
                </div>
                {active.role === 'owner' && (
                  <div>
                    <Button kind="secondary" onClick={() => beginEdit(active)}>
                      <Pencil size={14} /> Edit
                    </Button>
                    <Button kind="danger" onClick={() => beginDelete(active)}>
                      <Trash2 size={14} /> Delete
                    </Button>
                  </div>
                )}
              </div>
              {deleting ? (
                <div className="workspace-delete-confirm">
                  <div>
                    <strong>Delete {deleting.name}?</strong>
                    <small>
                      Only an empty workspace can be deleted. Procurement history remains protected.
                    </small>
                  </div>
                  <Button kind="secondary" onClick={() => setDeleting(null)}>
                    Cancel
                  </Button>
                  <Button kind="danger" disabled={busy} onClick={() => void deleteWorkspace()}>
                    Delete workspace
                  </Button>
                </div>
              ) : editing && edit ? (
                <form className="workspace-form compact" onSubmit={saveWorkspace}>
                  <div className="workspace-fields three">
                    <label>
                      Name
                      <input
                        required
                        value={edit.name}
                        onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                      />
                    </label>
                    <label>
                      Business entity
                      <input
                        required
                        value={edit.business_entity}
                        onChange={(e) => setEdit({ ...edit, business_entity: e.target.value })}
                      />
                    </label>
                    <label>
                      Warehouse
                      <input
                        required
                        value={edit.warehouse}
                        onChange={(e) => setEdit({ ...edit, warehouse: e.target.value })}
                      />
                    </label>
                    <label>
                      Currency
                      <input
                        required
                        maxLength={3}
                        value={edit.currency}
                        onChange={(e) =>
                          setEdit({ ...edit, currency: e.target.value.toUpperCase() })
                        }
                      />
                    </label>
                    <label>
                      Finance threshold
                      <input
                        required
                        type="number"
                        min="0"
                        step="0.01"
                        value={edit.finance_threshold}
                        onChange={(e) => setEdit({ ...edit, finance_threshold: e.target.value })}
                      />
                    </label>
                  </div>
                  <div className="workspace-form-actions">
                    <Button
                      kind="secondary"
                      onClick={() => {
                        setEdit(active)
                        setEditing(false)
                      }}
                    >
                      Cancel
                    </Button>
                    <Button disabled={busy} type="submit">
                      Save changes
                    </Button>
                  </div>
                </form>
              ) : (
                <dl className="workspace-facts">
                  <div>
                    <dt>Business entity</dt>
                    <dd>{active.business_entity}</dd>
                  </div>
                  <div>
                    <dt>Warehouse</dt>
                    <dd>{active.warehouse}</dd>
                  </div>
                  <div>
                    <dt>Currency</dt>
                    <dd>{active.currency}</dd>
                  </div>
                  <div>
                    <dt>Finance review from</dt>
                    <dd>
                      {active.currency} {active.finance_threshold}
                    </dd>
                  </div>
                </dl>
              )}
            </section>

            {active.role === 'owner' ? (
              <section className="member-manager">
                <div className="workspace-detail-head">
                  <div>
                    <span>ACCESS</span>
                    <h3>
                      <Users size={16} /> Members
                    </h3>
                  </div>
                </div>
                <div className="member-list">
                  {members.map((member) => (
                    <div className="member-row" key={member.id}>
                      <span>
                        <strong>{member.display_name}</strong>
                        <small>{member.email}</small>
                      </span>
                      {member.role === 'owner' ? (
                        <b>Owner</b>
                      ) : (
                        <>
                          <select
                            disabled={busy}
                            value={member.role}
                            onChange={(e) =>
                              void changeRole(member, e.target.value as WorkspaceRole)
                            }
                          >
                            <option value="procurement">Procurement</option>
                            <option value="purchasing">Purchasing manager</option>
                            <option value="finance">Finance manager</option>
                            <option value="viewer">Viewer</option>
                          </select>
                          <button
                            disabled={busy}
                            aria-label={`Remove ${member.display_name}`}
                            onClick={() => void remove(member)}
                          >
                            <Trash2 size={15} />
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
                <form className="member-invite" onSubmit={addMember}>
                  <input
                    required
                    placeholder="Name"
                    value={invite.display_name}
                    onChange={(e) => setInvite({ ...invite, display_name: e.target.value })}
                  />
                  <input
                    required
                    type="email"
                    placeholder="name@company.com"
                    value={invite.email}
                    onChange={(e) => setInvite({ ...invite, email: e.target.value })}
                  />
                  <select
                    value={invite.role}
                    onChange={(e) => setInvite({ ...invite, role: e.target.value })}
                  >
                    <option value="procurement">Procurement</option>
                    <option value="purchasing">Purchasing manager</option>
                    <option value="finance">Finance manager</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <Button disabled={busy} type="submit">
                    Add member
                  </Button>
                </form>
              </section>
            ) : (
              <p className="notice soft">
                Only workspace owners can edit policy or membership. Your role is {active.role}.
              </p>
            )}
          </>
        ) : null}
      </div>
    </div>
  )
}
