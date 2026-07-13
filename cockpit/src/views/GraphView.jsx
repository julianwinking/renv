import React, { useCallback, useEffect, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState } from '@xyflow/react'
import {
  getGraph, addExperiment, addClaim, addLog, addNote,
  setExperimentParent, relateClaims, linkExperimentToClaim, saveLayout,
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
function AddPanel({ kind, slug, onClose, onDone, experiments }) {
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

  return (
    <div className="gpanel">
      <div className="eyebrow" style={{ margin: '0 0 8px' }}>new {kind}</div>
      {kind === 'experiment' && (
        <>
          <input className="text" placeholder="slug, e.g. 004-dimension-sweep" onChange={set('slug')} autoFocus />
          <input className="text" placeholder="title" onChange={set('title')} />
          <textarea placeholder="hypothesis — what should this branch show?" onChange={set('hypothesis')} />
          <select className="text" onChange={set('parent')} defaultValue="">
            <option value="">no parent (root)</option>
            {experiments.map((s) => <option key={s} value={s}>branch of {s}</option>)}
          </select>
        </>
      )}
      {kind === 'claim' && (
        <>
          <textarea placeholder="the claim — one testable statement" onChange={set('text')} autoFocus />
          <select className="text" onChange={set('kind')} defaultValue="assertion">
            <option value="assertion">assertion</option>
            <option value="contribution">contribution</option>
            <option value="thesis">thesis</option>
          </select>
        </>
      )}
      {kind === 'question' && (
        <textarea placeholder="an open question — stays OPEN until an entry answers it" onChange={set('text')} autoFocus />
      )}
      {kind === 'hypothesis' && (
        <textarea placeholder="a testable hypothesis — branch experiments off it" onChange={set('text')} autoFocus />
      )}
      {kind === 'feedback' && (
        <>
          <input className="text" placeholder='who gave it? e.g. "advisor: Prof. X"' onChange={set('source')} autoFocus />
          <textarea placeholder="what did they say?" onChange={set('text')} />
        </>
      )}
      {kind === 'note' && (
        <textarea placeholder="meeting note / idea — saved to the store" onChange={set('text')} autoFocus />
      )}
      {err && <div style={{ color: 'var(--bad)', marginTop: 6, fontSize: 12 }}>{err}</div>}
      <div className="gnode-actions">
        <button className="btn" onClick={save}>Add to store</button>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}

// Confirm a drawn edge: stance/kind + an optional comment stored on the link.
function EdgePanel({ pending, onClose, onDone }) {
  const [choice, setChoice] = useState(pending.type === 'evidence' ? 'supports' : 'depends_on')
  const [note, setNote] = useState('')
  const [err, setErr] = useState(null)

  const save = async () => {
    setErr(null)
    const r = pending.type === 'evidence'
      ? await linkExperimentToClaim(pending.slug, pending.experiment, pending.claimId, choice, note.trim() || undefined)
      : await relateClaims(pending.claimId, pending.relatedId, choice, note.trim() || undefined)
    if (r && r.error) { setErr(r.error); return }
    onDone()
  }

  return (
    <div className="gpanel">
      <div className="eyebrow" style={{ margin: '0 0 8px' }}>
        {pending.type === 'evidence'
          ? `${pending.experiment} → claim #${pending.claimId}`
          : `claim #${pending.claimId} → claim #${pending.relatedId}`}
      </div>
      <select className="text" value={choice} onChange={(e) => setChoice(e.target.value)}>
        {pending.type === 'evidence' ? (
          <>
            <option value="supports">supports (via latest done run)</option>
            <option value="refutes">refutes (via latest done run)</option>
          </>
        ) : (
          <>
            <option value="depends_on">depends on</option>
            <option value="contradicts">contradicts</option>
          </>
        )}
      </select>
      <textarea placeholder="comment on this edge (optional) — why does it hold?"
                value={note} onChange={(e) => setNote(e.target.value)} />
      {err && <div style={{ color: 'var(--bad)', marginTop: 6, fontSize: 12 }}>{err}</div>}
      <div className="gnode-actions">
        <button className="btn" onClick={save}>Link</button>
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
  const [menu, setMenu] = useState(null)             // {x, y, flowPos}
  const [toast, setToast] = useState(null)
  const [legendOpen, setLegendOpen] = useState(() => localStorage.getItem('reref-legend') !== 'closed')
  const flowRef = React.useRef(null)
  const dropPos = React.useRef(null)                 // where a right-click add should land

  const load = useCallback(async () => {
    setBusy(true)
    const g = await getGraph(slug)
    const flow = toFlow(g)
    flow.nodes.forEach((n) => {
      n.data.defs = defs
      if (n.type === 'finding') {
        n.data.id = Number(n.id.split(':')[1])
        n.data.onDone = () => { load(); onMutate && onMutate() }
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

  // Drawing an edge writes through the domain layer — or is refused with the reason.
  const onConnect = useCallback(async ({ source, target }) => {
    const [sk, sid] = source.split(':')
    const [tk, tid] = target.split(':')
    const nodeOf = (id) => nodes.find((n) => n.id === id)
    if (sk === 'exp' && tk === 'exp') {
      const r = await setExperimentParent(slug, nodeOf(target)?.data.label, nodeOf(source)?.data.label)
      if (r && r.error) say(r.error, true)
      else { say(`${nodeOf(target)?.data.label} now branches off ${nodeOf(source)?.data.label}`); load(); onMutate && onMutate() }
    } else if (sk === 'exp' && tk === 'claim') {
      setPendingEdge({ type: 'evidence', slug, experiment: nodeOf(source)?.data.label, claimId: Number(tid) })
    } else if (sk === 'claim' && tk === 'claim') {
      setPendingEdge({ type: 'relation', claimId: Number(sid), relatedId: Number(tid) })
    } else {
      say(`a ${sk}→${tk} edge has no meaning in the store`, true)
    }
  }, [nodes, slug, load, onMutate])

  // Double-click opens the entity's page (hash deep-link into its view).
  const onNodeDoubleClick = useCallback((_, node) => {
    const [k, id] = node.id.split(':')
    const go = (h) => { location.hash = h }
    if (k === 'exp') go('#/experiments/' + encodeURIComponent(node.data.label))
    else if (k === 'claim') go('#/claims/' + id)
    else if (k === 'log') go('#/timeline/' + encodeURIComponent('log-' + id))
    else if (k === 'note') go('#/timeline/' + encodeURIComponent('note-' + id))
    else if (k === 'paper') go('#/papers/' + encodeURIComponent(node.data.label))
    else if (k === 'finding') go('#/findings')
  }, [])

  const onPaneContextMenu = useCallback((e) => {
    e.preventDefault()
    const inst = flowRef.current
    dropPos.current = inst ? inst.screenToFlowPosition({ x: e.clientX, y: e.clientY }) : null
    setMenu({ x: e.clientX, y: e.clientY })
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
        <AddPanel kind={adding} slug={slug} experiments={expSlugs}
                  onClose={() => setAdding(null)} onDone={addDone} />
      )}
      {pendingEdge && (
        <EdgePanel pending={pendingEdge}
                   onClose={() => setPendingEdge(null)}
                   onDone={() => { setPendingEdge(null); load(); onMutate && onMutate() }} />
      )}
      {menu && (
        <div className="gmenu" style={{ left: menu.x, top: menu.y }}>
          {[['experiment', 'var(--accent)'], ['claim', 'var(--claim)'],
            ['question', 'var(--warn)'], ['hypothesis', 'var(--citation)'],
            ['feedback', 'var(--code-kind)'], ['note', 'var(--line-strong)']].map(([k, c]) => (
            <button key={k} onClick={() => { setAdding(k); setMenu(null) }}>
              <span className="sw" style={{ background: c }} />new {k}
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
          <span className="faint">{legendOpen ? '▾' : '▸'}</span>
        </button>
        {legendOpen && (
          <>
            {KINDS.map(([k, c]) => (
              <div className="li" key={k}><span className="sw" style={{ background: c }} />{k}</div>
            ))}
            <div className="li faint" style={{ marginTop: 4 }}>drag node→node connects · double-click opens</div>
            <div className="li faint">right-click adds · positions are saved</div>
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
