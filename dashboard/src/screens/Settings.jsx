import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth.jsx'
import { Tile, Table, Empty } from '../components/ui'

const ROLES = ['viewer', 'member', 'admin']

export default function Settings() {
  const { activeOrg, user, saasEnabled } = useAuth()
  const [members, setMembers] = useState([])
  const [config, setConfig] = useState(null)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('member')
  const [inviteMsg, setInviteMsg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!activeOrg) return
    api.members(activeOrg).then(setMembers)
    api.orgConfig().then(setConfig)
  }, [activeOrg])

  const invite = async (e) => {
    e.preventDefault()
    setInviteMsg(''); setError('')
    const res = await api.inviteMember(activeOrg, inviteEmail, inviteRole)
    if (res?.ok) {
      setInviteMsg(`Invited ${inviteEmail} as ${inviteRole}`)
      setInviteEmail('')
      const m = await api.members(activeOrg)
      setMembers(m || [])
    } else {
      setError(res?.error || 'Invite failed')
    }
  }

  if (!saasEnabled) return (
    <div className="page"><h1>Settings</h1>
      <p className="muted">SaaS settings are only available when SaaS is enabled.</p>
    </div>
  )

  return <div className="page"><h1>Organization settings</h1>
    <div className="tiles">
      <Tile k="Organization" v={activeOrg ? `${activeOrg} (${user?.email})` : '—'} />
      <Tile k="Members" v={members?.length ?? '—'} />
    </div>
    <h2>Members</h2>
    {members?.length ? <Table cols={['Email', 'Phone', 'Role']}
      rows={members.map(m => [m.email || '—', m.phone || '—', m.role])} />
      : <Empty what="members" />}
    <h2>Invite member</h2>
    <form onSubmit={invite}>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <span style={{ display: 'block', color: 'var(--muted)', fontSize: 12, marginBottom: 4 }}>Email</span>
        <input type="email" value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} required
          style={{ width: '100%', padding: '8px 10px', background: '#222836', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 6 }} />
      </label>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <span style={{ display: 'block', color: 'var(--muted)', fontSize: 12, marginBottom: 4 }}>Role</span>
        <select value={inviteRole} onChange={e => setInviteRole(e.target.value)}
          style={{ width: '100%', padding: '8px 10px', background: '#222836', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 6 }}>
          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
      </label>
      {error && <p style={{ color: 'var(--red)', fontSize: 13 }}>{error}</p>}
      {inviteMsg && <p style={{ color: 'var(--green)', fontSize: 13 }}>{inviteMsg}</p>}
      <button type="submit">Send invite</button>
    </form>
    <h2>Config overrides</h2>
    <pre className="muted" style={{ fontSize: 12, maxHeight: 300, overflow: 'auto' }}>{config ? JSON.stringify(config, null, 2) : '—'}</pre>
  </div>
}
