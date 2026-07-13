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

  const CONTEXT = new Set(['relates_to', 'about', 'motivates', 'raises'])
  const stroke = (e) =>
    e.kind === 'refutes' || e.kind === 'contradicts' ? 'var(--bad)'
    : e.kind === 'supports' || e.kind === 'answers' ? 'var(--ok)'
    : e.kind === 'depends_on' ? 'var(--claim)'
    : e.context || CONTEXT.has(e.kind) ? 'var(--faint)'
    : e.kind === 'parent' ? 'var(--line-strong)'
    : 'var(--line)'

  const LABELLED = new Set(['supports', 'refutes', 'depends_on', 'contradicts',
                            'answers', 'relates_to', 'about', 'motivates', 'raises'])
  const edges = graph.edges.map((e, i) => {
    const isContext = e.context || CONTEXT.has(e.kind)
    const base = LABELLED.has(e.kind) ? e.kind.replace(/_/g, ' ') : ''
    const note = e.note ? ` — ${e.note.length > 30 ? e.note.slice(0, 30) + '…' : e.note}` : ''
    const s = stroke(e)
    return {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      label: base ? base + note : '',
      animated: e.kind === 'refutes' || e.kind === 'contradicts',
      markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color: s },
      style: {
        stroke: s,
        strokeWidth: e.kind === 'parent' ? 1.6 : 1.2,
        strokeDasharray: (e.kind === 'depends_on' || e.kind === 'contradicts') ? '5 4'
          : isContext ? '2 3' : undefined,
      },
    }
  })

  return { nodes, edges }
}
