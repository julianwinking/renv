import React, { useEffect, useRef, useState } from 'react'
import { getPapers, getPaperAnchors, addPaper, getPaperDocs, createPaperDoc,
         getInbox, markPaperRead } from '../api.js'
import { asArray, Empty, Mono, Modal } from '../ui.jsx'
import PaperViewer from './PaperViewer.jsx'
import NoteDoc from './NoteDoc.jsx'
import {
  LIBRARY, loadWorkspace, openTab, closePane, closeKey, toggleSplit,
  dropTab, pruneViews, renameDoc, activeView, isSplit,
} from '../paperWorkspace.js'

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

// The paper workspace: Library plus a tab per open paper/note. A tab can be
// a split pair (two titles, two panes) so other tabs — and other splits —
// stay available. Presentation state, localStorage per project.
const wsKey = (slug) => `renv-ws-${slug || 'default'}`
const loadRaw = (slug) => {
  try { return JSON.parse(localStorage.getItem(wsKey(slug))) || {} } catch { return {} }
}

function dropSideAt(x, y) {
  const el = document.querySelector('.paper-pane')
  if (!el) return null
  const r = el.getBoundingClientRect()
  if (x < r.left || x > r.right || y < r.top || y > r.bottom) return null
  return x < r.left + r.width / 2 ? 'left' : 'right'
}

function useTabDrag(canDrop, onDrop) {
  const [drag, setDrag] = useState(null)
  const canDropRef = useRef(canDrop)
  const onDropRef = useRef(onDrop)
  const swallow = useRef(false)
  canDropRef.current = canDrop
  onDropRef.current = onDrop

  const onPointerDown = (e, tab) => {
    if (e.button !== 0) return
    if (e.target.closest('.ptab-x, .ptab-split')) return
    const origin = { x: e.clientX, y: e.clientY }
    const st = { tab, moved: false }
    const move = (ev) => {
      if (!st.moved && Math.hypot(ev.clientX - origin.x, ev.clientY - origin.y) < 8) return
      st.moved = true
      document.body.classList.add('ptab-dragging')
      const side = canDropRef.current ? dropSideAt(ev.clientX, ev.clientY) : null
      setDrag({ tab: st.tab, x: ev.clientX, y: ev.clientY, side })
    }
    const up = (ev) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.classList.remove('ptab-dragging')
      if (!st.moved) { setDrag(null); return }
      swallow.current = true
      const side = canDropRef.current ? dropSideAt(ev.clientX, ev.clientY) : null
      setDrag(null)
      if (side) onDropRef.current(st.tab.key, side)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  useEffect(() => () => document.body.classList.remove('ptab-dragging'), [])
  const dragged = () => { if (!swallow.current) return false; swallow.current = false; return true }
  return { drag, onPointerDown, dragged }
}

function EmptyPane({ hot }) {
  return (
    <div className={`pp-empty ${hot ? 'hot' : ''}`}>
      <IconSplit size={22} />
      <div>Drop a tab here</div>
      <div className="faint">Drag another paper or note onto this side</div>
    </div>
  )
}

function WorkspaceTab({ view, selected, onActivate, onClose, onSplit, onPointerDown }) {
  const split = isSplit(view)
  const waiting = split && view.panes.some((p) => !p)
  return (
    <div className={`ptab ${selected ? 'active' : ''} ${split ? 'ptab-pair' : ''}`}
         onClick={() => onActivate(view.id)}
         title={view.panes.filter(Boolean).map((p) => p.title || p.key).join(' | ')}>
      {view.panes.map((pane, i) => (
        pane ? (
          <span key={pane.key} className="ptab-chip"
                onPointerDown={(e) => onPointerDown(e, pane)}>
            {pane.type === 'doc' && <IconNote size={13} />}
            <span className="ptab-name">{pane.title || pane.key}</span>
            <button type="button" className="ptab-x" title="Close"
                    onClick={(e) => { e.stopPropagation(); onClose(view.id, i) }}>✕</button>
          </span>
        ) : (
          <span key="empty" className="ptab-chip ptab-chip-empty">Drop a tab</span>
        )
      ))}
      {(view.panes.length === 1 || waiting) && (
        <button type="button" className={`ptab-split ${waiting ? 'on' : ''}`}
                title={waiting ? 'Cancel split' : 'Split this tab'}
                onClick={(e) => { e.stopPropagation(); onSplit(view.id) }}>
          <IconSplit size={12} />
        </button>
      )}
    </div>
  )
}

export default function Papers({ focus, slug, onMutate }) {
  const [papers, setPapers] = useState(null)
  const [ws, setWs] = useState(() => loadWorkspace(loadRaw(slug)))
  const [ratio, setRatio] = useState(() => Number(localStorage.getItem('renv-pp-ratio')) || 55)
  const insertRefs = useRef({})                     // docId → NoteDoc insert(text)
  const { views, active } = ws
  const current = activeView(ws)
  const split = isSplit(current)

  const load = () => getPapers().then((p) => setPapers(asArray(p)))
  useEffect(() => { load() }, [])

  const slugRef = useRef(slug)
  useEffect(() => {
    if (slugRef.current === slug) return
    slugRef.current = slug
    setWs(loadWorkspace(loadRaw(slug)))
  }, [slug])
  useEffect(() => {
    localStorage.setItem(wsKey(slug), JSON.stringify({ views, active }))
  }, [views, active, slug])
  useEffect(() => {
    if (papers) setWs((w) => pruneViews(w, papers))
  }, [papers])

  const openPaper = (p) => {
    if (typeof p === 'string') p = papers?.find((x) => x.key === p)
    if (!p?.has_pdf) return
    setWs((w) => openTab(w, { type: 'paper', key: p.key, title: p.title }))
  }
  const openDoc = (d) => {
    setWs((w) => openTab(w, { type: 'doc', key: `doc:${d.id}`, title: d.title, docId: d.id }))
  }
  const createDoc = async (p) => {
    const d = await createPaperDoc({ key: p.key, project: slug, title: `Notes — ${p.title || p.key}` })
    if (d && !d.error) { openDoc(d); load() }
  }
  const registerInsert = (docId, fn) => { if (fn) insertRefs.current[docId] = fn; else delete insertRefs.current[docId] }

  useEffect(() => {
    if (focus && papers) {
      const p = papers.find((x) => x.key === focus)
      if (p && p.has_pdf) openPaper(p)
    }
  }, [focus, papers])

  const visible = current ? current.panes.filter(Boolean) : []
  const targetDocTab = visible.find((t) => t.type === 'doc')
  const citeInto = ({ quote, page, fromKey }) => {
    if (!targetDocTab) return
    const block = quote.split('\n').map((l) => `> ${l}`).join('\n')
    const md = `\n${block}\n> — ${fromKey}${page ? `, p.${page}` : ''}\n`
    insertRefs.current[targetDocTab.docId]?.(md)
  }

  const { drag, onPointerDown, dragged } = useTabDrag(
    active !== LIBRARY, (key, side) => setWs((w) => dropTab(w, side, key)))

  const startSplitResize = (e) => {
    e.preventDefault()
    const pane = e.currentTarget.parentElement
    const rect = pane.getBoundingClientRect()
    let r = ratio
    const move = (ev) => { r = Math.min(75, Math.max(25, ((ev.clientX - rect.left) / rect.width) * 100)); setRatio(r) }
    const up = () => {
      window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up)
      localStorage.setItem('renv-pp-ratio', String(r))
    }
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
  }

  if (!papers) return <div className="loading">reading the store…</div>

  const openKeys = views.flatMap((v) => v.panes.filter(Boolean).map((p) => p.key))
  const renderPane = (pane, hot) => {
    if (!pane) return <EmptyPane hot={hot} />
    if (pane.type === 'paper')
      return <PaperViewer key={pane.key} paperKey={pane.key} title={pane.title} project={slug} embedded
                          onClose={() => setWs((w) => closeKey(w, pane.key))}
                          onMutate={() => { onMutate && onMutate(); load() }}
                          onCite={(p) => citeInto({ ...p, fromKey: pane.key })}
                          citeTargetTitle={targetDocTab && targetDocTab.key !== pane.key ? targetDocTab.title : null} />
    return <NoteDoc key={pane.key} docId={pane.docId} project={slug} registerInsert={registerInsert}
                    onClose={() => setWs((w) => closeKey(w, pane.key))} onMutate={load}
                    onTitle={(id, title) => setWs((w) => renameDoc(w, id, title))} />
  }

  return (
    <div className="paper-ws">
      <div className="paper-tabs">
        <button className={`ptab ${active === LIBRARY ? 'active' : ''}`}
                onClick={() => setWs((w) => ({ ...w, active: LIBRARY }))}>
          <IconDatabase size={14} style={{ marginLeft: 1 }} /> Library
          <span className="ptab-count">{papers.length}</span>
        </button>
        {views.map((v) => (
          <WorkspaceTab key={v.id} view={v} selected={active === v.id}
                        onActivate={(id) => { if (dragged()) return; setWs((w) => ({ ...w, active: id })) }}
                        onClose={(id, i) => setWs((w) => closePane(w, id, i))}
                        onSplit={(id) => setWs((w) => toggleSplit(w, id))}
                        onPointerDown={onPointerDown} />
        ))}
      </div>

      <div className="paper-pane">
        {active === LIBRARY ? (
          <div className="pp-pane" style={{ flex: 1 }}>
            <Library papers={papers} project={slug} onOpen={openPaper} openKeys={openKeys}
                     onAdded={load} onOpenDoc={openDoc} onCreateDoc={createDoc} />
          </div>
        ) : (
          (current?.panes || []).map((pane, i) => (
            <React.Fragment key={pane?.key || `empty-${i}`}>
              {i > 0 && <div className="pp-divider" onMouseDown={startSplitResize} title="Drag to resize" />}
              <div className="pp-pane" style={split && i === 0 ? { flexBasis: `${ratio}%`, flexGrow: 0 } : { flex: 1 }}>
                {renderPane(pane, !!(drag && ((i === 0 && drag.side === 'left') || (i === 1 && drag.side === 'right'))))}
              </div>
            </React.Fragment>
          ))
        )}
        {drag && active !== LIBRARY && (
          <div className="pp-dz-wrap">
            <div className={`pp-dz ${drag.side === 'left' ? 'hot' : ''}`}>
              <span>{split && !current?.panes[0] ? 'Drop here' : 'Split left'}</span>
            </div>
            <div className={`pp-dz right ${drag.side === 'right' ? 'hot' : ''}`}>
              <span>{split && !current?.panes[1] ? 'Drop here' : 'Split right'}</span>
            </div>
          </div>
        )}
      </div>
      {drag && (
        <div className="ptab-ghost" style={{ left: drag.x + 12, top: drag.y + 8 }}>
          {drag.tab.type === 'doc' && <IconNote size={13} />}
          {drag.tab.title || drag.tab.key}
        </div>
      )}
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
