import { useEffect, useState, type FormEvent } from 'react'
import { Building2, Check, Plus, Trash2, Users } from 'lucide-react'

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
      await onReload(edit.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to update workspace')
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
      {error && <p className="auth-error">{error}</p>}
      <div className="workspace-list">
        {workspaces.map((workspace) => (
          <button
            key={workspace.id}
            className={workspace.id === active?.id ? 'active' : ''}
            onClick={() => onSelect(workspace.id)}
          >
            <span><Building2 size={17} /></span>
            <span><strong>{workspace.business_entity}</strong><small>{workspace.warehouse} · {workspace.role}</small></span>
            {workspace.id === active?.id && <Check size={16} />}
          </button>
        ))}
        <button className="new-workspace" onClick={() => setCreate(true)}>
          <Plus size={17} /> Create workspace
        </button>
      </div>

      {create ? (
        <form className="workspace-form" onSubmit={submitWorkspace}>
          <h3>New business workspace</h3>
          <label>Organization<input required value={form.organization_name} onChange={(e) => setForm({ ...form, organization_name: e.target.value })} /></label>
          <label>Workspace name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>Business entity<input required value={form.business_entity} onChange={(e) => setForm({ ...form, business_entity: e.target.value })} /></label>
          <label>Warehouse<input required value={form.warehouse} onChange={(e) => setForm({ ...form, warehouse: e.target.value })} /></label>
          <div className="form-grid two">
            <label>Currency<input required maxLength={3} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} /></label>
            <label>Finance threshold<input required type="number" min="0" step="0.01" value={form.finance_threshold} onChange={(e) => setForm({ ...form, finance_threshold: e.target.value })} /></label>
          </div>
          <Button disabled={busy} type="submit">Create workspace</Button>
        </form>
      ) : edit && active?.role === 'owner' ? (
        <>
          <form className="workspace-form" onSubmit={saveWorkspace}>
            <h3>Workspace policy</h3>
            <label>Name<input required value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
            <label>Business entity<input required value={edit.business_entity} onChange={(e) => setEdit({ ...edit, business_entity: e.target.value })} /></label>
            <label>Warehouse<input required value={edit.warehouse} onChange={(e) => setEdit({ ...edit, warehouse: e.target.value })} /></label>
            <div className="form-grid two">
              <label>Currency<input required maxLength={3} value={edit.currency} onChange={(e) => setEdit({ ...edit, currency: e.target.value.toUpperCase() })} /></label>
              <label>Finance threshold<input required type="number" min="0" step="0.01" value={edit.finance_threshold} onChange={(e) => setEdit({ ...edit, finance_threshold: e.target.value })} /></label>
            </div>
            <Button disabled={busy} type="submit">Save policy</Button>
          </form>
          <section className="member-manager">
            <h3><Users size={17} /> Members</h3>
            {members.map((member) => (
              <div className="member-row" key={member.id}>
                <span><strong>{member.display_name}</strong><small>{member.email}</small></span>
                {member.role === 'owner' ? <b>Owner</b> : (
                  <>
                    <select disabled={busy} value={member.role} onChange={(e) => void changeRole(member, e.target.value as WorkspaceRole)}>
                      <option value="procurement">Procurement</option>
                      <option value="purchasing">Purchasing manager</option>
                      <option value="finance">Finance manager</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <button disabled={busy} aria-label={`Remove ${member.display_name}`} onClick={() => void remove(member)}><Trash2 size={15} /></button>
                  </>
                )}
              </div>
            ))}
            <form className="member-invite" onSubmit={addMember}>
              <input required placeholder="Name" value={invite.display_name} onChange={(e) => setInvite({ ...invite, display_name: e.target.value })} />
              <input required type="email" placeholder="name@company.com" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
              <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
                <option value="procurement">Procurement</option>
                <option value="purchasing">Purchasing manager</option>
                <option value="finance">Finance manager</option>
                <option value="viewer">Viewer</option>
              </select>
              <Button disabled={busy} type="submit">Add member</Button>
            </form>
          </section>
        </>
      ) : active ? (
        <p className="notice soft">Only workspace owners can edit policy or membership. Your role is {active.role}.</p>
      ) : null}
    </div>
  )
}
