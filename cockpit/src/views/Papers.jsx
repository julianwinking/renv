import React, { useEffect, useRef, useState } from 'react'
import { getPapers, getPaperAnchors, addPaper, getPaperDocs, createPaperDoc,
         getInbox, markPaperRead } from '../api.js'
import { asArray, Empty, Mono, Modal } from '../ui.jsx'
import PaperViewer from './PaperViewer.jsx'
import NoteDoc from './NoteDoc.jsx'

// Lucide-style line icons (rounded, 2px stroke, currentColor).
const Ico = ({ size = 15, children, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
       style={{ flexShrink: 0 }} {...p}>{children}</svg>
)
const IconDatabase = (p) => (
  <Ico {...p}><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5" /><path d="M3 12a9 3 0 0 0 18 0" /></Ico>
)
const IconColumns = (p) => (
  <Ico {...p}><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M9 3v18" /><path d="M15 3v18" /></Ico>
)
const IconSort = (p) => (
  <Ico {...p}><path d="m21 16-4 4-4-4" /><path d="M17 20V4" /><path d="m3 8 4-4 4 4" /><path d="M7 4v16" /></Ico>
)
const IconFilter = (p) => (
  <Ico {...p}><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" /></Ico>
)
const IconNote = (p) => (
  <Ico {...p}><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z" /></Ico>
)
const IconSplit = (p) => (
  <Ico {...p}><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M12 3v18" /></Ico>
)

// The paper workspace: a Library tab listing the corpus; papers and note
// documents open as their own tabs (inline, not popups), and any two tabs can
// sit side-by-side in a split so you read the PDF while writing the note.
// the workspace (open tabs, active tab, split) survives refreshes and view
// switches — presentation state, so localStorage per project, house pattern
const wsKey = (slug) => `renv-ws-${slug || 'default'}`
const loadWs = (slug) => {
  try { return JSON.parse(localStorage.getItem(wsKey(slug))) || {} } catch { return {} }
}

export default function Papers({ focus, slug, onMutate }) {
  const [papers, setPapers] = useState(null)
  const [tabs, setTabs] = useState(() => loadWs(slug).tabs || [])
  const [active, setActive] = useState(() => loadWs(slug).active || 'library')
  const [split, setSplit] = useState(() => loadWs(slug).split || null)
  const [ratio, setRatio] = useState(() => Number(localStorage.getItem('renv-pp-ratio')) || 55)
  const [dragKey, setDragKey] = useState(null)      // tab being dragged (for split drop zones)
  const insertRefs = useRef({})                     // docId → NoteDoc insert(text)

  const load = () => getPapers().then((p) => setPapers(asArray(p)))
  useEffect(() => { load() }, [])

  // switching projects swaps in that project's saved workspace
  const slugRef = useRef(slug)
  useEffect(() => {
    if (slugRef.current === slug) return
    slugRef.current = slug
    const ws = loadWs(slug)
    setTabs(ws.tabs || []); setActive(ws.active || 'library'); setSplit(ws.split || null)
  }, [slug])
  useEffect(() => {
    localStorage.setItem(wsKey(slug), JSON.stringify({ tabs, active, split }))
  }, [tabs, active, split, slug])
  // drop restored paper tabs whose PDF has left the corpus
  useEffect(() => {
    if (!papers) return
    setTabs((t) => t.filter((x) => x.type !== 'paper' || papers.some((p) => p.key === x.key && p.has_pdf)))
  }, [papers])
  useEffect(() => {                                 // keep active/split pointing at live tabs
    if (active !== 'library' && !tabs.some((t) => t.key === active)) setActive('library')
    if (split && !tabs.some((t) => t.key === split)) setSplit(null)
  }, [tabs])

  const openPaper = (p) => {
    if (!p.has_pdf) return
    setTabs((t) => (t.some((x) => x.key === p.key) ? t : [...t, { type: 'paper', key: p.key, title: p.title }]))
    setActive(p.key)
  }
  const openDoc = (d) => {
    const key = `doc:${d.id}`
    setTabs((t) => (t.some((x) => x.key === key) ? t : [...t, { type: 'doc', key, title: d.title, docId: d.id }]))
    setActive(key)
  }
  const createDoc = async (p) => {
    const d = await createPaperDoc({ key: p.key, project: slug, title: `Notes — ${p.title || p.key}` })
    if (d && !d.error) { openDoc(d); load() }
  }
  const closeTab = (key, e) => {
    e?.stopPropagation()
    setTabs((t) => t.filter((x) => x.key !== key))
    setSplit((s) => (s === key ? null : s))
    setActive((a) => (a === key ? 'library' : a))
  }
  const renameTab = (docId, title) => setTabs((t) => t.map((x) => (x.docId === docId ? { ...x, title } : x)))
  const registerInsert = (docId, fn) => { if (fn) insertRefs.current[docId] = fn; else delete insertRefs.current[docId] }

  useEffect(() => {
    if (focus && papers) {
      const p = papers.find((x) => x.key === focus)
      if (p && p.has_pdf) openPaper(p)
    }
  }, [focus, papers])

  // the cite target is a note-doc currently visible in a pane
  const visibleKeys = split ? [active, split] : [active]
  const targetDocTab = visibleKeys.map((k) => tabs.find((t) => t.key === k)).find((t) => t && t.type === 'doc')

  const citeInto = ({ quote, page, fromKey }) => {
    if (!targetDocTab) return
    const block = quote.split('\n').map((l) => `> ${l}`).join('\n')
    const md = `\n${block}\n> — ${fromKey}${page ? `, p.${page}` : ''}\n`
    insertRefs.current[targetDocTab.docId]?.(md)
  }

  const startSplitResize = (e) => {
    e.preventDefault()
    const pane = e.currentTarget.parentElement
    const rect = pane.getBoundingClientRect()
    let r = ratio
    // neither pane may drop below a quarter of the split width
    const move = (ev) => { r = Math.min(75, Math.max(25, ((ev.clientX - rect.left) / rect.width) * 100)); setRatio(r) }
    const up = () => {
      window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up)
      localStorage.setItem('renv-pp-ratio', String(r))
    }
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
  }

  if (!papers) return <div className="loading">reading the store…</div>

  const renderContent = (key) => {
    if (key === 'library')
      return <Library papers={papers} project={slug} onOpen={openPaper}
                      openKeys={tabs.map((t) => t.key)} onAdded={load}
                      onOpenDoc={openDoc} onCreateDoc={createDoc} />
    const tab = tabs.find((t) => t.key === key)
    if (!tab) return null
    if (tab.type === 'paper')
      return <PaperViewer key={key} paperKey={tab.key} title={tab.title} project={slug} embedded
                          onClose={() => closeTab(key)} onMutate={() => { onMutate && onMutate(); load() }}
                          onCite={(p) => citeInto({ ...p, fromKey: tab.key })}
                          citeTargetTitle={targetDocTab && targetDocTab.key !== key ? targetDocTab.title : null} />
    return <NoteDoc key={key} docId={tab.docId} project={slug} registerInsert={registerInsert}
                    onClose={() => closeTab(key)} onMutate={load} onTitle={renameTab} />
  }

  return (
    <div className="paper-ws">
      <div className="paper-tabs">
        <button className={`ptab ${active === 'library' ? 'active' : ''}`} onClick={() => setActive('library')}>
          <IconDatabase size={14} style={{ marginLeft: 1 }} /> Library
          <span className="ptab-count">{papers.length}</span>
        </button>
        {tabs.map((t) => (
          <button key={t.key} className={`ptab ${active === t.key ? 'active' : ''} ${split === t.key ? 'split' : ''}`}
                  onClick={() => setActive(t.key)} title={t.title || t.key}
                  draggable onDragStart={() => setDragKey(t.key)} onDragEnd={() => setDragKey(null)}>
            {t.type === 'doc' && <IconNote size={13} />}
            <span className="ptab-name">{t.title || t.key}</span>
            {t.key !== active && (
              <span className="ptab-split" title="Open in split view"
                    onClick={(e) => { e.stopPropagation(); setSplit(split === t.key ? null : t.key) }}>
                <IconSplit size={12} />
              </span>
            )}
            <span className="ptab-x" onClick={(e) => closeTab(t.key, e)} title="Close tab">✕</span>
          </button>
        ))}
      </div>

      <div className="paper-pane">
        <div className="pp-pane" style={split ? { flexBasis: `${ratio}%`, flexGrow: 0 } : { flex: 1 }}>
          {renderContent(active)}
        </div>
        {split && (
          <>
            <div className="pp-divider" onMouseDown={startSplitResize} title="Drag to resize" />
            <div className="pp-pane" style={{ flex: 1 }}>
              {renderContent(split)}
            </div>
          </>
        )}
        {dragKey && (
          <div className="pp-dz-wrap">
            <div className="pp-dz" onDragOver={(e) => e.preventDefault()}
                 onDrop={() => { setActive(dragKey); setDragKey(null) }}>
              <span>Open here</span>
            </div>
            <div className="pp-dz right" onDragOver={(e) => e.preventDefault()}
                 onDrop={() => { if (dragKey !== active) setSplit(dragKey); setDragKey(null) }}>
              <span>Split →</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const COLS = [['authors', 'Authors'], ['year', 'Year'], ['notes', 'Notes'], ['cited', 'Cited']]
const SORT_FIELDS = [['title', 'Title'], ['added', 'Added'], ['year', 'Year'], ['notes', 'Notes'], ['cited', 'Cited']]
const ATTRS = [['title', 'Title'], ['authors', 'Authors'], ['year', 'Year'], ['key', 'Key']]

function Library({ papers, project, onOpen, openKeys, onAdded, onOpenDoc, onCreateDoc }) {
  const [cols, setCols] = useState({ authors: true, year: true, notes: true, cited: true })
  const [sort, setSort] = useState({ key: 'title', dir: 'asc' })
  const [filters, setFilters] = useState([])
  const [menu, setMenu] = useState(null)
  const [attrQ, setAttrQ] = useState('')
  const [expanded, setExpanded] = useState({})     // key -> { notes, docs } | 'loading'
  const [adding, setAdding] = useState(false)
  const [src, setSrc] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const match = (p, f) => {
    const v = (f.value || '').trim().toLowerCase()
    if (!v) return true
    if (f.attr === 'authors') return (p.authors || []).join(' ').toLowerCase().includes(v)
    if (f.attr === 'year') return String(p.year || '').includes(v)
    if (f.attr === 'key') return (p.key || '').toLowerCase().includes(v)
    return (p.title || '').toLowerCase().includes(v)
  }
  const shown = papers
    .filter((p) => filters.every((f) => match(p, f)))
    .sort((a, b) => {
      let r
      if (sort.key === 'year') r = (a.year || 0) - (b.year || 0)
      else if (sort.key === 'added') r = (a.added || '').localeCompare(b.added || '')
      else if (sort.key === 'notes') r = (a.note_count || 0) - (b.note_count || 0)
      else if (sort.key === 'cited') r = (a.cite_count || 0) - (b.cite_count || 0)
      else r = (a.title || a.key).localeCompare(b.title || b.key)
      return sort.dir === 'desc' ? -r : r
    })
  const sortLabel = (SORT_FIELDS.find(([k]) => k === sort.key) || SORT_FIELDS[0])[1]
  const colSpan = 1 + COLS.filter(([k]) => cols[k]).length

  const toggle = async (p, e) => {
    e.stopPropagation()
    if (expanded[p.key] !== undefined) { setExpanded(({ [p.key]: _, ...rest }) => rest); return }
    setExpanded((x) => ({ ...x, [p.key]: 'loading' }))
    const [a, docs] = await Promise.all([getPaperAnchors(p.key, project), getPaperDocs(p.key, project)])
    setExpanded((x) => ({ ...x, [p.key]: { notes: a.notes || [], docs: asArray(docs) } }))
  }

  const doAdd = async () => {
    if (!src.trim()) return
    setBusy(true); setErr(null)
    const r = await addPaper(src.trim())
    setBusy(false)
    if (r && r.error) { setErr(r.error); return }
    setAdding(false); setSrc(''); onAdded && onAdded()
  }

  // the reading inbox: papers an agent (or the reference popup) added that no
  // human has read yet — refreshed whenever the library itself refreshes
  const [inbox, setInbox] = useState([])
  useEffect(() => { getInbox().then((r) => setInbox(asArray(r))) }, [papers])
  const readDone = async (key) => {
    await markPaperRead(key)
    setInbox((x) => x.filter((p) => p.key !== key))
  }

  return (
    <div className="lib-wrap">
      {inbox.length > 0 && (
        <div className="lib-inbox">
          <div className="lib-inbox-h">
            Inbox — added but not yet read by you <span className="num">{inbox.length}</span>
          </div>
          {inbox.map((p) => (
            <div key={p.key} className="lib-inbox-row">
              <span className="lib-inbox-title" onClick={() => onOpen(p.key, p.title || p.key)}>
                {p.title || p.key}
              </span>
              <span className="faint num">{p.key}</span>
              <button className="btn ghost" onClick={() => onOpen(p.key, p.title || p.key)}>Open</button>
              <button className="btn" onClick={() => readDone(p.key)}>Mark read</button>
            </div>
          ))}
        </div>
      )}
      <div className="lib-toolbar">
        <div className="lib-tg">
          <button className={`lib-tool ${menu === 'columns' ? 'on' : ''}`}
                  onClick={() => setMenu(menu === 'columns' ? null : 'columns')}><IconColumns /> Columns</button>
          {menu === 'columns' && (
            <div className="lib-menu">
              <div className="lib-menuhead">Show columns</div>
              {COLS.map(([k, l]) => (
                <label key={k} className="lib-menurow">
                  <input type="checkbox" checked={cols[k]} onChange={() => setCols({ ...cols, [k]: !cols[k] })} />{l}
                </label>
              ))}
            </div>
          )}
        </div>

        <div className="lib-tg">
          <button className={`lib-tool ${menu === 'sort' ? 'on' : ''}`}
                  onClick={() => setMenu(menu === 'sort' ? null : 'sort')}>
            <IconSort /> Sorted by <span className="faint">{sortLabel}</span>
          </button>
          {menu === 'sort' && (
            <div className="lib-menu">
              {SORT_FIELDS.map(([k, l]) => (
                <button key={k} className={`lib-menurow ${sort.key === k ? 'on' : ''}`}
                        onClick={() => setSort({ ...sort, key: k })}>
                  <span className="lib-check">{sort.key === k ? '✓' : ''}</span>{l}
                </button>
              ))}
              <div className="lib-menusep" />
              <button className="lib-menurow" onClick={() => setSort({ ...sort, dir: sort.dir === 'asc' ? 'desc' : 'asc' })}>
                <span className="lib-check" />{sort.dir === 'asc' ? 'Ascending ↑' : 'Descending ↓'}
              </button>
            </div>
          )}
        </div>

        <div className="lib-tg">
          <button className={`lib-tool ${menu === 'filter' ? 'on' : ''}`}
                  onClick={() => setMenu(menu === 'filter' ? null : 'filter')}><IconFilter /> Filter</button>
          {menu === 'filter' && (
            <div className="lib-menu">
              <input className="lib-attrsearch" autoFocus placeholder="Search attributes…"
                     value={attrQ} onChange={(e) => setAttrQ(e.target.value)} />
              {ATTRS.filter(([, l]) => l.toLowerCase().includes(attrQ.toLowerCase())).map(([k, l]) => (
                <button key={k} className="lib-menurow"
                        onClick={() => { setFilters([...filters, { attr: k, value: '' }]); setMenu(null); setAttrQ('') }}>
                  <span className="lib-check" />{l}
                </button>
              ))}
            </div>
          )}
        </div>

        <span className="lib-count">{shown.length}{shown.length !== papers.length ? ` / ${papers.length}` : ''} papers</span>
        <button className="gtool" onClick={() => setAdding(true)}>+ Add</button>
      </div>

      {filters.length > 0 && (
        <div className="lib-filters">
          {filters.map((f, i) => (
            <span key={i} className="lib-fchip">
              <span className="faint">{(ATTRS.find(([k]) => k === f.attr) || [])[1]}:</span>
              <input value={f.value} autoFocus placeholder="value…"
                     onChange={(e) => { const nf = [...filters]; nf[i] = { ...f, value: e.target.value }; setFilters(nf) }} />
              <button onClick={() => setFilters(filters.filter((_, j) => j !== i))}>✕</button>
            </span>
          ))}
        </div>
      )}

      {menu && <div className="lib-backdrop" onClick={() => setMenu(null)} />}

      {!papers.length ? (
        <div style={{ padding: 24 }}>
          <Empty>The corpus is empty — <code>renv add &lt;pdf|arxiv-id|doi&gt;</code> or the <b>+ Add</b> button brings papers in.</Empty>
        </div>
      ) : (
        <div className="lib-scroll">
          <table className="lib-t">
            <thead>
              <tr>
                <th>Title</th>
                {cols.authors && <th>Authors</th>}
                {cols.year && <th className="num">Year</th>}
                {cols.notes && <th className="num">Notes</th>}
                {cols.cited && <th className="num">Cited</th>}
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => {
                const authors = p.authors || []
                const ex = expanded[p.key]
                return (
                  <React.Fragment key={p.key}>
                    <tr className={p.has_pdf ? 'openable' : ''} onClick={() => onOpen(p)}>
                      <td>
                        <div className="lib-first">
                          <span className={`lib-ico ${ex !== undefined ? 'open' : ''}`}
                                onClick={(e) => toggle(p, e)} title="Show notes, questions & note documents">
                            <svg className="lib-doc" viewBox="0 0 24 24" width="15" height="15" fill="none"
                                 stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
                              <path d="M6 3h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
                              <path d="M14 3v4h4" />
                            </svg>
                            <svg className="lib-chev" viewBox="0 0 24 24" width="17" height="17" fill="none"
                                 stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M9 5l7 7-7 7" />
                            </svg>
                          </span>
                          <span className="lib-titlecol">
                            <div className="lib-title">{p.title || <span className="faint">untitled</span>}</div>
                            <Mono>{p.key}</Mono>
                          </span>
                        </div>
                      </td>
                      {cols.authors && (
                        <td className="lib-auth">{authors.slice(0, 2).join(', ')}{authors.length > 2 ? ' et al.' : ''}</td>
                      )}
                      {cols.year && <td className="num faint">{p.year || '—'}</td>}
                      {cols.notes && <td className="num">{p.note_count ? <span className="chip">✎ {p.note_count}</span> : <span className="faint">—</span>}</td>}
                      {cols.cited && <td className="num faint">{p.cite_count || '—'}</td>}
                    </tr>
                    {ex !== undefined && (
                      <tr className="lib-expand">
                        <td colSpan={colSpan}>
                          {ex === 'loading' ? (
                            <div className="lib-anno-empty">loading…</div>
                          ) : (
                            <>
                              {ex.notes.map((n) => (
                                <div key={`n${n.id}`} className="lib-anno" onClick={() => onOpen(p)}>
                                  <span className={`pv-kindtag pv-kt-${n.kind || 'note'}`}>{(n.kind || 'note') === 'note' ? 'annotation' : n.kind}</span>
                                  <span className="lib-anno-q">“{(n.quote || '').slice(0, 90)}{(n.quote || '').length > 90 ? '…' : ''}”</span>
                                  {n.body_md && <span className="lib-anno-b">{n.body_md}</span>}
                                </div>
                              ))}
                              {ex.docs.map((d) => (
                                <div key={`d${d.id}`} className="lib-anno lib-docrow" onClick={() => onOpenDoc(d)}>
                                  <IconNote size={14} /><span className="lib-anno-b">{d.title}</span>
                                </div>
                              ))}
                              {!ex.notes.length && !ex.docs.length && (
                                <div className="lib-anno-empty">No notes, questions, or hypotheses on this paper yet.</div>
                              )}
                              <button className="lib-createnote" onClick={() => onCreateDoc(p)}>
                                <IconNote size={14} /> Create note
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={adding} title="Add a paper" onClose={() => setAdding(false)}>
        <input className="text" autoFocus placeholder="arXiv id, DOI, or path to a PDF"
               value={src} onChange={(e) => setSrc(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') doAdd() }} />
        <div className="faint" style={{ fontSize: 12 }}>
          arXiv id downloads the PDF · DOI fetches metadata · a file path copies it into <span className="mono">library/</span>.
        </div>
        {err && <div style={{ color: 'var(--bad)', fontSize: 12 }}>{err}</div>}
        <div className="gnode-actions" style={{ marginTop: 0 }}>
          <button className="btn" onClick={doAdd} disabled={busy || !src.trim()}>{busy ? 'Adding…' : 'Add paper'}</button>
          <button className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      </Modal>
    </div>
  )
}
