// The control surface: edit the files agents actually read (AGENTS.md, the
// project templates), project settings, and metric definitions. Saving writes
// the real files/rows — an agent picks the instructions up at its next session
// start. What is deliberately NOT here: CLI/MCP tool prompts (they are code;
// their designed control point IS AGENTS.md) and the review rubric (hardcoded
// in review.py today — shown read-only until it moves to data).
import React, { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import {
  getConfigFiles, getConfigFile, saveConfigFile, getMetricDefs, defineMetric,
  saveProjectSettings, getRubric, getRemotes, addRemote,
} from '../api.js'
import { FileTree, filesToTree } from '../FileTree.jsx'
import { navigate, routePath } from '../nav.js'
import { asArray, Stamp, Section, Empty, Mono } from '../ui.jsx'

const MarkdownEditor = lazy(() => import('./MarkdownEditor.jsx'))

// Live markdown can throw on a construct the parser doesn't know. Fall back
// to the monospace textarea rather than taking down the whole admin view.
class MdBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) { return { error } }
  componentDidCatch() { this.props.onError?.() }
  render() {
    if (this.state.error) return this.props.fallback
    return this.props.children
  }
}

function FileEditor({ scopes, slug, view, focus, rootLabel, strip }) {
  const [files, setFiles] = useState(null)
  const [sel, setSel] = useState(null)          // listing row
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [ready, setReady] = useState(null)      // sel.path whose contents are loaded
  const [mdCrash, setMdCrash] = useState(false)
  const [msg, setMsg] = useState(null)
  const [treeW, setTreeW] = useState(() => Number(localStorage.getItem('renv-cfg-tree')) || 220)
  const contentRef = useRef('')
  const selRef = useRef(null)
  const dirtyRef = useRef(false)
  const saveTimer = useRef(0)
  selRef.current = sel
  dirtyRef.current = dirty

  useEffect(() => {
    let live = true
    getConfigFiles(slug).then((all) => {
      if (!live) return
      const mine = asArray(all).filter((f) => scopes.includes(f.scope))
      setFiles(mine)
      const want = focus && mine.find((f) => f.path === focus || f.name === focus)
      setSel((cur) => {
        if (want) return want
        if (cur && mine.some((f) => f.path === cur.path)) {
          return mine.find((f) => f.path === cur.path) || cur
        }
        return mine[0] || null
      })
    })
    return () => { live = false }
  }, [slug, scopes, focus])

  useEffect(() => {
    if (!sel) return
    setReady(null)
    setMdCrash(false)
    let live = true
    getConfigFile(sel.scope, sel.name, sel.project).then((r) => {
      if (!live) return
      const text = r.content ?? ''
      contentRef.current = text
      setContent(text)
      setDirty(false)
      setMsg(null)
      setReady(sel.path)
    })
    return () => { live = false }
  }, [sel])

  const tree = useMemo(() => filesToTree(files || [], { strip }), [files, strip])

  const saveNow = async (row = selRef.current, text = contentRef.current) => {
    if (!row) return
    setSaving(true)
    const r = await saveConfigFile(row.scope, row.name, text, row.project)
    setSaving(false)
    if (r.error) { setMsg({ bad: true, text: r.error }); return }
    if (selRef.current && row.path === selRef.current.path) setDirty(false)
  }

  const onEdit = (text) => {
    contentRef.current = text
    setContent(text)
    setDirty(true)
    clearTimeout(saveTimer.current)
    const row = selRef.current
    saveTimer.current = setTimeout(() => saveNow(row, text), 700)
  }

  const openFile = (row) => {
    if (!row || (sel && row.path === sel.path)) return
    clearTimeout(saveTimer.current)
    if (dirty && sel) saveNow(sel, contentRef.current)
    setSel(row)
    if (slug && view) navigate(routePath(slug, view, row.path))
  }

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        clearTimeout(saveTimer.current)
        saveNow()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => () => {
    clearTimeout(saveTimer.current)
    if (dirtyRef.current && selRef.current) {
      saveConfigFile(selRef.current.scope, selRef.current.name,
                     contentRef.current, selRef.current.project)
    }
  }, [])

  const startTreeResize = (e) => {
    e.preventDefault()
    const x0 = e.clientX, w0 = treeW
    let w = w0
    const move = (ev) => { w = Math.min(360, Math.max(140, w0 + ev.clientX - x0)); setTreeW(w) }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      localStorage.setItem('renv-cfg-tree', String(w))
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  if (!files) return <div className="loading">reading files…</div>

  const isMd = sel && /\.md$/i.test(sel.name)
  const useLive = isMd && !mdCrash && ready === sel.path
  const sourceArea = (
    <textarea
      className="fileedit"
      value={content}
      onChange={(e) => onEdit(e.target.value)}
      spellCheck={false}
    />
  )

  return (
    <div className="tx">
      <div className="tx-files" style={{ width: treeW }}>
        <div className="tx-chrome">
          <span className="tx-title">{rootLabel}</span>
        </div>
        <FileTree tree={tree} active={sel?.path}
                  onOpen={(n) => { if (n.kind === 'file' && n.file) openFile(n.file) }} />
        <div className="tx-files-resize" onMouseDown={startTreeResize} />
      </div>
      <div className="tx-mid">
        <div className="tx-chrome">
          <span className="tx-title" title={sel?.path}>{sel?.path || ''}</span>
          {sel && (
            <span className="tx-status">{saving ? 'saving…' : dirty ? 'unsaved' : 'saved'}</span>
          )}
          {sel && (
            <div className="tx-chrome-actions">
              <button className="tx-tool primary" onClick={() => { clearTimeout(saveTimer.current); saveNow() }}
                      disabled={!dirty || saving}>Save</button>
            </div>
          )}
        </div>
        {sel && (
          <>
            {mdCrash && (
              <div className="tx-err">Live preview could not open this file — editing as source.</div>
            )}
            {msg && (
              <div className={`tx-err ${msg.bad ? '' : 'ok'}`}>{msg.text}</div>
            )}
            <div className={`tx-fileedit-wrap${useLive ? ' md' : ''}`}>
              {ready !== sel.path ? (
                <div className="loading" style={{ padding: 20 }}>reading file…</div>
              ) : useLive ? (
                <MdBoundary onError={() => setMdCrash(true)} fallback={sourceArea}>
                  <Suspense fallback={<div className="loading" style={{ padding: 20 }}>loading editor…</div>}>
                    <MarkdownEditor
                      key={sel.path}
                      markdown={content}
                      onChange={onEdit}
                      onError={({ error }) => setMsg({ bad: true, text: `${error} — switch to Source to edit.` })}
                      className="tx-mdx-root"
                      contentEditableClassName="tx-mdx"
                      spellCheck={false}
                      placeholder="Write in markdown. Shortcuts: # heading, **bold**, - list, > quote."
                    />
                  </Suspense>
                </MdBoundary>
              ) : sourceArea}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const INSTR_SCOPES = ['env', 'project']
const TMPL_SCOPES = ['writing', 'template']

export function Instructions({ slug, focus }) {
  return (
    <FileEditor
      scopes={INSTR_SCOPES} slug={slug} view="instructions" focus={focus}
      rootLabel="."
    />
  )
}

export function Templates({ slug, focus }) {
  return (
    <FileEditor
      scopes={TMPL_SCOPES} slug={slug} view="templates" focus={focus}
      rootLabel="templates/" strip="templates"
    />
  )
}

const DIRS = { maximize: '↑ Higher is better', minimize: '↓ Lower is better', info: '· Informational' }

export function Settings({ slug, project, onMutate }) {
  const [title, setTitle] = useState(project?.title || '')
  const [status, setStatus] = useState(project?.status || 'active')
  const [defs, setDefs] = useState(null)
  const [draft, setDraft] = useState(null)      // metric being edited/created
  const [remotes, setRemotes] = useState(null)
  const [rdraft, setRdraft] = useState(null)    // remote being edited/created
  const [rubric, setRubric] = useState(null)
  const [showRubric, setShowRubric] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => { setTitle(project?.title || ''); setStatus(project?.status || 'active') }, [project])
  useEffect(() => {
    getMetricDefs().then(setDefs)
    getRemotes().then((r) => setRemotes(asArray(r)))
  }, [])

  const saveRemote = async () => {
    const r = await addRemote(rdraft)
    if (r.error) { setMsg({ bad: true, text: r.error }); return }
    setRdraft(null)
    setRemotes(await getRemotes())
  }

  const saveSettings = async () => {
    const r = await saveProjectSettings(slug, { title, status })
    setMsg(r.error ? { bad: true, text: r.error } : { text: 'project settings saved' })
    if (!r.error && onMutate) onMutate()
  }

  const saveMetric = async () => {
    const r = await defineMetric(draft)
    if (r.error) { setMsg({ bad: true, text: r.error }); return }
    setDraft(null)
    setDefs(await getMetricDefs())
  }

  return (
    <>
      <div className="pagehead">
        <h1>Settings</h1>
      </div>

      <Section title="Project" aside={slug}>
        <div style={{ padding: '4px 16px 14px', display: 'grid', gap: 8, maxWidth: 480 }}>
          <input className="text" placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <select className="text" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
          {msg && <div style={{ color: msg.bad ? 'var(--bad)' : 'var(--ok)', fontSize: 12 }}>{msg.text}</div>}
          <div className="gnode-actions" style={{ marginTop: 0 }}>
            <button className="btn" onClick={saveSettings}>Save settings</button>
          </div>
        </div>
      </Section>

      <div style={{ height: 14 }} />

      <Section title="Metric definitions"
               aside={<button className="rowbtn" style={{ display: 'inline', width: 'auto', color: 'var(--accent)', cursor: 'pointer' }}
                              onClick={() => setDraft({ direction: 'maximize', fmt: '.3f' })}>+ Define metric</button>}>
        {defs && Object.values(defs).map((d) => (
          <div className="row" key={d.name}>
            <Mono>{d.name}</Mono>
            <div className="grow">{d.label || <span className="faint">no label</span>}
              {d.description && <span className="muted"> — {d.description}</span>}</div>
            <span className="chip">{DIRS[d.direction]}</span>
            <Mono title="format">{d.fmt}{d.unit ? ` · ${d.unit}` : ''}</Mono>
            <button className="btn ghost" style={{ fontSize: 11, padding: '1px 8px' }}
                    onClick={() => setDraft({ ...d })}>Edit</button>
          </div>
        ))}
        {defs && !Object.keys(defs).length && (
          <Empty>No metric definitions — unregistered metrics still record, they just render raw.</Empty>
        )}
        {draft && (
          <div className="detail" style={{ display: 'grid', gap: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <input className="text" placeholder="Name (metric key, e.g. acc)" value={draft.name || ''}
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              <input className="text" placeholder="Label (display name)" value={draft.label || ''}
                     onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
              <select className="text" value={draft.direction}
                      onChange={(e) => setDraft({ ...draft, direction: e.target.value })}>
                <option value="maximize">Maximize (↑)</option>
                <option value="minimize">Minimize (↓)</option>
                <option value="info">Info (neither)</option>
              </select>
              <input className="text" placeholder="Format, e.g. .3f or .1%" value={draft.fmt || ''}
                     onChange={(e) => setDraft({ ...draft, fmt: e.target.value })} />
              <input className="text" placeholder="Unit suffix (optional, e.g. ms)" value={draft.unit || ''}
                     onChange={(e) => setDraft({ ...draft, unit: e.target.value })} />
              <input className="text" placeholder="Description (optional)" value={draft.description || ''}
                     onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </div>
            <div className="gnode-actions" style={{ marginTop: 0 }}>
              <button className="btn" onClick={saveMetric} disabled={!(draft.name || '').trim()}>Save metric</button>
              <button className="btn ghost" onClick={() => setDraft(null)}>Cancel</button>
            </div>
          </div>
        )}
      </Section>

      <div style={{ height: 14 }} />

      <Section title="Remotes"
               aside={<button className="rowbtn" style={{ display: 'inline', width: 'auto', color: 'var(--accent)', cursor: 'pointer' }}
                              onClick={() => setRdraft({})}>+ Add remote</button>}>
        <div style={{ padding: '0 16px 8px' }} className="muted">
          Named clusters/storage referencing your ssh aliases (`ssh snaga` stays the source of
          truth for auth). The data root makes locators like <span className="mono">snaga:runs/exp42</span> expand.
        </div>
        {remotes && remotes.map((r) => (
          <div className="row" key={r.name}>
            <Mono>{r.name}</Mono>
            <span className="chip">{r.host || 'This machine'}</span>
            <div className="grow mono muted" style={{ fontSize: 11.5 }}>{r.data_root || '—'}</div>
            {r.description && <span className="muted">{r.description}</span>}
            <button className="btn ghost" style={{ fontSize: 11, padding: '1px 8px' }}
                    onClick={() => setRdraft({ ...r })}>Edit</button>
          </div>
        ))}
        {remotes && !remotes.length && (
          <Empty>No remotes yet — register your cluster so runs and data can say where they live.</Empty>
        )}
        {rdraft && (
          <div className="detail" style={{ display: 'grid', gap: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <input className="text" placeholder="Name, e.g. snaga" value={rdraft.name || ''}
                     onChange={(e) => setRdraft({ ...rdraft, name: e.target.value })} />
              <input className="text" placeholder="SSH alias (default: the name)" value={rdraft.host || ''}
                     onChange={(e) => setRdraft({ ...rdraft, host: e.target.value })} />
              <input className="text" placeholder="Data root, e.g. /scratch/julian/research" value={rdraft.data_root || ''}
                     onChange={(e) => setRdraft({ ...rdraft, data_root: e.target.value })} />
              <input className="text" placeholder="Description (optional)" value={rdraft.description || ''}
                     onChange={(e) => setRdraft({ ...rdraft, description: e.target.value })} />
            </div>
            <div className="gnode-actions" style={{ marginTop: 0 }}>
              <button className="btn" onClick={saveRemote} disabled={!(rdraft.name || '').trim()}>Save remote</button>
              <button className="btn ghost" onClick={() => setRdraft(null)}>Cancel</button>
            </div>
          </div>
        )}
      </Section>

      <div style={{ height: 14 }} />

      <Section title="Review rubric"
               aside={<button className="rowbtn" style={{ display: 'inline', width: 'auto', color: 'var(--accent)', cursor: 'pointer' }}
                              onClick={async () => { if (!rubric) setRubric(await getRubric()); setShowRubric(!showRubric) }}>
                        {showRubric ? 'Hide' : 'Show'}
                      </button>}>
        <div style={{ padding: '0 16px 10px' }} className="muted">
          Read-only: the checks live as data in <span className="mono">renv/review.py</span> —
          making them editable means moving them to a rubric file first, not patching code from the browser.
        </div>
        {showRubric && rubric && rubric.map((c) => (
          <div className="row" key={c.id}>
            <Stamp value={c.severity} />
            <Mono>{c.id}</Mono>
            <div className="grow muted">{c.check}</div>
            <span className="chip">{c.section}</span>
            <span className="chip">{c.verify}</span>
          </div>
        ))}
      </Section>
    </>
  )
}