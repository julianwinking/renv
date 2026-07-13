import React, { useState } from 'react'
import { Handle, Position } from '@xyflow/react'

const STAT = { planned: '○', running: '▶', done: '✓', abandoned: '✗' }
const SEVCLASS = { high: 'sev-high', medium: 'sev-medium', low: 'sev-low' }
const CSTAT = { open: '○ open', supported: '✓ supported', refuted: '✗ refuted' }

function Shell({ kind, children }) {
  return (
    <div className={`node node-${kind}`}>
      <Handle type="target" position={Position.Left} />
      {children}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

// Experiment node: status + metrics; expand to show the hypothesis.
export function ExperimentNode({ data }) {
  const [open, setOpen] = useState(false)
  const mets = Object.entries(data.metrics || {})
  return (
    <Shell kind="experiment">
      <div className="node-head" onClick={() => setOpen(!open)}>
        <span className="ic">{STAT[data.status] || '?'}</span>
        <b>{data.label}</b>
      </div>
      <div className="node-sub">{data.title}</div>
      {mets.length > 0 && (
        <div className="chips">
          {mets.map(([k, v]) => (
            <span key={k} className="chip">{k}={v}</span>
          ))}
        </div>
      )}
      {open && data.hypothesis && <div className="node-detail">⌖ {data.hypothesis}</div>}
    </Shell>
  )
}

// Finding node: severity + issue, with inline adjudication branches.
export function FindingNode({ data }) {
  return (
    <Shell kind="finding">
      <div className="node-head">
        <span className={SEVCLASS[data.severity]}>{(data.severity || '').toUpperCase()}</span>
        <b>{data.label}</b>
      </div>
      <div className="node-sub">{data.issue}</div>
      <div className="node-actions">
        <button onClick={() => data.onAdjudicate?.(data.id, 'accept')}>accept</button>
        <button className="danger" onClick={() => data.onAdjudicate?.(data.id, 'reject')}>reject</button>
      </div>
    </Shell>
  )
}

export function ClaimNode({ data }) {
  return (
    <Shell kind="claim">
      <div className="node-head">
        <span className="chip">{data.kind}</span>
        <span className={`cstat ${data.status}`}>{CSTAT[data.status] || data.status}</span>
      </div>
      <div className="node-sub">{data.text}</div>
    </Shell>
  )
}

export function CitationNode({ data }) {
  return (
    <Shell kind="citation">
      <div className="node-head"><b>{data.label}</b><span className="pill">{data.support}</span></div>
      {data.quote && <div className="node-sub mono">“{(data.quote || '').slice(0, 60)}…”</div>}
    </Shell>
  )
}

export function PaperNode({ data }) {
  return (
    <Shell kind="paper">
      <div className="node-head">📄 <b>{data.label}</b></div>
    </Shell>
  )
}

// Code reference node: a @reref tag in the codebase pointing at a store entity.
export function CodeNode({ data }) {
  return (
    <Shell kind="code">
      <div className="node-head">{'</>'} <b className="mono">{data.label}</b></div>
      {data.text && <div className="node-sub">{data.text}</div>}
    </Shell>
  )
}

export const nodeTypes = {
  experiment: ExperimentNode,
  finding: FindingNode,
  claim: ClaimNode,
  citation: CitationNode,
  paper: PaperNode,
  code: CodeNode,
}
