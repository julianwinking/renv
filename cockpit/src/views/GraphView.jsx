import React, { useCallback, useEffect, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap, ViewportPortal, useNodesState, useEdgesState } from '@xyflow/react'
import {
  getGraph, addExperiment, addClaim, addLog, addNote,
  setExperimentParent, relateClaims, linkExperimentToClaim, saveLayout,
  editClaim, editLog, editNote, getConnections, addContextLink, linkCitationToClaim,
  getRegions, addRegion, updateRegion, editExperiment, updatePaperNote, updatePlanItem,
  getPhases, setPhaseBand, setPhaseBandColor, declareTest, undeclareTest, editPaper,
  retractEvidence, confirmEvidence, deleteClaimRelation, deleteContextLink,
} from '../api.js'
import { navigate } from '../nav.js'
import { toFlow } from '../layout.js'
import { nodeTypes, REGION_COLORS } from '../nodes.jsx'

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
function AddPanel({ kind, slug, onClose, onDone, experiments, at, initial }) {
  const [f, setF] = useState(initial || {})
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
    } else if (['question', 'hypothesis', 'feedback', 'decision', 'blocker', 'observation'].includes(kind)) {
      r = await addLog(slug, kind, f.text, kind === 'feedback' && f.source ? { source: f.source } : {})
      nodeId = r && r.id ? `log:${r.id}` : null
    } else {
      r = await addNote(slug, f.text)
      nodeId = r && r.id ? `note:${r.id}` : null
    }
    if (r && r.error) { setErr(r.error); return }
    onDone(nodeId, r)
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
          <input className="text" placeholder="Title" defaultValue={f.title || ''} onChange={set('title')} />
          <textarea placeholder="Hypothesis — what should this branch show?"
                    defaultValue={f.hypothesis || ''} onChange={set('hypothesis')} />
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
            <option value="hypothesis">Hypothesis (awaiting its test)</option>
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
      {kind === 'decision' && (
        <textarea placeholder="A decision — what was chosen, and why" onChange={set('text')} autoFocus />
      )}
      {kind === 'blocker' && (
        <textarea placeholder="A blocker — what is stopping progress" onChange={set('text')} autoFocus />
      )}
      {kind === 'observation' && (
        <textarea placeholder="An observation — what was noticed" onChange={set('text')} autoFocus />
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
  const [grade, setGrade] = useState('suggestive')
  const [err, setErr] = useState(null)
  const opt = options.find((o) => o.value === choice)
  const srcId = Number(source.id.split(':')[1])
  const tgtId = Number(target.id.split(':')[1])
  const srcKind = source.type
  const tgtKind = target.type
  const isEvidence = opt.mode === 'evidence' || opt.mode === 'cite_evidence'

  const save = async () => {
    setErr(null)
    const n = note.trim() || undefined
    let r
    if (opt.mode === 'parent') {
      r = await setExperimentParent(slug, target.data.label, source.data.label)
    } else if (opt.mode === 'tests') {
      r = await declareTest(slug, source.data.label, tgtId)
    } else if (opt.mode === 'evidence') {
      r = await linkExperimentToClaim(slug, source.data.label, tgtId, choice, n, grade)
    } else if (opt.mode === 'cite_evidence') {
      r = await linkCitationToClaim(tgtId, srcId, choice, n, grade)
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
      {isEvidence && (
        <select className="text" value={grade} onChange={(e) => setGrade(e.target.value)}
                title="How strong is this evidence? Headline claims need confirmatory support.">
          <option value="anecdotal">Anecdotal — a single observation</option>
          <option value="suggestive">Suggestive — a toy or single-seed run</option>
          <option value="confirmatory">Confirmatory — scaled, multi-seed, trustworthy</option>
        </select>
      )}
      {opt.mode === 'tests' && (
        <div className="muted" style={{ fontSize: 11.5, margin: '6px 0 2px' }}>
          Pre-registers the test before any run — evidence linked later counts as
          declared, not post-hoc.
        </div>
      )}
      {!(opt.mode === 'tests') && (
        <textarea placeholder="Comment on this connection (optional)"
                  value={note} onChange={(e) => setNote(e.target.value)} />
      )}
      {err && <div style={{ color: 'var(--bad)', marginTop: 6, fontSize: 12 }}>{err}</div>}
      <div className="gnode-actions">
        <button className="btn" onClick={save}>Connect</button>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}

// Click an edge to see what it means in the store — and act on it. Soft links
// and argument relations can be removed; evidence is retracted (kept as
// history, with a required reason), never deleted; a stale evidence link can
// be re-confirmed after a claim was reworded; a parent edge can be detached.
function EdgePanel({ pending, slug, nodes, onClose, onDone }) {
  const { edge, at } = pending
  const d = edge.data || {}
  const [retracting, setRetracting] = useState(false)
  const [reason, setReason] = useState('')
  const [err, setErr] = useState(null)

  const run = async (fn) => {
    setErr(null)
    const r = await fn()
    if (r && r.error) { setErr(r.error); return }
    onDone()
  }
  const targetLabel = () => (nodes.find((n) => n.id === edge.target) || {}).data?.label

  const style = at ? {
    left: Math.max(12, Math.min(at.x - 150, window.innerWidth - 312)),
    top: Math.max(12, Math.min(at.y + 10, window.innerHeight - 240)),
    right: 'auto',
  } : undefined

  return (
    <div className="gpanel" style={style}>
      <div className="eyebrow" style={{ margin: '0 0 8px' }}>
        {(d.kind || '').replace(/_/g, ' ')} · {d.etype}
      </div>
      {d.etype === 'evidence' && (
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          {d.grade}{d.run_id ? ` · run #${d.run_id}` : ''}{d.citation_id ? ` · citation #${d.citation_id}` : ''}
          {d.run_id ? (d.preregistered ? ' · ⚑ pre-registered' : ' · exploratory (post-hoc)') : ''}
          {d.stale ? ' · STALE — claim reworded since' : ''}
          {d.note ? ` — ${d.note}` : ''}
        </div>
      )}
      {d.etype !== 'evidence' && d.note && (
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>{d.note}</div>
      )}
      {err && <div style={{ color: 'var(--bad)', marginBottom: 6, fontSize: 12 }}>{err}</div>}
      {retracting ? (
        <>
          <textarea autoFocus placeholder="Why is this evidence retracted? (required)"
                    value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="gnode-actions">
            <button className="btn" disabled={!reason.trim()}
                    onClick={() => run(() => retractEvidence(d.eid, reason.trim()))}>Retract</button>
            <button className="btn ghost" onClick={() => setRetracting(false)}>Cancel</button>
          </div>
        </>
      ) : (
        <div className="gnode-actions">
          {d.etype === 'context' && (
            <button className="btn ghost" onClick={() => run(() => deleteContextLink(d.eid))}>Remove link</button>
          )}
          {d.etype === 'relation' && (
            <button className="btn ghost" onClick={() => run(() => deleteClaimRelation(d.eid))}>Remove relation</button>
          )}
          {d.etype === 'tests' && (
            <button className="btn ghost" onClick={() => run(() => undeclareTest(d.eid))}>Remove declaration</button>
          )}
          {d.etype === 'parent' && (
            <button className="btn ghost"
                    onClick={() => run(() => setExperimentParent(slug, targetLabel(), null))}>Detach from parent</button>
          )}
          {d.etype === 'evidence' && d.stale ? (
            <button className="btn" onClick={() => run(() => confirmEvidence(d.eid))}>Still valid</button>
          ) : null}
          {d.etype === 'evidence' && (
            <button className="btn ghost" onClick={() => setRetracting(true)}>Retract…</button>
          )}
          <button className="btn ghost" onClick={onClose}>Close</button>
        </div>
      )}
    </div>
  )
}

// Full-height phase bands behind the graph: a plan phase projected onto the
// canvas x-axis. Left→right is the arrow of the project. Grips on both edges
// resize; the top tab moves the whole band; membership is geometric (node
// center-x), computed by the server for lint, mirrored here for hover.
function PhaseBands({ phases, hover, flowRef, onLive, onCommit }) {
  const drag = React.useRef(null)
  const startDrag = (p, edge) => (e) => {
    e.preventDefault()
    e.stopPropagation()
    const zoom = (flowRef.current?.getViewport?.() || {}).zoom || 1
    drag.current = { id: p.id, edge, sx: e.clientX, x0: p.x0, x1: p.x1, zoom }
    const move = (ev) => {
      const s = drag.current
      if (!s) return
      const dx = (ev.clientX - s.sx) / s.zoom
      let x0 = s.x0, x1 = s.x1
      if (s.edge === 'l') x0 = Math.min(s.x0 + dx, s.x1 - 80)
      else if (s.edge === 'r') x1 = Math.max(s.x1 + dx, s.x0 + 80)
      else { x0 = s.x0 + dx; x1 = s.x1 + dx }
      onLive(s.id, x0, x1)
    }
    const up = () => {
      const s = drag.current
      drag.current = null
      window.removeEventListener('pointermove', move)
      if (s) onCommit(s.id)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up, { once: true })
  }
  return (
    <ViewportPortal>
      {phases.map((p, i) => (
        <div key={p.id}
             className={`phase-band ${p.color ? 'phase-' + p.color : 'phase-c-' + (i % 6)}${hover === p.id ? ' hl' : ''}`}
             style={{ left: p.x0, width: p.x1 - p.x0 }}>
          <div className="phase-band-grip l nopan nodrag" onPointerDown={startDrag(p, 'l')} />
          <div className="phase-band-grip r nopan nodrag" onPointerDown={startDrag(p, 'r')} />
        </div>
      ))}
    </ViewportPortal>
  )
}

// Screen-anchored phase names: each placed band carries its name near the top
// of the view, tucked into the band's top-right corner (it pans/zooms with the
// band horizontally, stays pinned vertically). Hover highlights the band and
// its boundary-crossing edges; ◑ recolors; unplaced phases dock top-left.
function PhaseLabel({ p, colorClass, hovered, setHover, onFocus, onColor, onRename, style }) {
  const [menu, setMenu] = useState(false)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(p.title)
  const save = () => {
    setEditing(false)
    if (text.trim() && text.trim() !== p.title) onRename(p, text.trim())
  }
  return (
    <div className={`phase-label ${colorClass}${hovered ? ' hl' : ''}${p.status === 'done' ? ' done' : ''}`}
         style={style}
         onMouseEnter={() => setHover(p.id)}
         onMouseLeave={() => { setHover(null); setMenu(false) }}>
      {editing ? (
        <input className="region-input phase-input" autoFocus value={text}
               onChange={(e) => setText(e.target.value)} onBlur={save}
               onKeyDown={(e) => {
                 if (e.key === 'Enter') e.target.blur()
                 if (e.key === 'Escape') { setText(p.title); setEditing(false) }
               }} />
      ) : (
        <span className="phase-label-name"
              title={`${p.start || '…'} → ${p.due}${p.status === 'done' ? ' · done' : ''} — click to rename, double-click to zoom`}
              onClick={(e) => { e.stopPropagation(); setText(p.title); setEditing(true) }}
              onDoubleClick={(e) => { e.stopPropagation(); setEditing(false); onFocus(p) }}>
          {p.title}
        </span>
      )}
      <button className="region-btn" title="Color"
              onClick={(e) => { e.stopPropagation(); setMenu(!menu) }}>◑</button>
      {menu && (
        <div className="region-menu phase-label-menu">
          {REGION_COLORS.map((c) => (
            <button key={c} className={`region-swatch region-${c}`} title={c}
                    onClick={() => { setMenu(false); onColor(p, c) }} />
          ))}
        </div>
      )}
    </div>
  )
}

function PhaseLabels({ phases, viewport, hover, setHover, onFocus, onColor, onRename, onPlace }) {
  const placed = phases.filter((p) => p.x0 != null)
  const unplaced = phases.filter((p) => p.x0 == null)
  return (
    <div className="phase-labels">
      {placed.map((p, i) => (
        <PhaseLabel key={p.id} p={p}
                    colorClass={p.color ? 'phase-' + p.color : 'phase-c-' + (i % 6)}
                    hovered={hover === p.id} setHover={setHover}
                    onFocus={onFocus} onColor={onColor} onRename={onRename}
                    style={{
                      left: p.x1 * viewport.zoom + viewport.x,
                      // never reach past the band's own left edge — neighbors stay legible
                      maxWidth: Math.max(36, (p.x1 - p.x0) * viewport.zoom - 24),
                      // scale with the canvas, exactly like region titles do
                      fontSize: 11 * viewport.zoom,
                    }} />
      ))}
      {unplaced.length > 0 && (
        <div className="phase-unplaced">
          {unplaced.map((p) => (
            <button key={p.id} className="phasechip unplaced" onClick={() => onPlace(p)}
                    title="This plan phase has no canvas band yet — click to place one at the view center">
              ＋ {p.title}
            </button>
          ))}
        </div>
      )}
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
  const [showRegions, setShowRegions] = useState(() => localStorage.getItem('reref-regions') !== 'off')
  const showRegionsRef = React.useRef(showRegions)
  showRegionsRef.current = showRegions
  const [conns, setConns] = useState([])            // the connection registry
  const [phases, setPhases] = useState([])          // plan phases + canvas bands
  const [showPhases, setShowPhases] = useState(() => localStorage.getItem('reref-phasebands') !== 'off')
  const [hoverPhase, setHoverPhase] = useState(null)
  const [edgeAction, setEdgeAction] = useState(null) // {edge, at} — edge click panel
  const [viewport, setViewport] = useState({ x: 0, y: 0, zoom: 1 })
  const phasesRef = React.useRef(phases)
  phasesRef.current = phases
  const promoteRef = React.useRef(null)             // {node, mode} while promoting
  const flowRef = React.useRef(null)

  useEffect(() => { getConnections().then((c) => setConns(Array.isArray(c) ? c : [])) }, [])
  const optionsFor = (from, to) =>
    (conns.find((c) => c.from === from && c.to === to) || {}).options || []
  const dropPos = React.useRef(null)                 // where a right-click add should land

  // promote: spawn the experiment a question/hypothesis calls for, pre-wired
  const startPromote = useCallback((node, mode) => {
    promoteRef.current = { node, mode }
    dropPos.current = { x: node.position.x + 300, y: node.position.y }
    setMenuAt(null)
    setAdding('experiment')
  }, [])

  const load = useCallback(async () => {
    setBusy(true)
    const [g, regions, phaseRows] = await Promise.all(
      [getGraph(slug), getRegions(slug), getPhases(slug)])
    setPhases(Array.isArray(phaseRows) ? phaseRows : [])
    const flow = toFlow(g)
    const after = () => { load(); onMutate && onMutate() }
    flow.nodes.forEach((n) => {
      n.data.defs = defs
      n.zIndex = 1                       // entity nodes sit above region frames
      const [k, id] = n.id.split(':')
      if (k === 'claim') {
        n.data.onSaveText = (t) => editClaim(Number(id), t).then(after)
        if (n.data.kind === 'hypothesis') n.data.onPromote = () => startPromote(n, 'claim')
      }
      else if (k === 'log') {
        n.data.onSaveText = (t) => editLog(Number(id), t).then(after)
        if (n.type === 'question' || n.type === 'hypothesis')
          n.data.onPromote = () => startPromote(n, 'log')
      }
      else if (k === 'note') n.data.onSaveText = (t) => editNote(Number(id), t).then(after)
      else if (k === 'exp') {
        n.data.onSaveText = (t) => editExperiment(slug, n.data.label, { title: t }).then(after)
        n.data.onSaveSlug = (t) => editExperiment(slug, n.data.label, { new_slug: t }).then(after)
        n.data.onSaveHyp = (t) => editExperiment(slug, n.data.label, { hypothesis: t }).then(after)
      }
      else if (k === 'pnote') n.data.onSaveText = (t) => updatePaperNote(Number(id), { body_md: t }).then(after)
      else if (k === 'paper') n.data.onSaveText = (t) => editPaper(Number(id), t).then(after)
      if (n.type === 'finding') {
        n.data.id = Number(id)
        n.data.onDone = after
      }
    })
    // region frames as background nodes: dragged by their label bar, resizable;
    // the phases a region belongs to are DERIVED from its surface overlap
    const regionNodes = (Array.isArray(regions) ? regions : []).map((r) => ({
      id: `region:${r.id}`, type: 'region', position: { x: r.x, y: r.y },
      style: { width: r.w, height: r.h }, zIndex: 0, draggable: true,
      dragHandle: '.region-bar', selectable: false, hidden: !showRegionsRef.current,
      data: {
        label: r.label, color: r.color, onChange: after,
        phaseNames: r.phases || [],
      },
    }))
    setNodes([...regionNodes, ...flow.nodes])
    setEdges(flow.edges)
    setBusy(false)
    // fit AFTER the async data lands — the mount-time fitView saw an empty canvas
    requestAnimationFrame(() => {
      flowRef.current?.fitView({ padding: 0.18, maxZoom: 1 })
      if (flowRef.current) setViewport(flowRef.current.getViewport())
    })
  }, [slug, defs, onMutate, setNodes, setEdges, startPromote])

  useEffect(() => { load() }, [load])

  // hovering a phase chip: tint its band, light up the edges that cross its
  // boundary (the arguments moving the project forward), dim the rest
  useEffect(() => {
    const inst = flowRef.current
    const band = phasesRef.current.find((p) => p.id === hoverPhase)
    if (!inst || !band || band.x0 == null) {
      setEdges((es) => es.map((e) => (e.className ? { ...e, className: undefined } : e)))
      return
    }
    const inside = new Set(inst.getNodes()
      .filter((n) => !n.id.startsWith('region:'))
      .filter((n) => {
        const cx = n.position.x + (n.measured?.width || n.width || 220) / 2
        return cx >= band.x0 && cx < band.x1
      })
      .map((n) => n.id))
    setEdges((es) => es.map((e) => ({
      ...e,
      className: inside.has(e.source) !== inside.has(e.target) ? 'phase-hl' : 'phase-dim',
    })))
  }, [hoverPhase, setEdges])

  // band drag: optimistic while moving, one store write on release
  const liveBand = useCallback((id, x0, x1) =>
    setPhases((ps) => ps.map((p) => (p.id === id ? { ...p, x0, x1 } : p))), [])
  const commitBand = useCallback((id) => {
    const p = phasesRef.current.find((x) => x.id === id)
    if (p && p.x0 != null) setPhaseBand(id, p.x0, p.x1)
  }, [])
  const placePhase = useCallback(async (p) => {
    const inst = flowRef.current
    const c = inst?.screenToFlowPosition
      ? inst.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
      : { x: 0 }
    const r = await setPhaseBand(p.id, c.x - 300, c.x + 300)
    if (r && r.error) { say(r.error, true); return }
    getPhases(slug).then((rows) => setPhases(Array.isArray(rows) ? rows : []))
  }, [slug])
  const focusPhase = useCallback((p) => {
    const inst = flowRef.current
    if (!inst || p.x0 == null) return
    const ys = inst.getNodes().filter((n) => !n.id.startsWith('region:')).map((n) => n.position.y)
    const y0 = ys.length ? Math.min(...ys) - 80 : -200
    const y1 = ys.length ? Math.max(...ys) + 200 : 600
    inst.fitBounds({ x: p.x0, y: y0, width: p.x1 - p.x0, height: y1 - y0 },
                   { padding: 0.06, duration: 350 })
  }, [])

  // toggle region visibility without a full reload
  useEffect(() => {
    setNodes((ns) => ns.map((n) =>
      n.id.startsWith('region:') ? { ...n, hidden: !showRegions } : n))
  }, [showRegions, setNodes])

  const say = (msg, bad) => {
    setToast({ msg, bad })
    setTimeout(() => setToast(null), 5000)
  }

  const persistPositions = useCallback((_, node) => {
    if (node?.id?.startsWith('region:')) {   // regions persist to their own table
      updateRegion(Number(node.id.split(':')[1]), { x: node.position.x, y: node.position.y })
      return
    }
    const inst = flowRef.current
    if (!inst) return
    const positions = Object.fromEntries(inst.getNodes()
      .filter((n) => !n.id.startsWith('region:'))
      .map((n) => [n.id, n.position]))
    saveLayout(slug, positions)
  }, [slug])

  const addRegionAtCenter = useCallback(async () => {
    const inst = flowRef.current
    let p = { x: 0, y: 0 }
    if (inst?.screenToFlowPosition) {
      p = inst.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
    }
    await addRegion(slug, { x: p.x - 180, y: p.y - 120, w: 360, h: 240, label: '' })
    load()
  }, [slug, load])

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

  // Double-click opens the entity: papers/notes into the PDF viewer, the rest
  // deep-link into their page.
  const onNodeDoubleClick = useCallback((_, node) => {
    const [k, id] = node.id.split(':')
    const at = (sub) => navigate('/' + encodeURIComponent(slug) + '/' + sub)
    if (k === 'exp') at('experiments/' + encodeURIComponent(node.data.label))
    else if (k === 'claim') at('claims/' + id)
    else if (k === 'log') at('log/' + encodeURIComponent('log-' + id))
    else if (k === 'note') at('log/' + encodeURIComponent('note-' + id))
    else if (k === 'paper') at('papers/' + encodeURIComponent(node.data.label))
    else if (k === 'pnote') at('papers/' + encodeURIComponent(node.data.paper_key))
    else if (k === 'finding') at('findings')
  }, [slug])

  const onPaneContextMenu = useCallback((e) => {
    e.preventDefault()
    const inst = flowRef.current
    dropPos.current = inst ? inst.screenToFlowPosition({ x: e.clientX, y: e.clientY }) : null
    setMenu({ x: e.clientX, y: e.clientY })
    setMenuAt({ x: e.clientX, y: e.clientY })
  }, [])

  const addDone = async (nodeId, created) => {
    setAdding(null)
    if (nodeId && dropPos.current) {   // pin the new node where the user right-clicked
      await saveLayout(slug, { [nodeId]: dropPos.current })
      dropPos.current = null
    }
    // promote: wire the new experiment back to what spawned it — a hypothesis
    // claim gets a pre-registered `tests` edge, a thought gets `motivates`
    const promo = promoteRef.current
    if (promo && created?.id && nodeId?.startsWith('exp:')) {
      const [, srcId] = promo.node.id.split(':')
      const r = promo.mode === 'claim'
        ? await declareTest(slug, created.slug, Number(srcId))
        : await addContextLink({ project: slug, from_kind: promo.node.type,
                                 from_id: Number(srcId), to_kind: 'experiment',
                                 to_id: created.id, relation: 'motivates' })
      if (r && r.error) say(r.error, true)
    }
    promoteRef.current = null
    load(); onMutate && onMutate()
  }

  const onEdgeClick = useCallback((e, edge) => {
    if (!edge.data?.etype) return   // structural edge (cited/annotates/…) — nothing to act on
    e.stopPropagation()
    setEdgeAction({ edge, at: { x: e.clientX, y: e.clientY } })
  }, [])

  // papers/claims/experiments open on single click — in place, or in a new
  // browser tab with ⌘/ctrl. Inline editors stopPropagation, so clicking text
  // still edits; clicking the card navigates.
  const onNodeClick = useCallback((e, node) => {
    const [k, id] = node.id.split(':')
    const sub = k === 'paper' ? 'papers/' + encodeURIComponent(node.data.label)
      : k === 'claim' ? 'claims/' + id
      : k === 'exp' ? 'experiments/' + encodeURIComponent(node.data.label)
      : null
    if (!sub) return
    const path = '/' + encodeURIComponent(slug) + '/' + sub
    if (e.metaKey || e.ctrlKey) window.open(location.origin + path, '_blank')
    else navigate(path)
  }, [slug])

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
        onPaneClick={() => { setMenu(null); setEdgeAction(null) }}
        onEdgeClick={onEdgeClick}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        onInit={(inst) => {
          flowRef.current = inst
          inst.fitView({ padding: 0.18, maxZoom: 1 })
          setViewport(inst.getViewport())
        }}
        onMove={(_, vp) => setViewport(vp)}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={22} size={1.2} color="var(--line-strong)" />
        {showPhases && (
          <PhaseBands phases={phases.filter((p) => p.x0 != null)} hover={hoverPhase}
                      flowRef={flowRef} onLive={liveBand} onCommit={commitBand} />
        )}
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
                  initial={promoteRef.current ? {
                    title: (promoteRef.current.node.data.text || '').slice(0, 80),
                    hypothesis: promoteRef.current.node.data.text || '',
                  } : undefined}
                  onClose={() => { promoteRef.current = null; setAdding(null) }}
                  onDone={addDone} />
      )}
      {pendingEdge && (
        <ConnectPanel pending={pendingEdge} slug={slug}
                      onClose={() => setPendingEdge(null)}
                      onDone={() => { setPendingEdge(null); load(); onMutate && onMutate() }} />
      )}
      {edgeAction && (
        <EdgePanel pending={edgeAction} slug={slug} nodes={nodes}
                   onClose={() => setEdgeAction(null)}
                   onDone={() => { setEdgeAction(null); load(); onMutate && onMutate() }} />
      )}
      {showPhases && phases.length > 0 && (
        <PhaseLabels phases={phases} viewport={viewport}
                     hover={hoverPhase} setHover={setHoverPhase}
                     onFocus={focusPhase} onPlace={placePhase}
                     onColor={(p, c) => setPhaseBandColor(p.id, c).then(() =>
                       getPhases(slug).then((rows) => setPhases(Array.isArray(rows) ? rows : [])))}
                     onRename={(p, title) => updatePlanItem(p.id, { title }).then(() => {
                       getPhases(slug).then((rows) => setPhases(Array.isArray(rows) ? rows : []))
                       onMutate && onMutate()
                     })} />
      )}
      {menu && (
        <div className="gmenu" style={{ left: menu.x, top: menu.y }}>
          {[['experiment', 'var(--accent)'], ['claim', 'var(--claim)'],
            ['question', 'var(--warn)'], ['hypothesis', 'var(--citation)'],
            ['feedback', 'var(--code-kind)'], ['decision', 'var(--ok)'],
            ['blocker', 'var(--bad)'], ['observation', 'var(--paper-kind)'],
            ['note', 'var(--line-strong)']].map(([k, c]) => (
            <button key={k} onClick={() => { setAdding(k); setMenu(null) }}>
              <span className="sw" style={{ background: c }} />New {k}
            </button>
          ))}
          <button onClick={() => { addRegionAtCenter(); setMenu(null) }}>
            <span className="sw" style={{ background: 'var(--line-strong)' }} />New region
          </button>
        </div>
      )}

      <div className="glegend-row">
        <div className="glegend closed">
          <button className="glegend-head" title="Show or hide phase bands (plan phases on the canvas x-axis)"
                  onClick={() => {
                    const next = !showPhases
                    setShowPhases(next)
                    localStorage.setItem('reref-phasebands', next ? 'on' : 'off')
                  }}>
            <span className="lamp" style={{ background: showPhases ? 'var(--accent)' : 'var(--line-strong)' }} />
            <span className="eyebrow" style={{ margin: 0 }}>Phases</span>
          </button>
        </div>
        <div className="glegend closed">
          <button className="glegend-head" title="Show or hide region frames"
                  onClick={() => {
                    const next = !showRegions
                    setShowRegions(next)
                    localStorage.setItem('reref-regions', next ? 'on' : 'off')
                  }}>
            <span className="lamp" style={{ background: showRegions ? 'var(--accent)' : 'var(--line-strong)' }} />
            <span className="eyebrow" style={{ margin: 0 }}>Regions</span>
          </button>
        </div>
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
