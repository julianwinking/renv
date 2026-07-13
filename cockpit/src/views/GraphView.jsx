import React, { useCallback, useEffect, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState } from '@xyflow/react'
import { getGraph, addExperiment, addClaim, setExperimentParent, relateClaims, linkExperimentToClaim } from '../api.js'
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
    const r = kind === 'experiment'
      ? await addExperiment(slug, f.slug, f.title, f.hypothesis, f.parent || undefined)
      : await addClaim(slug, f.text, f.kind || 'assertion')
    if (r && r.error) { setErr(r.error); return }
    onDone()
  }

  return (
    <div className="gpanel">
      <div className="eyebrow" style={{ margin: '0 0 8px' }}>new {kind}</div>
      {kind === 'experiment' ? (
        <>
          <input className="text" placeholder="slug, e.g. 004-dimension-sweep" onChange={set('slug')} autoFocus />
          <input className="text" placeholder="title" onChange={set('title')} />
          <textarea placeholder="hypothesis — what should this branch show?" onChange={set('hypothesis')} />
          <select className="text" onChange={set('parent')} defaultValue="">
            <option value="">no parent (root)</option>
            {experiments.map((s) => <option key={s} value={s}>branch of {s}</option>)}
          </select>
        </>
      ) : (
        <>
          <textarea placeholder="the claim — one testable statement" onChange={set('text')} autoFocus />
          <select className="text" onChange={set('kind')} defaultValue="assertion">
            <option value="assertion">assertion</option>
            <option value="contribution">contribution</option>
            <option value="thesis">thesis</option>
          </select>
        </>
      )}
      {err && <div style={{ color: 'var(--bad)', marginTop: 6, fontSize: 12 }}>{err}</div>}
      <div className="gnode-actions">
        <button className="btn" onClick={save}>Add to store</button>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}

export default function GraphView({ slug, defs, onMutate }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [busy, setBusy] = useState(true)
  const [adding, setAdding] = useState(null)         // 'experiment' | 'claim' | null
  const [toast, setToast] = useState(null)
  const flowRef = React.useRef(null)

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

  // Drawing an edge writes through the domain layer — or is refused with the reason.
  const onConnect = useCallback(async ({ source, target }) => {
    const [sk, sid] = source.split(':')
    const [tk, tid] = target.split(':')
    const nodeOf = (id) => nodes.find((n) => n.id === id)
    let r
    if (sk === 'exp' && tk === 'exp') {
      r = await setExperimentParent(slug, nodeOf(target)?.data.label, nodeOf(source)?.data.label)
      if (!r.error) say(`${nodeOf(target)?.data.label} now branches off ${nodeOf(source)?.data.label}`)
    } else if (sk === 'exp' && tk === 'claim') {
      r = await linkExperimentToClaim(slug, nodeOf(source)?.data.label, Number(tid), 'supports')
      if (!r.error) say('claim now supported by the experiment’s latest run')
    } else if (sk === 'claim' && tk === 'claim') {
      r = await relateClaims(Number(sid), Number(tid), 'depends_on')
      if (!r.error) say('argument chained: claim depends on claim')
    } else {
      say(`a ${sk}→${tk} edge has no meaning in the store`, true)
      return
    }
    if (r && r.error) say(r.error, true)
    else { load(); onMutate && onMutate() }
  }, [nodes, slug, load, onMutate])

  const expSlugs = nodes.filter((n) => n.type === 'experiment').map((n) => n.data.label)

  return (
    <>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
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

      <div className="gtools">
        <button className="btn ghost" onClick={() => setAdding(adding === 'experiment' ? null : 'experiment')}>+ experiment</button>
        <button className="btn ghost" onClick={() => setAdding(adding === 'claim' ? null : 'claim')}>+ claim</button>
      </div>
      {adding && (
        <AddPanel kind={adding} slug={slug} experiments={expSlugs}
                  onClose={() => setAdding(null)}
                  onDone={() => { setAdding(null); load(); onMutate && onMutate() }} />
      )}

      <div className="glegend">
        {KINDS.map(([k, c]) => (
          <div className="li" key={k}><span className="sw" style={{ background: c }} />{k}</div>
        ))}
        <div className="li faint" style={{ marginTop: 4 }}>drag node→node to connect:</div>
        <div className="li faint">exp→exp branches · exp→claim backs · claim→claim chains</div>
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
