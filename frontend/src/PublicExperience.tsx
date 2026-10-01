import { useState, type FormEvent } from 'react'
import {
  ArrowRight,
  BarChart3,
  Check,
  ChevronRight,
  FileCheck2,
  Layers3,
  LockKeyhole,
  Menu,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react'
import { api } from './api'
import { cloudAuthEnabled, supabase } from './auth'

export interface WorkspaceUser {
  name: string
  email: string
  role: string
  initials: string
}

type View = 'landing' | 'login' | 'signup'

function initials(name: string) {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'PR'
  )
}

function Brand() {
  return (
    <button className="public-brand" onClick={() => location.assign(location.pathname)}>
      <span>
        <Layers3 size={20} />
      </span>
      <strong>Supplydesk</strong>
    </button>
  )
}

function AuthPage({
  view,
  onView,
  onEnter,
}: {
  view: Exclude<View, 'landing'>
  onView: (v: View) => void
  onEnter: (u: WorkspaceUser, accessToken?: string) => void
}) {
  const signup = view === 'signup'
  const [method, setMethod] = useState<'business' | 'demo'>('business')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setNotice('')
    if (method === 'demo') {
      if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$/.test(username))
        return setError('Use 3–32 letters, numbers, dots, hyphens or underscores.')
      if (password.length < 8) return setError('Use at least 8 characters.')
      setBusy(true)
      try {
        const session = signup
          ? await api.demoRegister({ username, password })
          : await api.demoLogin({ username, password })
        onEnter(session.user, session.access_token)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unable to access the demo account.')
      } finally {
        setBusy(false)
      }
      return
    }
    if (signup && name.trim().length < 2) return setError('Enter your full name.')
    if (!email.includes('@')) return setError('Enter a valid business email.')
    if (password.length < 8) return setError('Use at least 8 characters.')
    if (!cloudAuthEnabled || !supabase)
      return setError('Business accounts require the hosted Supabase deployment.')
    const displayName = signup ? name.trim() : email.split('@')[0].replace(/[._-]/g, ' ')
    setBusy(true)
    const result = signup
      ? await supabase.auth.signUp({
          email,
          password,
          options: {
            data: { full_name: displayName },
            emailRedirectTo: `${window.location.origin}${import.meta.env.BASE_URL}`,
          },
        })
      : await supabase.auth.signInWithPassword({ email, password })
    setBusy(false)
    if (result.error) return setError(result.error.message)
    if (!result.data.session) {
      setNotice('Check your email to confirm the account, then sign in.')
      return
    }
    onEnter({
      name: displayName.replace(/\b\w/g, (letter) => letter.toUpperCase()),
      email,
      role: signup ? 'Procurement Member' : 'Procurement Manager',
      initials: initials(displayName),
    })
  }

  return (
    <div className="auth-page">
      <header className="auth-nav">
        <Brand />
        <button onClick={() => onView('landing')}>
          <X size={18} /> Close
        </button>
      </header>
      <div className="auth-layout">
        <section className="auth-story">
          <span className="auth-kicker">PROCUREMENT, WITH CONTROL</span>
          <h1>Every recommendation explained. Every order reviewed.</h1>
          <p>
            Turn inventory, demand and supplier data into an auditable purchase-order
            workflow—without giving up human control.
          </p>
          <div className="auth-proof">
            <div>
              <ShieldCheck size={19} />
              <span>
                <strong>Human approval</strong>
                <small>Required before every export</small>
              </span>
            </div>
            <div>
              <FileCheck2 size={19} />
              <span>
                <strong>Complete audit trail</strong>
                <small>Source evidence for each decision</small>
              </span>
            </div>
          </div>
        </section>
        <section className="auth-card" aria-labelledby="auth-title">
          <div className="auth-lock">
            <LockKeyhole size={19} />
          </div>
          <span className="auth-overline">
            {signup ? 'CREATE YOUR ACCOUNT' : 'SECURE ACCOUNT ACCESS'}
          </span>
          <h2 id="auth-title">{signup ? 'Sign up for Supplydesk' : 'Welcome back'}</h2>
          <p>
            {signup
              ? 'Choose a verified business account or a fast demo account.'
              : 'Sign in to your business or demo account.'}
          </p>
          <div className="auth-methods" role="tablist" aria-label="Account type">
            <button
              type="button"
              role="tab"
              aria-selected={method === 'business'}
              className={method === 'business' ? 'active' : ''}
              onClick={() => {
                setMethod('business')
                setError('')
                setNotice('')
              }}
            >
              {signup ? 'Normal registration' : 'Business account'}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={method === 'demo'}
              className={method === 'demo' ? 'active' : ''}
              onClick={() => {
                setMethod('demo')
                setError('')
                setNotice('')
              }}
            >
              {signup ? 'Demo registration' : 'Demo account'}
            </button>
          </div>
          <form onSubmit={submit}>
            {method === 'business' && signup && (
              <label>
                Full name
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Alex Morgan"
                />
              </label>
            )}
            {method === 'business' ? (
              <label>
                Business email
                <input
                  autoFocus={!signup}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  autoComplete="email"
                />
              </label>
            ) : (
              <label>
                Username
                <input
                  autoFocus
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="procurement_demo"
                  autoComplete="username"
                />
              </label>
            )}
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                autoComplete={signup ? 'new-password' : 'current-password'}
              />
            </label>
            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
            {notice && <p className="notice soft">{notice}</p>}
            <button className="auth-submit" type="submit" disabled={busy}>
              {busy
                ? 'Please wait…'
                : signup
                  ? method === 'demo'
                    ? 'Create demo account'
                    : 'Create business account'
                  : 'Sign in'}
              <ArrowRight size={16} />
            </button>
          </form>
          <p className="auth-switch">
            {signup ? 'Already have an account?' : 'New to Supplydesk?'}{' '}
            <button onClick={() => onView(signup ? 'login' : 'signup')}>
              {signup ? 'Log in' : 'Sign up'}
            </button>
          </p>
          <small className="auth-note">
            {method === 'demo'
              ? 'Demo registration needs no email, phone or verification. Demo accounts still receive an isolated workspace session.'
              : 'Business account sessions and email verification are managed by Supabase.'}
          </small>
        </section>
      </div>
    </div>
  )
}

export function PublicExperience({
  onEnter,
}: {
  onEnter: (user: WorkspaceUser, accessToken?: string) => void
}) {
  const [view, setView] = useState<View>('landing')
  const [menu, setMenu] = useState(false)
  if (view !== 'landing') return <AuthPage view={view} onView={setView} onEnter={onEnter} />

  return (
    <div className="landing-page">
      <header className="landing-nav">
        <Brand />
        <nav className={menu ? 'open' : ''}>
          <a href="#capabilities" onClick={() => setMenu(false)}>
            Platform
          </a>
          <a href="#workflow" onClick={() => setMenu(false)}>
            Workflow
          </a>
          <a href="#controls" onClick={() => setMenu(false)}>
            Controls
          </a>
        </nav>
        <div className="landing-actions">
          <button onClick={() => setView('login')}>Login</button>
          <button className="nav-cta" onClick={() => setView('signup')}>
            Sign up <ArrowRight size={14} />
          </button>
        </div>
        <button className="landing-menu" aria-label="Toggle menu" onClick={() => setMenu(!menu)}>
          {menu ? <X /> : <Menu />}
        </button>
      </header>

      <main>
        <section className="landing-hero">
          <div className="hero-copy">
            <span className="hero-eyebrow">
              <i /> PROCUREMENT INTELLIGENCE, WITH CONTROL
            </span>
            <h1>
              From fragmented data
              <br />
              to a <em>defensible order.</em>
            </h1>
            <p>
              Supplydesk gives procurement teams one rigorous workspace to validate source data,
              evaluate every SKU, resolve exceptions and approve purchase orders.
            </p>
            <div className="hero-actions">
              <button className="hero-primary" onClick={() => setView('login')}>
                Login <ArrowRight size={16} />
              </button>
              <button className="hero-secondary" onClick={() => setView('signup')}>
                Sign up
              </button>
            </div>
            <div className="hero-trust">
              <span>
                <Check size={14} /> Deterministic decisions
              </span>
              <span>
                <Check size={14} /> Human approval
              </span>
              <span>
                <Check size={14} /> Full audit history
              </span>
            </div>
          </div>
          <div className="hero-product" aria-label="Supplydesk product preview">
            <div className="preview-top">
              <span>
                <Layers3 size={14} /> Supplydesk
              </span>
              <span>Current review · 27 Sep 2026</span>
            </div>
            <div className="preview-body">
              <div className="preview-side">
                <i />
                <i />
                <i className="active" />
                <i />
                <i />
              </div>
              <div className="preview-content">
                <span className="preview-label">DAILY PROCUREMENT REVIEW</span>
                <h2>Decision overview</h2>
                <p>Every active SKU is accounted for.</p>
                <div className="preview-metrics">
                  <div>
                    <small>SKUs reviewed</small>
                    <strong>10</strong>
                    <span>100% coverage</span>
                  </div>
                  <div>
                    <small>Ready to order</small>
                    <strong>06</strong>
                    <span>3 suppliers</span>
                  </div>
                  <div>
                    <small>Needs attention</small>
                    <strong>03</strong>
                    <span>Action required</span>
                  </div>
                </div>
                <div className="preview-panel">
                  <div>
                    <span>Decision completion</span>
                    <strong>70%</strong>
                  </div>
                  <div className="preview-track">
                    <i />
                  </div>
                  <div className="preview-rows">
                    <span>SKU-001</span>
                    <span>Office consumables</span>
                    <b>REORDER</b>
                  </div>
                  <div className="preview-rows">
                    <span>SKU-004</span>
                    <span>Price verification</span>
                    <b className="warning">BLOCKED</b>
                  </div>
                </div>
              </div>
            </div>
            <div className="preview-float">
              <ShieldCheck size={20} />
              <span>
                <strong>Approval protected</strong>
                <small>Critical edits require a new review</small>
              </span>
            </div>
          </div>
        </section>

        <section className="credibility">
          <span>BUILT FOR CONTROLLED PROCUREMENT</span>
          <div>
            <strong>Source-aware</strong>
            <strong>Exception-led</strong>
            <strong>Human-approved</strong>
            <strong>Audit-ready</strong>
          </div>
        </section>

        <section className="capabilities" id="capabilities">
          <div className="landing-section-heading">
            <span>CORE PLATFORM</span>
            <h2>A disciplined workflow for the work between planning and purchasing.</h2>
            <p>
              Focused tools for making reliable procurement decisions—without replacing professional
              judgment.
            </p>
          </div>
          <div className="capability-grid">
            <article>
              <span>01</span>
              <BarChart3 />
              <h3>Decision engine</h3>
              <p>
                Evaluate every SKU against dated demand, incoming supply, safety stock, MOQ and pack
                constraints.
              </p>
              <a>
                Trace the calculation <ChevronRight size={14} />
              </a>
            </article>
            <article>
              <span>02</span>
              <Sparkles />
              <h3>Exception workspace</h3>
              <p>
                Separate missing or conflicting data from valid decisions, then recheck only what
                changed.
              </p>
              <a>
                Resolve with context <ChevronRight size={14} />
              </a>
            </article>
            <article>
              <span>03</span>
              <ShieldCheck />
              <h3>Approval controls</h3>
              <p>
                Group recommendations by supplier, protect approvals with version checks and retain
                every action.
              </p>
              <a>
                Review with confidence <ChevronRight size={14} />
              </a>
            </article>
          </div>
        </section>

        <section className="workflow-section" id="workflow">
          <div>
            <span>ONE OPERATING VIEW</span>
            <h2>
              Clear enough for the daily review.
              <br />
              Rigorous enough for the audit.
            </h2>
          </div>
          <ol>
            <li>
              <b>01</b>
              <span>
                <strong>Validate</strong>
                <small>Import and verify source records</small>
              </span>
            </li>
            <li>
              <b>02</b>
              <span>
                <strong>Evaluate</strong>
                <small>Review every SKU and its evidence</small>
              </span>
            </li>
            <li>
              <b>03</b>
              <span>
                <strong>Resolve</strong>
                <small>Correct blockers with ownership</small>
              </span>
            </li>
            <li>
              <b>04</b>
              <span>
                <strong>Approve</strong>
                <small>Release a controlled PO export</small>
              </span>
            </li>
          </ol>
        </section>

        <section className="control-section" id="controls">
          <div>
            <span className="control-icon">
              <LockKeyhole />
            </span>
            <span>DESIGNED AROUND ACCOUNTABILITY</span>
            <h2>
              Automation prepares the decision.
              <br />
              Your team owns the commitment.
            </h2>
            <p>
              Calculations remain deterministic. Missing facts remain visible. Critical edits
              invalidate approval. Every export is tied to a named review.
            </p>
            <button onClick={() => setView('login')}>
              Explore the workspace <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </main>
      <footer className="landing-footer">
        <Brand />
        <span>Procurement decisions, clearly prepared.</span>
        <small>© 2026 Supplydesk</small>
      </footer>
    </div>
  )
}
