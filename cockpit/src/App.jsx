import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState,
} from '@xyflow/react'
import { getOverview, getGraph, adjudicate, search } from './api.js'
import { toFlow } from './layout.js'
import { nodeTypes } from './nodes.jsx'

export default function App() {
  const [overview, setOverview] = useState(null)
  const [slug, setSlug] = useState(null)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [busy, setBusy] = useState(false)
  const [hits, setHits] = useState(null)

  const runSearch = useCallback(async (q) => {
    if (!q.trim()) { setHits(null); return }
    setHits(await search(q))
  }, [])

  const loadOverview = useCallback(async () => {
    const o = await getOverview()
    setOverview(o)
    setSlug((cur) => cur || o.projects[0]?.slug || null)
  }, [])

  const onAdjudicate = useCallback(async (id, verdict) => {
    const reasoning = window.prompt(
      `Reasoning for ${verdict} (visible to future agents; rejected findings are never re-raised):`
    )
    if (!reasoning) return
    const r = await adjudicate(id, verdict, reasoning)
    if (r.error) alert(r.error)
    else loadGraph(slug)
  }, [slug])

  const loadGraph = useCallback(async (s) => {
    if (!s) return
    setBusy(true)
    const g = await getGraph(s)
    const flow = toFlow(g)
    // inject the finding id + adjudicate handler into finding node data
    flow.nodes.forEach((n) => {
      if (n.type === 'finding') {
        n.data.id = Number(n.id.split(':')[1])
        n.data.onAdjudicate = onAdjudicate
      }
    })
    setNodes(flow.nodes)
    setEdges(flow.edges)
    setBusy(false)
  }, [onAdjudicate, setNodes, setEdges])

  useEffect(() => { loadOverview() }, [loadOverview])
  useEffect(() => { loadGraph(slug) }, [slug, loadGraph])

  const counts = overview?.counts || {}

  return (
    <div className="app">
      <aside>
        <h1>re<span>ref</span> cockpit</h1>
        <input className="search" placeholder="search papers, notes, claims…"
               onKeyDown={(e) => { if (e.key === 'Enter') runSearch(e.target.value) }} />
        {hits && (
          <div className="hits">
            <div className="navgroup">{hits.length} result(s)</div>
            {hits.map((h, i) => (
              <div key={i} className="hit">
                <span className="chip">{h.kind}</span> <b>{h.title}</b>
                <div className="muted">{h.snippet}</div>
              </div>
            ))}
          </div>
        )}
        <div className="stats">
          {['paper', 'experiment', 'claim', 'finding'].map((k) => (
            <div key={k} className="stat"><b>{counts[k] ?? '–'}</b><span>{k}s</span></div>
          ))}
        </div>
        <div className="navgroup">Projects</div>
        {(overview?.projects || []).map((p) => (
          <div key={p.slug}
               className={`navitem ${p.slug === slug ? 'active' : ''}`}
               onClick={() => setSlug(p.slug)}>
            <span>{p.title || p.slug}</span>
            {p.open_findings > 0 && <span className="badge">{p.open_findings}</span>}
          </div>
        ))}
        {overview && overview.projects.length === 0 && (
          <div className="muted">no projects — <code>reref new &lt;slug&gt;</code></div>
        )}
        <div className="legend">
          <div className="navgroup">Graph</div>
          <span className="k k-experiment">experiment</span>
          <span className="k k-claim">claim</span>
          <span className="k k-finding">finding</span>
          <span className="k k-citation">citation</span>
          <span className="k k-paper">paper</span>
          <span className="k k-code">code</span>
        </div>
      </aside>

      <main>
        {!slug && <div className="empty">Select a project</div>}
        {slug && (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} color="#222732" />
            <MiniMap pannable zoomable nodeColor={() => '#2b3242'} maskColor="rgba(8,10,14,.7)" />
            <Controls />
          </ReactFlow>
        )}
        {busy && <div className="toast">loading…</div>}
      </main>
    </div>
  )
}
