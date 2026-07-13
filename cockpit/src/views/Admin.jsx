// The control surface: edit the files agents actually read (AGENTS.md, the
// project templates), project settings, and metric definitions. Saving writes
// the real files/rows — an agent picks the instructions up at its next session
// start. What is deliberately NOT here: CLI/MCP tool prompts (they are code;
// their designed control point IS AGENTS.md) and the review rubric (hardcoded
// in review.py today — shown read-only until it moves to data).
import React, { useEffect, useState } from 'react'
import {
  getConfigFiles, getConfigFile, saveConfigFile, getMetricDefs, defineMetric,
  saveProjectSettings, getRubric,
} from '../api.js'
import { Stamp, Section, Empty, Mono } from '../ui.jsx'

function FileEditor({ scopes, slug, banner }) {
  const [files, setFiles] = useState(null)
  const [sel, setSel] = useState(null)          // {scope, name, project}
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    let live = true
    getConfigFiles(slug).then((all) => {
      if (!live) return
      const mine = all.filter((f) => scopes.includes(f.scope))
      setFiles(mine)
      setSel((cur) => cur || mine[0] || null)
    })
    return () => { live = false }
  }, [slug, scopes])

  useEffect(() => {
    if (!sel) return
    let live = true
    getConfigFile(sel.scope, sel.name, sel.project).then((r) => {
      if (live) { setContent(r.content ?? ''); setDirty(false); setMsg(null) }
    })
    return () => { live = false }
  }, [sel])

  const save = async () => {
    const r = await saveConfigFile(sel.scope, sel.name, content, sel.project)
    if (r.error) { setMsg({ bad: true, text: r.error }); return }
    setDirty(false)
    setMsg({ text: `saved to ${r.saved}` })
  }

  if (!files) return <div className="loading">reading files…</div>

  return (
    <>
      <div className="filetabs">
        {files.map((f) => (
          <button
            key={f.scope + f.name}
            className={`btn ghost ${sel && sel.scope === f.scope && sel.name === f.name ? 'active-tab' : ''}`}
            onClick={() => setSel(f)}
          >
            <span className="mono">{f.scope === 'project' ? `${f.project}/` : f.scope === 'template' ? 'template/' : ''}{f.name}</span>
          </button>
        ))}
      </div>
      {sel && (
        <Section title={sel.name} aside={dirty ? 'unsaved changes' : 'saved'}>
          <div style={{ padding: '0 16px 6px' }} className="muted">
            {files.find((f) => f.scope === sel.scope && f.name === sel.name)?.description} {banner}
          </div>
          <div style={{ padding: '6px 16px 14px' }}>
            <textarea
              className="fileedit"
              value={content}
              onChange={(e) => { setContent(e.target.value); setDirty(true) }}
              spellCheck={false}
            />
            {msg && <div style={{ color: msg.bad ? 'var(--bad)' : 'var(--ok)', marginTop: 6, fontSize: 12 }} className="mono">{msg.text}</div>}
            <div className="gnode-actions">
              <button className="btn" onClick={save} disabled={!dirty}>Save file</button>
            </div>
          </div>
        </Section>
      )}
    </>
  )
}

export function Instructions({ slug }) {
  return (
    <>
      <div className="pagehead">
        <h1>Instructions</h1>
        <div className="sub">
          the protocol agents load at session start — saving changes what they do on their next session
        </div>
      </div>
      <FileEditor scopes={['env', 'project']} slug={slug}
                  banner="Agents (Claude Code via MCP/CLI) read this file — edits take effect next session." />
    </>
  )
}

export function Templates({ slug }) {
  return (
    <>
      <div className="pagehead">
        <h1>Templates</h1>
        <div className="sub">
          what every new project is scaffolded from — paper structure lives in text/paper.tex
        </div>
      </div>
      <FileEditor scopes={['template']} slug={slug}
                  banner="Applies to every FUTURE `reref new` — existing projects keep their copies." />
    </>
  )
}

const DIRS = { maximize: '↑ higher is better', minimize: '↓ lower is better', info: '· informational' }

export function Settings({ slug, project, onMutate }) {
  const [title, setTitle] = useState(project?.title || '')
  const [status, setStatus] = useState(project?.status || 'active')
  const [defs, setDefs] = useState(null)
  const [draft, setDraft] = useState(null)      // metric being edited/created
  const [rubric, setRubric] = useState(null)
  const [showRubric, setShowRubric] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => { setTitle(project?.title || ''); setStatus(project?.status || 'active') }, [project])
  useEffect(() => { getMetricDefs().then(setDefs) }, [])

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
        <div className="sub">project metadata and the metric registry (standardized display everywhere)</div>
      </div>

      <Section title="Project" aside={slug}>
        <div style={{ padding: '4px 16px 14px', display: 'grid', gap: 8, maxWidth: 480 }}>
          <input className="text" placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <select className="text" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="active">active</option>
            <option value="archived">archived</option>
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
                              onClick={() => setDraft({ direction: 'maximize', fmt: '.3f' })}>+ define metric</button>}>
        {defs && Object.values(defs).map((d) => (
          <div className="row" key={d.name}>
            <Mono>{d.name}</Mono>
            <div className="grow">{d.label || <span className="faint">no label</span>}
              {d.description && <span className="muted"> — {d.description}</span>}</div>
            <span className="chip">{DIRS[d.direction]}</span>
            <Mono title="format">{d.fmt}{d.unit ? ` · ${d.unit}` : ''}</Mono>
            <button className="btn ghost" style={{ fontSize: 11, padding: '1px 8px' }}
                    onClick={() => setDraft({ ...d })}>edit</button>
          </div>
        ))}
        {defs && !Object.keys(defs).length && (
          <Empty>No metric definitions — unregistered metrics still record, they just render raw.</Empty>
        )}
        {draft && (
          <div className="detail" style={{ display: 'grid', gap: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <input className="text" placeholder="name (metric key, e.g. acc)" value={draft.name || ''}
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              <input className="text" placeholder="label (display name)" value={draft.label || ''}
                     onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
              <select className="text" value={draft.direction}
                      onChange={(e) => setDraft({ ...draft, direction: e.target.value })}>
                <option value="maximize">maximize (↑)</option>
                <option value="minimize">minimize (↓)</option>
                <option value="info">info (neither)</option>
              </select>
              <input className="text" placeholder="format, e.g. .3f or .1%" value={draft.fmt || ''}
                     onChange={(e) => setDraft({ ...draft, fmt: e.target.value })} />
              <input className="text" placeholder="unit suffix (optional, e.g. ms)" value={draft.unit || ''}
                     onChange={(e) => setDraft({ ...draft, unit: e.target.value })} />
              <input className="text" placeholder="description (optional)" value={draft.description || ''}
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

      <Section title="Review rubric"
               aside={<button className="rowbtn" style={{ display: 'inline', width: 'auto', color: 'var(--accent)', cursor: 'pointer' }}
                              onClick={async () => { if (!rubric) setRubric(await getRubric()); setShowRubric(!showRubric) }}>
                        {showRubric ? 'hide' : 'show'}
                      </button>}>
        <div style={{ padding: '0 16px 10px' }} className="muted">
          Read-only: the checks live as data in <span className="mono">reref/review.py</span> —
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
