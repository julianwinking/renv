import React, { useCallback, useEffect, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState } from '@xyflow/react'
import {
  getGraph, addExperiment, addClaim, addLog, addNote,
  setExperimentParent, relateClaims, linkExperimentToClaim, saveLayout,
  editClaim, editLog, editNote, getConnections, addContextLink, linkCitationToClaim,
} from '../api.js'
import { toFlow } from '../layout.js'
import { nodeTypes } from '../nodes.jsx'

const KINDS = [
  ['experiment', 'var(--accent)'],
  ['claim', 'var(--claim)'],
  ['citation', 'var(--citation)'],
  ['paper', 'var(--paper-kind)'],
  ['finding', 'var(--warn)'],
  ['question', 'var(--warn)'],
  ['hypothesis', 'var(--citation)'],
  ['feedback', 'var(--code-kind)'],
  ['note', 'var(--line-strong)'],
  ['code', 'var(--code-kind)'],
]
const MINI = Object.fromEntries(KINDS)

// The canvas is a planning surface over the ledger: every gesture maps to a
// domain write (or is refused with the store's reason). Nothing is drawn free-form.
function AddPanel({ kind, slug, onClose, onDone, experiments, at }) {
  const [f, setF] = useState({})
  const [err, setErr] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const save = async () => {
    setErr(null)
    let r, nodeId
    if (kind === 'experiment') {
      r = await addExperiment(slug, f.slug, f.title, f.hypothesis, f.parent || undefined)
      nodeId = r && r.id ? `exp:${r.id}` : null
    } else if (kind === 'claim') {
      r = await addClaim(slug, f.text, f.kind || 'assertion')
      nodeId = r && r.id ? `claim:${r.id}` : null
    } else if (kind === 'question' || kind === 'hypothesis' || kind === 'feedback') {
      r = await addLog(slug, kind, f.text, kind === 'feedback' && f.source ? { source: f.source } : {})
      nodeId = r && r.id ? `log:${r.id}` : null
    } else {
      r = await addNote(slug, f.text)
      nodeId = r && r.id ? `note:${r.id}` : null
    }
    if (r && r.error) { setErr(r.error); return }
    onDone(nodeId)
  }

  // open where the user right-clicked (clamped so the panel stays on screen)
  const pos = at ? {
    position: 'fixed',
    left: Math.min(at.x, window.innerWidth - 320),
    top: Math.min(at.y, window.innerHeight - 380),
    right: 'auto',
  } : null

  return (
    <div className="gpanel" style={pos}>
      <div className="eyebrow" style={{ margin: '0 0 8px' }}>New {kind}</div>
      {kind === 'experiment' && (
        <>
          <input className="text" placeholder="Slug, e.g. 004-dimension-sweep" onChange={set('slug')} autoFocus />
          <input className="text" placeholder="Title" onChange={set('title')} />
          <textarea placeholder="Hypothesis — what should this branch show?" onChange={set('hypothesis')} />
          <select className="text" onChange={set('parent')} defaultValue="">
            <option value="">No parent (root)</option>
            {experiments.map((s) => <option key={s} value={s}>Branch of {s}</option>)}
          </select>
        </>
      )}
      {kind === 'claim' && (
        <>
          <textarea placeholder="The claim — one testable statement" onChange={set('text')} autoFocus />
          <select className="text" onChange={set('kind')} defaultValue="assertion">
            <option value="assertion">Assertion</option>
            <option value="contribution">Contribution</option>
            <option value="thesis">Thesis</option>
          </select>
        </>
      )}
      {kind === 'question' && (
        <textarea placeholder="An open question — stays OPEN until an entry answers it" onChange={set('text')} autoFocus />
      )}
      {kind === 'hypothesis' && (
        <textarea placeholder="A testable hypothesis — branch experiments off it" onChange={set('text')} autoFocus />
      )}
      {kind === 'feedback' && (
        <>
          <input className="text" placeholder='Who gave it? e.g. "advisor: Prof. X"' onChange={set('source')} autoFocus />
          <textarea placeholder="What did they say?" onChange={set('text')} />
        </>
      )}
      {kind === 'note' && (
        <textarea placeholder="Meeting note / idea — saved to the store" onChange={set('text')} autoFocus />
      )}
      {err && <div style={{ color: 'var(--bad)', marginTop: 6, fontSize: 12 }}>{err}</div>}
      <div className="gnode-actions">
        <button className="btn" onClick={save}>Add to store</button>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}

// Registry-driven connect panel. `pending` carries the source/target nodes and
// the list of allowed relation options (from /api/connections). The user picks
// one; dispatch() routes it to the right store write by the option's mode.
function ConnectPanel({ pending, slug, onClose, onDone }) {
  const { source, target, options, at } = pending
  const [choice, setChoice] = useState(options[0].value)
  const [note, setNote] = useState('')
  const [err, setErr] = useState(null)
  const opt = options.find((o) => o.value === choice)
  const srcId = Number(source.id.split(':')[1])
  const tgtId = Number(target.id.split(':')[1])
  const srcKind = source.type
  const tgtKind = target.type

  const save = async () => {
    setErr(null)
    const n = note.trim() || undefined
    let r
    if (opt.mode === 'parent') {
      r = await setExperimentParent(slug, target.data.label, source.data.label)
    } else if (opt.mode === 'evidence') {
      r = await linkExperimentToClaim(slug, source.data.label, tgtId, choice, n)
    } else if (opt.mode === 'cite_evidence') {
      r = await linkCitationToClaim(tgtId, srcId, choice, n)
    } else if (opt.mode === 'relation') {
      r = await relateClaims(srcId, tgtId, choice, n)
    } else {   // context
      r = await addContextLink({
        project: slug, from_kind: srcKind, from_id: srcId,
        to_kind: tgtKind, to_id: tgtId, relation: choice, note: n,
      })
    }
    if (r && r.error) { setErr(r.error); return }
    onDone()
  }

  // center the ~280px panel on the midpoint, clamped to the viewport
  const style = at ? {
    left: Math.max(12, Math.min(at.x - 150, window.innerWidth - 312)),
    top: Math.max(12, Math.min(at.y - 90, window.innerHeight - 240)),
    right: 'auto',
  } : undefined

  return (
    <div className="gpanel" style={style}>
      <div className="eyebrow" style={{ margin: '0 0 8px' }}>{srcKind} → {tgtKind}</div>
      {options.length > 1 ? (
        <select className="text" value={choice} onChange={(e) => setChoice(e.target.value)}>
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : (
        <div className="muted" style={{ fontSize: 12 }}>{options[0].label}</div>
      )}
      <textarea placeholder="Comment on this connection (optional)"
                value={note} onChange={(e) => setNote(e.target.value)} />
      {err && <div style={{ color: 'var(--bad)', marginTop: 6, fontSize: 12 }}>{err}</div>}
      <div className="gnode-actions">
        <button className="btn" onClick={save}>Connect</button>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}

export default function GraphView({ slug, defs, onMutate }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [busy, setBusy] = useState(true)
  const [adding, setAdding] = useState(null)         // 'experiment' | 'claim' | 'question' | 'note'
  const [pendingEdge, setPendingEdge] = useState(null)
  const [menu, setMenu] = useState(null)             // {x, y}
  const [menuAt, setMenuAt] = useState(null)         // where the add panel should open
  const [toast, setToast] = useState(null)
  const [legendOpen, setLegendOpen] = useState(() => localStorage.getItem('reref-legend') !== 'closed')
  const [conns, setConns] = useState([])            // the connection registry
  const flowRef = React.useRef(null)

  useEffect(() => { getConnections().then((c) => setConns(Array.isArray(c) ? c : [])) }, [])
  const optionsFor = (from, to) =>
    (conns.find((c) => c.from === from && c.to === to) || {}).options || []
  const dropPos = React.useRef(null)                 // where a right-click add should land

  const load = useCallback(async () => {
    setBusy(true)
    const g = await getGraph(slug)
    const flow = toFlow(g)
    flow.nodes.forEach((n) => {
      n.data.defs = defs
      const [k, id] = n.id.split(':')
      const after = () => { load(); onMutate && onMutate() }
      if (k === 'claim') n.data.onSaveText = (t) => editClaim(Number(id), t).then(after)
      else if (k === 'log') n.data.onSaveText = (t) => editLog(Number(id), t).then(after)
      else if (k === 'note') n.data.onSaveText = (t) => editNote(Number(id), t).then(after)
      if (n.type === 'finding') {
        n.data.id = Number(id)
        n.data.onDone = after
      }
    })
    setNodes(flow.nodes)
    setEdges(flow.edges)
    setBusy(false)
    // fit AFTER the async data lands — the mount-time fitView saw an empty canvas
    requestAnimationFrame(() =>
      flowRef.current?.fitView({ padding: 0.18, maxZoom: 1 }))
  }, [slug, defs, onMutate, setNodes, setEdges])

  useEffect(() => { load() }, [load])

  const say = (msg, bad) => {
    setToast({ msg, bad })
    setTimeout(() => setToast(null), 5000)
  }

  const persistPositions = useCallback(() => {
    const inst = flowRef.current
    if (!inst) return
    const positions = Object.fromEntries(inst.getNodes().map((n) => [n.id, n.position]))
    saveLayout(slug, positions)
  }, [slug])

  // Drawing an edge consults the central connection registry: the node kinds
  // decide which relations are possible. 0 → refuse; ≥1 → a panel to choose
  // + comment; a single obvious option still shows so you can annotate it.
  const onConnect = useCallback(async ({ source, target }) => {
    const src = nodes.find((n) => n.id === source)
    const tgt = nodes.find((n) => n.id === target)
    if (!src || !tgt) return
    const options = optionsFor(src.type, tgt.type)
    if (!options.length) {
      say(`A ${src.type} → ${tgt.type} connection has no meaning in the store`, true)
      return
    }
    // open the panel centered between the two nodes (screen space)
    let at = null
    const inst = flowRef.current
    if (inst?.flowToScreenPosition) {
      const c = (n) => ({
        x: n.position.x + (n.measured?.width || n.width || 220) / 2,
        y: n.position.y + (n.measured?.height || n.height || 90) / 2,
      })
      const a = c(src), b = c(tgt)
      at = inst.flowToScreenPosition({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
    }
    setPendingEdge({ source: src, target: tgt, options, at })
  }, [nodes, conns])

  // Double-click opens the entity's page (hash deep-link into its view).
  const onNodeDoubleClick = useCallback((_, node) => {
    const [k, id] = node.id.split(':')
    const go = (h) => { location.hash = h }
    if (k === 'exp') go('#/experiments/' + encodeURIComponent(node.data.label))
    else if (k === 'claim') go('#/claims/' + id)
    else if (k === 'log') go('#/log/' + encodeURIComponent('log-' + id))
    else if (k === 'note') go('#/log/' + encodeURIComponent('note-' + id))
    else if (k === 'paper') go('#/papers/' + encodeURIComponent(node.data.label))
    else if (k === 'finding') go('#/findings')
  }, [])

  const onPaneContextMenu = useCallback((e) => {
    e.preventDefault()
    const inst = flowRef.current
    dropPos.current = inst ? inst.screenToFlowPosition({ x: e.clientX, y: e.clientY }) : null
    setMenu({ x: e.clientX, y: e.clientY })
    setMenuAt({ x: e.clientX, y: e.clientY })
  }, [])

  const addDone = async (nodeId) => {
    setAdding(null)
    if (nodeId && dropPos.current) {   // pin the new node where the user right-clicked
      await saveLayout(slug, { [nodeId]: dropPos.current })
      dropPos.current = null
    }
    load(); onMutate && onMutate()
  }

  const expSlugs = nodes.filter((n) => n.type === 'experiment').map((n) => n.data.label)

  return (
    <>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeDoubleClick={onNodeDoubleClick}
        onNodeDragStop={persistPositions}
        onPaneContextMenu={onPaneContextMenu}
        onPaneClick={() => setMenu(null)}
        nodeTypes={nodeTypes}
        onInit={(inst) => { flowRef.current = inst; inst.fitView({ padding: 0.18, maxZoom: 1 }) }}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={22} size={1.2} color="var(--line-strong)" />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => MINI[n.type] || 'var(--line-strong)'}
          maskColor="color-mix(in srgb, var(--bg) 75%, transparent)"
          style={{ background: 'var(--surface)' }}
        />
        <Controls showInteractive={false} />
      </ReactFlow>

      {adding && (
        <AddPanel kind={adding} slug={slug} experiments={expSlugs} at={menuAt}
                  onClose={() => setAdding(null)} onDone={addDone} />
      )}
      {pendingEdge && (
        <ConnectPanel pending={pendingEdge} slug={slug}
                      onClose={() => setPendingEdge(null)}
                      onDone={() => { setPendingEdge(null); load(); onMutate && onMutate() }} />
      )}
      {menu && (
        <div className="gmenu" style={{ left: menu.x, top: menu.y }}>
          {[['experiment', 'var(--accent)'], ['claim', 'var(--claim)'],
            ['question', 'var(--warn)'], ['hypothesis', 'var(--citation)'],
            ['feedback', 'var(--code-kind)'], ['note', 'var(--line-strong)']].map(([k, c]) => (
            <button key={k} onClick={() => { setAdding(k); setMenu(null) }}>
              <span className="sw" style={{ background: c }} />New {k}
            </button>
          ))}
        </div>
      )}

      <div className={`glegend ${legendOpen ? '' : 'closed'}`}>
        <button className="glegend-head" onClick={() => {
          const next = !legendOpen
          setLegendOpen(next)
          localStorage.setItem('reref-legend', next ? 'open' : 'closed')
        }}>
          <span className="eyebrow" style={{ margin: 0 }}>legend</span>
          <span className="glegend-caret">{legendOpen ? '▾' : '▴'}</span>
        </button>
        {legendOpen && (
          <>
            {KINDS.map(([k, c]) => (
              <div className="li" key={k}><span className="sw" style={{ background: c }} />{k[0].toUpperCase() + k.slice(1)}</div>
            ))}
            <div className="li faint" style={{ marginTop: 4 }}>Drag node→node connects · double-click opens</div>
            <div className="li faint">Right-click adds · positions are saved</div>
          </>
        )}
      </div>

      {toast && (
        <div className="gtoast" style={toast.bad ? { borderColor: 'var(--bad)', color: 'var(--bad)' } : null}>
          {toast.msg}
        </div>
      )}
      {busy && <div className="loading" style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}>laying out…</div>}
    </>
  )
}
