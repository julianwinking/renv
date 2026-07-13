import React, { useEffect, useState } from 'react'
import { getProject, getClaim } from '../api.js'
import { Stamp, Section, Empty, Mono } from '../ui.jsx'

export default function Claims({ slug }) {
  const [claims, setClaims] = useState(null)
  const [detail, setDetail] = useState({})

  useEffect(() => {
    let live = true
    getProject(slug).then((d) => live && setClaims(d.claims))
    return () => { live = false }
  }, [slug])

  const toggle = async (id) => {
    if (detail[id]) { setDetail({ ...detail, [id]: null }); return }
    const full = await getClaim(id)
    setDetail((d) => ({ ...d, [id]: full }))
  }

  if (!claims) return <div className="loading">reading the store…</div>

  return (
    <>
      <div className="pagehead">
        <h1>Claims</h1>
        <div className="sub">every assertion traces to evidence; status is derived, never hand-set</div>
      </div>
      <Section title="Claim ledger" aside={`${claims.length} claims`}>
        {claims.map((c) => (
          <div key={c.id}>
            <button className="rowbtn" onClick={() => toggle(c.id)}>
              <div className="row">
                <Mono>#{c.id}</Mono>
                <Stamp value={c.status} />
                <div className="grow">{c.text}</div>
                <span className="chip">{c.kind}</span>
              </div>
            </button>
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
                  <div className="muted">no evidence linked — <span className="mono">reref claim link {c.id} --run N</span></div>
                )}
              </div>
            )}
          </div>
        ))}
        {!claims.length && (
          <Empty>No claims yet — <code>reref claim add {slug} "…" --kind thesis</code> states what the runs must prove.</Empty>
        )}
      </Section>
    </>
  )
}
