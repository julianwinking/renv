import React, { useEffect, useState } from 'react'
import { getProject, getRuns } from '../api.js'
import { asArray, Stamp, Metrics, Section, Empty, Mono, timeAgo, Provenance } from '../ui.jsx'

function Run({ run, defs }) {
  const where = run.remote
    ? run.remote.replace(/^[a-z+]+:\/\//, '').split('/')[0]   // host part
    : 'local'
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

  if (!exps) return <div className="loading">reading the store…</div>

  const byId = Object.fromEntries(exps.map((e) => [e.id, e]))
  const depth = (e) => {
    let d = 0, p = e.parent_id
    while (p && byId[p]) { d += 1; p = byId[p].parent_id }
    return d
  }

  return (
    <>
      <div className="pagehead">
        <h1>Experiments</h1>
        <div className="sub">the branch DAG — one experiment, one question; children branch off their parent</div>
      </div>
      <Section title="Branches" aside={`${exps.length} experiments · ${runs.length} runs`}>
        {exps.map((e) => {
          const eruns = runs.filter((r) => r.experiment === e.slug)
          const isOpen = !!open[e.id]
          return (
            <div key={e.id} id={`exp-${e.slug}`} className={focus === e.slug ? 'flash' : ''}>
              <button className="rowbtn" onClick={() => setOpen({ ...open, [e.id]: !isOpen })}>
                <div className="row" style={{ paddingLeft: 16 + depth(e) * 22 }}>
                  <span className="faint mono">{isOpen ? '▾' : '▸'}</span>
                  <Mono>{e.slug}</Mono>
                  <div className="grow">{e.title}</div>
                  <Metrics defs={defs} metrics={e.metrics} />
                  <Stamp value={e.status} />
                </div>
              </button>
              {isOpen && (
                <div className="detail">
                  {e.hypothesis && (
                    <div className="kv"><span className="k">hypothesis</span><span>{e.hypothesis}</span></div>
                  )}
                  {eruns.length > 0 && (
                    <table className="ledger-t" style={{ marginTop: 8 }}>
                      <thead>
                        <tr><th>run</th><th>status</th><th>metrics</th><th>params</th><th>seed</th><th>provenance</th><th>where</th><th>git</th><th>when</th></tr>
                      </thead>
                      <tbody>{eruns.map((r) => <Run key={r.id} run={r} defs={defs} />)}</tbody>
                    </table>
                  )}
                  {!eruns.length && <div className="muted">no runs yet — <span className="mono">reref exp run {slug} {e.slug} …</span></div>}
                </div>
              )}
            </div>
          )
        })}
        {!exps.length && (
          <Empty>No experiments yet — <code>reref exp new {slug} 001-… --hypothesis "…"</code> opens the first branch.</Empty>
        )}
      </Section>
    </>
  )
}
