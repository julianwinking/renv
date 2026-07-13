import React, { useEffect, useState } from 'react'
import { getPapers, getPaperUsage } from '../api.js'
import { asArray, Stamp, Section, Empty, Mono } from '../ui.jsx'

export default function Papers({ focus }) {
  const [papers, setPapers] = useState(null)
  const [sel, setSel] = useState(focus || null)   // key
  const [usage, setUsage] = useState(null)

  useEffect(() => { if (focus) setSel(focus) }, [focus])

  useEffect(() => {
    let live = true
    getPapers().then((p) => live && setPapers(asArray(p)))
    return () => { live = false }
  }, [])

  useEffect(() => {
    if (!sel) { setUsage(null); return }
    let live = true
    getPaperUsage(sel).then((u) => live && setUsage(u))
    return () => { live = false }
  }, [sel])

  if (!papers) return <div className="loading">reading the store…</div>

  return (
    <>
      <div className="pagehead">
        <h1>Papers</h1>
      </div>
      <div className="grid cols-2">
        <Section title="Corpus" aside={`${papers.length} papers`}>
          {papers.map((p) => (
            <button key={p.key} className="rowbtn" onClick={() => setSel(p.key === sel ? null : p.key)}>
              <div className="row" style={p.key === sel ? { background: 'var(--accent-soft)' } : null}>
                <Mono>{p.key}</Mono>
                <div className="grow">{p.title}</div>
                <span className="faint num">{p.year || ''}</span>
              </div>
            </button>
          ))}
          {!papers.length && (
            <Empty>The corpus is empty — <code>reref add &lt;pdf|arxiv-id|doi&gt;</code> or <code>reref discover "…"</code> brings papers in.</Empty>
          )}
        </Section>

        <Section title="Usage map" aside={sel ? sel : 'No paper selected'}>
          {!sel && <Empty>Select a paper to trace its citations and the log entries that lean on them.</Empty>}
          {sel && usage && (
            <>
              {usage.paper && (
                <div className="detail" style={{ borderTop: 0 }}>
                  <div className="kv"><span className="k">Title</span><span>{usage.paper.title}</span></div>
                  {usage.paper.authors && <div className="kv"><span className="k">Authors</span><span className="muted">{usage.paper.authors}</span></div>}
                  {usage.paper.arxiv && <div className="kv"><span className="k">arXiv</span><Mono>{usage.paper.arxiv}</Mono></div>}
                </div>
              )}
              {(usage.cited_in || []).map((c) => (
                <div className="row" key={c.id}>
                  <Mono>#{c.id}</Mono>
                  <div className="grow">
                    <div className="quote">“{(c.quote || '').slice(0, 160)}{(c.quote || '').length > 160 ? '…' : ''}”</div>
                  </div>
                  <Stamp value={c.support} />
                  <span className="chip">{c.project}</span>
                </div>
              ))}
              {!(usage.cited_in || []).length && (
                <Empty>Not cited yet — <code>reref cite "&lt;claim&gt;" &lt;project&gt;</code> anchors a span from it.</Empty>
              )}
            </>
          )}
        </Section>
      </div>
    </>
  )
}
