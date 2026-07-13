import React, { useEffect, useState } from 'react'
import { getProject, getRuns, addExperiment, editExperiment } from '../api.js'
import { asArray, Stamp, Metrics, Section, Empty, Mono, timeAgo, Provenance, Modal, RegionTag } from '../ui.jsx'

function Run({ run, defs }) {
  const where = run.remote
    ? run.remote.replace(/^[a-z+]+:\/\//, '').split('/')[0]   // host part
    : 'Local'
  return (
    <tr>
      <td className="num">#{run.id}</td>
      <td><Stamp value={run.status} /></td>
      <td><Metrics defs={defs} metrics={run.metrics} /></td>
      <td className="num faint">
        {Object.entries(run.params || {}).filter(([k]) => k !== 'data')
          .map(([k, v]) => `${k}=${v}`).join(' ') || '—'}
      </td>
      <td className="num faint">{run.seed ?? '—'}</td>
      <td><Provenance run={run} /></td>
      <td className="num faint"
          title={(run.remote || 'ran on this machine')
                 + (run.dataset ? `\ndata: ${run.dataset}` : '')
                 + (run.dataset_location ? ` @ ${run.dataset_location}` : '')}>
        {where}{run.dataset_location && !run.dataset_location.startsWith('/') ? ' ⇅' : ''}
      </td>
      <td className="num faint" title={run.git_sha}>{(run.git_sha || '').slice(0, 7) || '—'}</td>
      <td className="when">{timeAgo(run.started)}</td>
    </tr>
  )
}

export default function Experiments({ slug, defs, focus }) {
  const [exps, setExps] = useState(null)
  const [runs, setRuns] = useState([])
  const [open, setOpen] = useState({})
  const [adding, setAdding] = useState(null)
  const [editing, setEditing] = useState(null)   // slug whose title is being edited
  const [editText, setEditText] = useState('')
  const [err, setErr] = useState(null)

  const commitEdit = async () => {
    const t = editText.trim()
    const e = exps.find((x) => x.slug === editing)
    if (t && e && t !== e.title) await editExperiment(slug, editing, { title: t })
    setEditing(null)
    load()
  }

  const commitHyp = async (e) => {
    const t = editText.trim()
    if (t !== (e.hypothesis || '')) await editExperiment(slug, e.slug, { hypothesis: t })
    setEditing(null)
    load()
  }

  const load = () => getProject(slug).then((d) => setExps(d.experiments))
  useEffect(() => {
    let live = true
    getProject(slug).then((d) => {
      if (!live) return
      setExps(d.experiments)
      const hit = focus && d.experiments.find((e) => e.slug === focus)
      if (hit) {
        setOpen((o) => ({ ...o, [hit.id]: true }))
        requestAnimationFrame(() =>
          document.getElementById(`exp-${focus}`)?.scrollIntoView({ block: 'center' }))
      }
    })
    getRuns(slug).then((r) => live && setRuns(asArray(r)))
    return () => { live = false }
  }, [slug, focus])

  const save = async () => {
    setErr(null)
    const r = await addExperiment(slug, (adding.slug || '').trim(),
                                  adding.title || undefined, adding.hypothesis || undefined,
                                  adding.parent || undefined)
    if (r && r.error) { setErr(r.error); return }
    setAdding(null)
    load()
  }

  if (!exps) return <div className="loading">reading the store…</div>

  const byId = Object.fromEntries(exps.map((e) => [e.id, e]))
  const depth = (e) => {
    let d = 0, p = e.parent_id
    while (p && byId[p]) { d += 1; p = byId[p].parent_id }
    return d
  }

  return (
    <>
      <div className="pagehead with-action">
        <h1>Experiments</h1>
        <button className="gtool" onClick={() => setAdding({})}>+ Add experiment</button>
      </div>
      <Section title="Branches" aside={`${exps.length} experiments · ${runs.length} runs`}>
        {exps.map((e) => {
          const eruns = runs.filter((r) => r.experiment === e.slug)
          const isOpen = !!open[e.id]
          return (
            <div key={e.id} id={`exp-${e.slug}`} className={focus === e.slug ? 'flash' : ''}>
              <div className="row" style={{ paddingLeft: 16 + depth(e) * 22 }}>
                <button className="rowbtn" style={{ width: 'auto', display: 'flex', gap: 10, alignItems: 'baseline' }}
                        onClick={() => setOpen({ ...open, [e.id]: !isOpen })} title="Show runs">
                  <span className="faint mono">{isOpen ? '▾' : '▸'}</span>
                  <Mono>{e.slug}</Mono>
                </button>
                {editing === e.slug ? (
                  <textarea className="inline-edit" autoFocus value={editText}
                            onChange={(ev) => setEditText(ev.target.value)}
                            onBlur={commitEdit}
                            onKeyDown={(ev) => {
                              if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); commitEdit() }
                              if (ev.key === 'Escape') setEditing(null)
                            }} />
                ) : (
                  <div className="grow inline-target" title="Click to edit"
                       onClick={() => { setEditing(e.slug); setEditText(e.title || '') }}>
                    {e.title || <span className="faint">no title</span>}
                  </div>
                )}
                <Metrics defs={defs} metrics={e.metrics} />
                <RegionTag region={e.region} />
                <Stamp value={e.status} />
              </div>
              {isOpen && (
                <div className="detail">
                  <div className="kv">
                    <span className="k">Hypothesis</span>
                    {editing === `hyp:${e.slug}` ? (
                      <textarea className="inline-edit" autoFocus value={editText}
                                onChange={(ev) => setEditText(ev.target.value)}
                                onBlur={() => commitHyp(e)}
                                onKeyDown={(ev) => {
                                  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); commitHyp(e) }
                                  if (ev.key === 'Escape') setEditing(null)
                                }} />
                    ) : (
                      <span className="grow inline-target" title="Click to edit"
                            onClick={() => { setEditing(`hyp:${e.slug}`); setEditText(e.hypothesis || '') }}>
                        {e.hypothesis || <span className="faint">no hypothesis — click to add</span>}
                      </span>
                    )}
                  </div>
                  {eruns.length > 0 && (
                    <table className="ledger-t" style={{ marginTop: 8 }}>
                      <thead>
                        <tr><th>run</th><th>status</th><th>metrics</th><th>params</th><th>seed</th><th>provenance</th><th>where</th><th>git</th><th>when</th></tr>
                      </thead>
                      <tbody>{eruns.map((r) => <Run key={r.id} run={r} defs={defs} />)}</tbody>
                    </table>
                  )}
                  {!eruns.length && <div className="muted">No runs yet — <span className="mono">reref exp run {slug} {e.slug} …</span></div>}
                </div>
              )}
            </div>
          )
        })}
        {!exps.length && (
          <Empty>No experiments yet — <code>reref exp new {slug} 001-… --hypothesis "…"</code> opens the first branch.</Empty>
        )}
      </Section>

      <Modal open={!!adding} title="New experiment" onClose={() => setAdding(null)}>
        <input className="text" autoFocus placeholder="Slug, e.g. 004-dimension-sweep"
               value={adding?.slug || ''}
               onChange={(e) => setAdding({ ...adding, slug: e.target.value })} />
        <input className="text" placeholder="Title"
               value={adding?.title || ''}
               onChange={(e) => setAdding({ ...adding, title: e.target.value })} />
        <textarea placeholder="Hypothesis — what should this branch show?"
                  value={adding?.hypothesis || ''}
                  onChange={(e) => setAdding({ ...adding, hypothesis: e.target.value })} />
        <select className="text" value={adding?.parent || ''}
                onChange={(e) => setAdding({ ...adding, parent: e.target.value || null })}>
          <option value="">No parent (root)</option>
          {exps.map((e) => <option key={e.slug} value={e.slug}>Branch of {e.slug}</option>)}
        </select>
        {err && <div style={{ color: 'var(--bad)', fontSize: 12 }}>{err}</div>}
        <div className="gnode-actions" style={{ marginTop: 0 }}>
          <button className="btn" onClick={save} disabled={!(adding?.slug || '').trim()}>Add experiment</button>
          <button className="btn ghost" onClick={() => setAdding(null)}>Cancel</button>
        </div>
      </Modal>
    </>
  )
}
