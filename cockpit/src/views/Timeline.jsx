import React, { useEffect, useState } from 'react'
import { getProject, addNote, addLog, editLog, editNote, getSources } from '../api.js'
import { asArray, Stamp, Section, Empty, timeAgo } from '../ui.jsx'

// 'result' is deliberately absent: measured numbers enter via runs (§0).
const COMPOSER_TYPES = ['note', 'decision', 'hypothesis', 'observation', 'question', 'feedback', 'blocker']
const FILTERS = ['all', ...COMPOSER_TYPES.filter((t) => t !== 'note'), 'result', 'note']

export default function Timeline({ slug, focus }) {
  const [data, setData] = useState(null)
  const [filter, setFilter] = useState('all')
  const [draft, setDraft] = useState('')
  const [type, setType] = useState('note')
  const [source, setSource] = useState('')
  const [answering, setAnswering] = useState(null)   // question entry being answered
  const [editing, setEditing] = useState(null)        // fkey of the entry being edited
  const [editText, setEditText] = useState('')
  const [err, setErr] = useState(null)

  const [sources, setSources] = useState([])

  const load = () => getProject(slug).then(setData)
  useEffect(() => { setData(null); setAnswering(null); load() }, [slug])
  useEffect(() => { getSources().then((s) => setSources(asArray(s))) }, [slug])
  useEffect(() => {   // deep link from the graph: scroll to one entry
    if (focus && data) {
      requestAnimationFrame(() =>
        document.getElementById(`tl-${focus}`)?.scrollIntoView({ block: 'center' }))
    }
  }, [focus, data])

  if (!data) return <div className="loading">reading the store…</div>

  const entries = [
    ...(data.log || []).map((e) => ({ ...e, kind: e.type, fkey: `log-${e.id}` })),
    ...(data.notes || []).map((n) => ({ ...n, kind: 'note', fkey: `note-${n.id}`,
      raw_body: n.body_md,
      body_md: n.title ? `${n.title}\n${n.body_md}` : n.body_md })),
  ].sort((a, b) => (a.ts < b.ts ? 1 : -1))
  const shown = entries.filter((e) => filter === 'all' || e.kind === filter)

  const save = async () => {
    if (!draft.trim()) return
    setErr(null)
    let r
    if (type === 'note' && !answering) {
      r = await addNote(slug, draft.trim())
    } else {
      const t = type === 'note' ? 'observation' : type   // an answer is a log entry
      r = await addLog(slug, t, draft.trim(), {
        answers: answering ? answering.id : undefined,
        source: type === 'feedback' && source.trim() ? source.trim() : undefined,
      })
    }
    if (r && r.error) { setErr(r.error); return }
    setDraft(''); setSource(''); setAnswering(null)
    load()
  }

  return (
    <>
      <div className="pagehead">
        <h1>Log</h1>
      </div>

      <Section title={answering ? `Answer question #${answering.id}` : 'Add an entry'}>
        <div style={{ padding: '4px 16px 12px' }}>
          {answering && (
            <div className="quote" style={{ marginBottom: 8 }}>
              {answering.body_md}
              <button className="rowbtn" style={{ display: 'inline', width: 'auto', marginLeft: 8, color: 'var(--accent)', cursor: 'pointer' }}
                      onClick={() => setAnswering(null)}>cancel</button>
            </div>
          )}
          {!answering && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
              {COMPOSER_TYPES.map((t) => (
                <button key={t} className={`btn ghost ${type === t ? 'active' : ''}`}
                        style={{ textTransform: 'capitalize',
                                 ...(type === t ? { color: 'var(--accent)', borderColor: 'var(--accent)' } : null) }}
                        onClick={() => setType(t)}>
                  {t}
                </button>
              ))}
            </div>
          )}
          {!answering && type === 'feedback' && (
            <>
              <input className="text" style={{ marginBottom: 6 }}
                     placeholder='Who gave it? e.g. "advisor: Prof. X"'
                     value={source} onChange={(e) => setSource(e.target.value)} />
              {(() => {   // suggest known people so the same person stays one label
                const s = sources.filter((p) =>
                  p.toLowerCase().includes(source.trim().toLowerCase()) && p !== source)
                return s.length ? (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                    {s.slice(0, 8).map((p) => (
                      <button key={p} className="chip" style={{ cursor: 'pointer' }}
                              onClick={() => setSource(p)}>
                        {p}
                      </button>
                    ))}
                  </div>
                ) : null
              })()}
            </>
          )}
          <textarea
            placeholder={
              answering ? 'The answer — cite a run or experiment where it applies…'
              : type === 'question' ? 'An open question — it stays OPEN until a later entry answers it'
              : type === 'feedback' ? 'What did they say?'
              : 'Saved to the store, visible to agents…'
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          {err && <div style={{ color: 'var(--bad)', marginTop: 6 }}>{err}</div>}
          <div className="gnode-actions">
            <button className="btn" onClick={save} disabled={!draft.trim()}>
              {answering ? 'Save answer' : `Save ${type}`}
            </button>
          </div>
        </div>
      </Section>

      <div style={{ height: 14 }} />

      <Section
        title="Entries"
        aside={
          <span>
            {FILTERS.map((t) => (
              <button key={t} className="rowbtn"
                      style={{ display: 'inline', width: 'auto', marginLeft: 10, font: 'inherit',
                               textTransform: 'capitalize',
                               color: filter === t ? 'var(--accent)' : 'inherit', cursor: 'pointer' }}
                      onClick={() => setFilter(t)}>
                {t}
              </button>
            ))}
          </span>
        }
      >
        {shown.map((e) => (
          <div className={`tl-row ${focus === e.fkey ? 'flash' : ''}`} id={`tl-${e.fkey}`} key={e.fkey}>
            <div className="tl-rail">
              <Stamp value={e.kind} tone={e.kind === 'result' ? 'ok' : e.kind === 'blocker' ? 'bad' : 'idle'} />
              {e.kind === 'question' && (
                <span style={{ marginTop: 4 }}>
                  <Stamp value={e.answered_by ? 'answered' : 'open'} tone={e.answered_by ? 'ok' : 'warn'} />
                </span>
              )}
              <span className="when" style={{ marginTop: 4 }}>{timeAgo(e.ts)}</span>
              {e.edited && (
                <span className="when" style={{ marginTop: 2 }} title="last edited">
                  ✎ {timeAgo(e.edited)}
                </span>
              )}
            </div>
            <div className="tl-body">
              {e.source && <div className="faint" style={{ fontSize: 11.5 }}>{e.source}</div>}
              {editing === e.fkey ? (
                <>
                  <textarea value={editText} autoFocus
                            onChange={(ev) => setEditText(ev.target.value)} />
                  <div className="gnode-actions">
                    <button className="btn" onClick={async () => {
                      const r = e.kind === 'note'
                        ? await editNote(e.id, editText)
                        : await editLog(e.id, editText)
                      if (r.error) { setErr(r.error); return }
                      setEditing(null)
                      load()
                    }} disabled={!editText.trim()}>Save edit</button>
                    <button className="btn ghost" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </>
              ) : e.body_md}
              {editing !== e.fkey && (
                <div className="tl-ev">
                  {e.evidence?.runs?.map((r) => <span key={`r${r}`} className="chip">run #{r}</span>)}
                  {e.evidence?.citations?.map((c) => <span key={`c${c}`} className="chip">cite #{c}</span>)}
                  {e.answers && <span className="chip">answers #{e.answers}</span>}
                  {e.kind === 'question' && !e.answered_by && (
                    <button className="btn ghost" style={{ fontSize: 11, padding: '1px 8px' }}
                            onClick={() => { setAnswering(e); document.querySelector('.content')?.scrollTo({ top: 0, behavior: 'smooth' }) }}>
                      Answer…
                    </button>
                  )}
                  <button className="btn ghost" style={{ fontSize: 11, padding: '1px 8px' }}
                          onClick={() => {
                            setEditing(e.fkey)
                            setEditText(e.kind === 'note' ? (e.raw_body ?? e.body_md) : e.body_md)
                          }}>
                    Edit…
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
        {!shown.length && (
          <Empty>Nothing here yet — <code>reref log add {slug} decision "…"</code> writes the first entry.</Empty>
        )}
      </Section>
    </>
  )
}
