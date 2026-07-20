import dagre from '@dagrejs/dagre'
import { MarkerType } from '@xyflow/react'

const SIZE = { width: 220, height: 96 }

// Map the backend's neutral {nodes, edges} into React Flow nodes/edges. Nodes
// with a hand-saved position (graph_layout) keep it; the rest get a dagre
// layered layout so experiment branches read left→right.
export function toFlow(graph, dir = 'LR') {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: dir, nodesep: 36, ranksep: 110, marginx: 24, marginy: 24 })

  // one object PER node — dagre writes x/y into the object it is handed,
  // so sharing one literal stacks every node at the last position
  graph.nodes.forEach((n) => g.setNode(n.id, { ...SIZE }))
  graph.edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)

  const nodes = graph.nodes.map((n) => {
    const p = g.node(n.id)
    return {
      id: n.id,
      type: n.kind,
      position: n.pos ? { x: n.pos.x, y: n.pos.y }
                      : { x: p.x - SIZE.width / 2, y: p.y - SIZE.height / 2 },
      data: { label: n.label, ...n.data },
    }
  })

  const CONTEXT = new Set(['relates_to', 'about', 'motivates', 'raises',
                           'informs', 'concerns', 'annotates', 'suggests',
                           'based_on', 'blocks', 'resolves'])
  const stroke = (e) =>
    e.kind === 'refutes' || e.kind === 'contradicts' || e.kind === 'blocks' ? 'var(--bad)'
    : e.data?.stale ? 'var(--warn)'
    : e.kind === 'supports' || e.kind === 'answers' || e.kind === 'resolves' ? 'var(--ok)'
    : e.kind === 'inconclusive' ? 'var(--warn)'
    : e.kind === 'depends_on' ? 'var(--claim)'
    : e.kind === 'tests' ? 'var(--accent)'
    : e.context || CONTEXT.has(e.kind) ? 'var(--faint)'
    : e.kind === 'parent' ? 'var(--line-strong)'
    : 'var(--line)'

  const LABELLED = new Set(['supports', 'refutes', 'inconclusive', 'tests',
                            'depends_on', 'contradicts',
                            'answers', 'relates_to', 'about', 'motivates', 'raises',
                            'informs', 'concerns', 'annotates', 'suggests',
                            'based_on', 'blocks', 'resolves'])
  const edges = graph.edges.map((e, i) => {
    const isContext = e.context || CONTEXT.has(e.kind)
    let base = LABELLED.has(e.kind) ? e.kind.replace(/_/g, ' ') : ''
    if (e.kind === 'tests') base = 'will test'
    // evidence edges wear their epistemics: strength grade, pre-registration
    // flag (⚑ = declared before running), staleness (claim reworded since)
    if (e.etype === 'evidence') {
      if (e.grade && e.grade !== 'suggestive') base += ` · ${e.grade}`
      if (e.preregistered) base = '⚑ ' + base
      if (e.stale) base += ' · stale'
    }
    const note = e.note ? ` — ${e.note.length > 30 ? e.note.slice(0, 30) + '…' : e.note}` : ''
    const data = { etype: e.etype, eid: e.eid, kind: e.kind, note: e.note,
                   grade: e.grade, stale: e.stale, preregistered: e.preregistered,
                   run_id: e.run_id, citation_id: e.citation_id }
    const s = stroke({ ...e, data })
    return {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      label: base ? base + note : '',
      animated: e.kind === 'refutes' || e.kind === 'contradicts',
      markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color: s },
      data,
      style: {
        stroke: s,
        strokeWidth: e.kind === 'parent' ? 1.6 : 1.2,
        strokeDasharray: (e.kind === 'depends_on' || e.kind === 'contradicts') ? '5 4'
          : e.kind === 'tests' ? '6 3'
          : isContext ? '2 3' : undefined,
      },
    }
  })

  return { nodes, edges }
}
