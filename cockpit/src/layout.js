import dagre from '@dagrejs/dagre'

const SIZE = { width: 210, height: 92 }

// Map the backend's neutral {nodes, edges} into React Flow nodes/edges, then run a
// dagre layered layout so the experiment branches read left→right.
export function toFlow(graph, dir = 'LR') {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: dir, nodesep: 30, ranksep: 90, marginx: 20, marginy: 20 })

  graph.nodes.forEach((n) => g.setNode(n.id, SIZE))
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

  const edges = graph.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    label: e.kind === 'parent' ? '' : e.kind,
    animated: e.kind === 'supports' || e.kind === 'refutes',
    style: { stroke: e.kind === 'refutes' ? '#f0727f' : e.kind === 'supports' ? '#5bd6a0' : '#3a4150' },
  }))

  return { nodes, edges }
}
