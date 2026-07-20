import React, { useEffect, useState } from 'react'
import { getProject, adjudicate } from '../api.js'
import { Stamp, Section, Empty, Mono, timeAgo } from '../ui.jsx'

function OpenFinding({ f, onDone }) {
  const [verdict, setVerdict] = useState(null)   // 'accept' | 'reject' | null
  const [reason, setReason] = useState('')
  const [err, setErr] = useState(null)

  const submit = async () => {
    if (!reason.trim()) { setErr('Reasoning is required — it is what future reviews learn from.'); return }
    const r = await adjudicate(f.id, verdict, reason.trim())
    if (r.error) setErr(r.error)
    else onDone()
  }

  return (
    <div>
      <div className="row">
        <Stamp value={f.severity} />
        <Mono>{f.check_id}</Mono>
        <div className="grow">{f.issue}</div>
        {f.section && <span className="chip">{f.section}</span>}
        <span className="when">{timeAgo(f.created)}</span>
      </div>
      <div className="detail">
        {!verdict && (
          <div className="gnode-actions" style={{ marginTop: 0 }}>
            <button className="btn ghost" onClick={() => setVerdict('accept')}>Accept…</button>
            <button className="btn ghost" onClick={() => setVerdict('reject')}>Reject…</button>
          </div>
        )}
        {verdict && (
          <>
            <textarea
              autoFocus
              placeholder={`Why ${verdict}? Rejected findings are remembered and never re-raised.`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            {err && <div style={{ color: 'var(--bad)', marginTop: 5 }}>{err}</div>}
            <div className="gnode-actions">
              <button className={`btn ${verdict === 'reject' ? 'danger' : ''}`} onClick={submit}>
                {verdict === 'accept' ? 'Accept finding' : 'Reject finding'}
              </button>
              <button className="btn ghost" onClick={() => { setVerdict(null); setErr(null) }}>Cancel</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function Findings({ slug }) {
  const [findings, setFindings] = useState(null)

  const load = () => getProject(slug).then((d) => setFindings(d.findings))
  useEffect(() => { setFindings(null); load() }, [slug])

  if (!findings) return <div className="loading">reading the store…</div>

  const open = findings.filter((f) => f.status === 'open')
  const closed = findings.filter((f) => f.status !== 'open')

  return (
    <>
      <div className="pagehead">
        <h1>Findings</h1>
      </div>
      <Section title="Open" aside={`${open.length} awaiting adjudication`}>
        {open.map((f) => <OpenFinding key={f.id} f={f} onDone={load} />)}
        {!open.length && (
          <Empty>Nothing awaits a verdict — <code>renv review {slug}</code> runs the automated checks on the draft.</Empty>
        )}
      </Section>
      <div style={{ height: 14 }} />
      <Section title="Adjudicated" aside={`${closed.length} settled`}>
        {closed.map((f) => (
          <div className="row" key={f.id}>
            <Stamp value={f.status} />
            <Mono>{f.check_id}</Mono>
            <div className="grow muted">{f.issue}</div>
            <span className="when">{timeAgo(f.created)}</span>
          </div>
        ))}
        {!closed.length && <Empty>No settled findings yet.</Empty>}
      </Section>
    </>
  )
}
