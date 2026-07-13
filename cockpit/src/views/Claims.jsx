import React, { useEffect, useState } from 'react'
import { getProject, getClaim, addClaim, editClaim, getArgument } from '../api.js'
import { Stamp, Section, Empty, Mono, Modal } from '../ui.jsx'

export default function Claims({ slug, focus }) {
  const [claims, setClaims] = useState(null)
  const [detail, setDetail] = useState({})
  const [fnd, setFnd] = useState({})   // claim id → foundation ('weak'|'broken')
  const [adding, setAdding] = useState(null)   // {text, kind} while creating
  const [editing, setEditing] = useState(null) // claim id being renamed inline
  const [editText, setEditText] = useState('')
  const [err, setErr] = useState(null)

  const load = () => getProject(slug).then((d) => setClaims(d.claims))
  useEffect(() => {
    getArgument(slug).then((a) => {
      if (!a || a.error) return
      const m = {}
      for (const c of a.claims) if (c.foundation && c.foundation !== 'sound') m[c.id] = c.foundation
      setFnd(m)
    })
  }, [slug])
  useEffect(() => {
    let live = true
    getProject(slug).then((d) => {
      if (!live) return
      setClaims(d.claims)
      if (focus) {
        getClaim(Number(focus)).then((full) => live && setDetail((dd) => ({ ...dd, [focus]: full })))
        requestAnimationFrame(() =>
          document.getElementById(`claim-${focus}`)?.scrollIntoView({ block: 'center' }))
      }
    })
    return () => { live = false }
  }, [slug, focus])

  const toggle = async (id) => {
    if (detail[id]) { setDetail({ ...detail, [id]: null }); return }
    const full = await getClaim(id)
    setDetail((d) => ({ ...d, [id]: full }))
  }

  const save = async () => {
    setErr(null)
    const r = await addClaim(slug, (adding.text || '').trim(), adding.kind || 'assertion')
    if (r && r.error) { setErr(r.error); return }
    setAdding(null)
    load()
  }

  const commitEdit = async () => {
    const t = editText.trim()
    const c = claims.find((x) => x.id === editing)
    if (t && c && t !== c.text) await editClaim(editing, t)
    setEditing(null)
    load()
  }

  if (!claims) return <div className="loading">reading the store…</div>

  return (
    <>
      <div className="pagehead with-action">
        <h1>Claims</h1>
        <button className="gtool" onClick={() => setAdding({ kind: 'assertion' })}>+ Add claim</button>
      </div>
      <Section title="Claim ledger" aside={`${claims.length} claims`}>
        {claims.map((c) => (
          <div key={c.id} id={`claim-${c.id}`} className={String(focus) === String(c.id) ? 'flash' : ''}>
            <div className="row">
              <button className="rowbtn" style={{ width: 'auto' }} onClick={() => toggle(c.id)}
                      title="Show evidence">
                <Mono>#{c.id}</Mono>
              </button>
              <Stamp value={c.status} />
              {fnd[c.id] && (
                <Stamp value={fnd[c.id] === 'broken' ? 'foundation broken' : 'foundation weak'}
                       tone={fnd[c.id] === 'broken' ? 'bad' : 'warn'} />
              )}
              {editing === c.id ? (
                <textarea className="inline-edit" autoFocus value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitEdit() }
                            if (e.key === 'Escape') setEditing(null)
                          }} />
              ) : (
                <div className="grow inline-target" title="Click to edit"
                     onClick={() => { setEditing(c.id); setEditText(c.text) }}>
                  {c.text}
                </div>
              )}
              <span className="chip">{c.kind}</span>
            </div>
            {detail[c.id] && (
              <div className="detail">
                {(detail[c.id].evidence || []).map((ev, i) => (
                  <div className="kv" key={i}>
                    <span className="k">{ev.stance}</span>
                    <span className="mono">
                      {ev.run_id ? `run #${ev.run_id}` : `citation #${ev.citation_id}`}
                    </span>
                    {ev.note && <span className="muted">— {ev.note}</span>}
                  </div>
                ))}
                {!(detail[c.id].evidence || []).length && (
                  <div className="muted">No evidence linked — <span className="mono">reref claim link {c.id} --run N</span></div>
                )}
              </div>
            )}
          </div>
        ))}
        {!claims.length && (
          <Empty>No claims yet — <code>reref claim add {slug} "…" --kind thesis</code> states what the runs must prove.</Empty>
        )}
      </Section>

      <Modal open={!!adding} title="New claim" onClose={() => setAdding(null)}>
        <textarea autoFocus placeholder="The claim — one testable statement"
                  value={adding?.text || ''}
                  onChange={(e) => setAdding({ ...adding, text: e.target.value })} />
        <select className="text" value={adding?.kind || 'assertion'}
                onChange={(e) => setAdding({ ...adding, kind: e.target.value })}>
          <option value="assertion">Assertion</option>
          <option value="contribution">Contribution</option>
          <option value="thesis">Thesis</option>
        </select>
        <div className="muted" style={{ fontSize: 11.5 }}>
          Status is derived from evidence — link runs or citations on the graph. The claim appears there immediately.
        </div>
        {err && <div style={{ color: 'var(--bad)', fontSize: 12 }}>{err}</div>}
        <div className="gnode-actions" style={{ marginTop: 0 }}>
          <button className="btn" onClick={save} disabled={!(adding?.text || '').trim()}>Add claim</button>
          <button className="btn ghost" onClick={() => setAdding(null)}>Cancel</button>
        </div>
      </Modal>
    </>
  )
}
