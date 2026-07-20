// The control surface: edit the files agents actually read (AGENTS.md, the
// project templates), project settings, and metric definitions. Saving writes
// the real files/rows — an agent picks the instructions up at its next session
// start. What is deliberately NOT here: CLI/MCP tool prompts (they are code;
// their designed control point IS AGENTS.md) and the review rubric (hardcoded
// in review.py today — shown read-only until it moves to data).
import React, { useEffect, useState } from 'react'
import {
  getConfigFiles, getConfigFile, saveConfigFile, getMetricDefs, defineMetric,
  saveProjectSettings, getRubric, getRemotes, addRemote,
} from '../api.js'
import { asArray, Stamp, Section, Empty, Mono } from '../ui.jsx'

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
      const mine = asArray(all).filter((f) => scopes.includes(f.scope))
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
            <span className="mono">
              {f.scope === 'project' ? `${f.project}/` : f.scope === 'template' ? 'template/'
                : f.scope === 'writing' ? 'writing/' : ''}{f.name}
            </span>
          </button>
        ))}
      </div>
      {sel && (
        <Section title={sel.name} aside={dirty ? 'Unsaved changes' : 'Saved'}>
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
        <h1>Templates & writing</h1>
        <div className="sub">
          how a paper is built, how a thesis argues, sentences worth reusing — plus the project scaffold
        </div>
      </div>
      <FileEditor scopes={['writing', 'template']} slug={slug}
                  banner="Agents read the writing guides before drafting text; template files apply to every FUTURE `renv new`." />
    </>
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
