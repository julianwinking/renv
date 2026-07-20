// Shared primitives: the ledger's visual vocabulary.
// A Stamp marks a state; a Metric renders a measured value per its definition.
import React from 'react'

// status/severity/stance → tone class
const TONE = {
  done: 'ok', supported: 'ok', accepted: 'ok', resolved: 'ok', full: 'ok', complete: 'ok',
  running: 'warn', partial: 'warn', medium: 'warn', degraded: 'warn',
  failed: 'bad', refuted: 'bad', abandoned: 'bad', high: 'bad', rejected: 'bad', none: 'bad',
  planned: 'idle', open: 'idle', low: 'idle', info: 'idle',
}

export function Stamp({ value, tone, title }) {
  if (!value) return null
  return (
    <span className={`stamp stamp-${tone || TONE[value] || 'idle'}`} title={title}>
      {value}
    </span>
  )
}

// Python-format-spec subset (.3f / .1% / .4g) — mirrors renv.experiment.fmt_metric.
export function fmtValue(def, v) {
  if (typeof v !== 'number') return String(v)
  let out
  const m = def && /^\.(\d+)([f%g])$/.exec(def.fmt || '')
  if (m && m[2] === 'f') out = v.toFixed(+m[1])
  else if (m && m[2] === '%') out = (v * 100).toFixed(+m[1]) + '%'
  else out = String(Number(v.toPrecision(4)))
  return def && def.unit ? out + def.unit : out
}

export function Metric({ defs, name, value }) {
  const def = (defs || {})[name]
  const dir = def && def.direction
  return (
    <span className="metric" title={def && def.description ? def.description : name}>
      <span className="metric-name">{(def && def.label) || name}</span>
      <span className="metric-value">{fmtValue(def, value)}</span>
      {dir === 'maximize' && <span className="metric-dir">↑</span>}
      {dir === 'minimize' && <span className="metric-dir">↓</span>}
    </span>
  )
}

export function Metrics({ defs, metrics }) {
  const entries = Object.entries(metrics || {})
  if (!entries.length) return null
  return (
    <span className="metrics">
      {entries.map(([k, v]) => <Metric key={k} defs={defs} name={k} value={v} />)}
    </span>
  )
}

export function Section({ title, aside, children }) {
  return (
    <section className="card">
      <header className="card-head">
        <h3>{title}</h3>
        {aside && <div className="card-aside">{aside}</div>}
      </header>
      {children}
    </section>
  )
}

export function Empty({ children }) {
  return <div className="empty-state">{children}</div>
}

export function Mono({ children, title }) {
  return <span className="mono" title={title}>{children}</span>
}

// A region membership chip (a graph node's location). Empty when unplaced.
export function RegionTag({ region }) {
  if (!region) return null
  return (
    <span className={`region-tag region-${region.color || 'slate'}`}>
      {region.label || 'region'}
    </span>
  )
}

export function timeAgo(iso) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 90) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`
  return new Date(iso).toISOString().slice(0, 10)
}

// A crashed view must never white the whole app: render the error where the
// view would be, keep the shell alive. Keyed per view so navigation resets it.
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="card" style={{ margin: 22, padding: '14px 16px' }}>
        <div className="eyebrow" style={{ margin: '0 0 8px' }}>this view crashed</div>
        <div className="mono" style={{ color: 'var(--bad)', fontSize: 12 }}>
          {String(this.state.error)}
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          Often a stale server after an update — it exits when idle and the next
          request starts the new one. Try again, or restart with <span className="mono">renv web</span>.
        </div>
        <div className="gnode-actions">
          <button className="btn" onClick={() => location.reload()}>Reload</button>
        </div>
      </div>
    )
  }
}

// Normalize API list responses: a stale/erroring server returns {error: …} —
// render that as empty, never crash a .map on it.
export const asArray = (x) => (Array.isArray(x) ? x : [])

// Reusable centered modal dialog for create/edit forms.
export function Modal({ open, title, onClose, children }) {
  if (!open) return null
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="modal">
        <div className="eyebrow" style={{ margin: '0 0 12px' }}>{title}</div>
        {children}
      </div>
    </>
  )
}

// Minimal reusable confirm dialog — for actions worth a second look
// (e.g. moving a deadline). Renders nothing when closed.
export function Confirm({ open, title, body, confirmLabel = 'Confirm', danger, onConfirm, onCancel }) {
  if (!open) return null
  return (
    <>
      <div className="backdrop" onClick={onCancel} />
      <div className="confirm">
        <div className="eyebrow" style={{ margin: 0 }}>{title}</div>
        <div style={{ margin: '10px 0 14px' }}>{body}</div>
        <div className="gnode-actions" style={{ marginTop: 0 }}>
          <button className={`btn ${danger ? 'danger' : ''}`} onClick={onConfirm} autoFocus>
            {confirmLabel}
          </button>
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </>
  )
}

// provenance stamp for a run
export function Provenance({ run }) {
  const grade = run.provenance || (run.status === 'done' ? 'unknown' : null)
  if (!grade) return null
  const tone = grade === 'complete' ? 'ok' : 'warn'
  const why = run.dirty ? 'git tree was dirty' : 'git sha + env + dataset pinned'
  return <Stamp value={grade} tone={tone} title={why} />
}
