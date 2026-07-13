import dagre from '@dagrejs/dagre'

const SIZE = { width: 220, height: 96 }

// Map the backend's neutral {nodes, edges} into React Flow nodes/edges, then run a
// dagre layered layout so the experiment branches read left→right.
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
      position: { x: p.x - SIZE.width / 2, y: p.y - SIZE.height / 2 },
      data: { label: n.label, ...n.data },
    }
  })

  const stroke = (kind) =>
    kind === 'refutes' || kind === 'contradicts' ? 'var(--bad)'
    : kind === 'supports' ? 'var(--ok)'
    : kind === 'depends_on' ? 'var(--claim)'
    : kind === 'parent' ? 'var(--line-strong)'
    : 'var(--line)'

  const LABELLED = new Set(['supports', 'refutes', 'depends_on', 'contradicts'])
  const edges = graph.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    label: LABELLED.has(e.kind) ? e.kind.replace('_', ' ') : '',
    animated: e.kind === 'refutes' || e.kind === 'contradicts',
    style: {
      stroke: stroke(e.kind),
      strokeWidth: e.kind === 'parent' ? 1.6 : 1.2,
      strokeDasharray: e.kind === 'depends_on' || e.kind === 'contradicts' ? '5 4' : undefined,
    },
  }))

  return { nodes, edges }
}
