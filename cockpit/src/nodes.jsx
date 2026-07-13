import React, { useState } from 'react'
import { Handle, Position } from '@xyflow/react'
import { adjudicate } from './api.js'
import { Stamp, Metrics } from './ui.jsx'

function Shell({ kind, children }) {
  return (
    <div className={`gnode gnode-${kind}`}>
      <Handle type="target" position={Position.Left} />
      {children}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

// Experiment: status stamp + formatted metrics; click to reveal the hypothesis.
export function ExperimentNode({ data }) {
  const [open, setOpen] = useState(false)
  return (
    <Shell kind="experiment">
      <div className="gnode-head" onClick={() => setOpen(!open)} style={{ cursor: 'pointer' }}>
        <b className="mono">{data.label}</b>
        <span style={{ marginLeft: 'auto' }}><Stamp value={data.status} /></span>
      </div>
      <div className="gnode-sub">{data.title}</div>
      <Metrics defs={data.defs} metrics={data.metrics} />
      {open && data.hypothesis && (
        <div className="gnode-sub" style={{ WebkitLineClamp: 6, marginTop: 6 }}>
          <span className="gnode-kind">hypothesis · </span>{data.hypothesis}
        </div>
      )}
    </Shell>
  )
}

// Finding: severity + issue, adjudicated inline with required reasoning.
export function FindingNode({ data }) {
  const [verdict, setVerdict] = useState(null)
  const [reason, setReason] = useState('')

  const submit = async () => {
    if (!reason.trim()) return
    const r = await adjudicate(data.id, verdict, reason.trim())
    if (!r.error) data.onDone?.()
  }

  return (
    <Shell kind="finding">
      <div className="gnode-head">
        <Stamp value={data.severity} />
        <b className="mono">{data.label}</b>
      </div>
      <div className="gnode-sub">{data.issue}</div>
      {!verdict && (
        <div className="gnode-actions">
          <button className="btn ghost" onClick={() => setVerdict('accept')}>accept</button>
          <button className="btn ghost" onClick={() => setVerdict('reject')}>reject</button>
        </div>
      )}
      {verdict && (
        <>
          <textarea
            className="nodrag"
            placeholder={`why ${verdict}?`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="gnode-actions">
            <button className="btn" onClick={submit}>save</button>
            <button className="btn ghost" onClick={() => setVerdict(null)}>cancel</button>
          </div>
        </>
      )}
    </Shell>
  )
}

export function ClaimNode({ data }) {
  return (
    <Shell kind="claim">
      <div className="gnode-head">
        <span className="gnode-kind">{data.kind}</span>
        <span style={{ marginLeft: 'auto' }}><Stamp value={data.status} /></span>
      </div>
      <div className="gnode-sub" style={{ WebkitLineClamp: 3 }}>{data.text}</div>
    </Shell>
  )
}

export function CitationNode({ data }) {
  return (
    <Shell kind="citation">
      <div className="gnode-head">
        <b className="mono">{data.label}</b>
        <span style={{ marginLeft: 'auto' }}><Stamp value={data.support} /></span>
      </div>
      {data.quote && <div className="gnode-sub quote">“{(data.quote || '').slice(0, 90)}…”</div>}
    </Shell>
  )
}

export function PaperNode({ data }) {
  return (
    <Shell kind="paper">
      <div className="gnode-head">
        <span className="gnode-kind">paper</span>
        <b className="mono">{data.label}</b>
      </div>
    </Shell>
  )
}

export function CodeNode({ data }) {
  return (
    <Shell kind="code">
      <div className="gnode-head">
        <span className="gnode-kind">code</span>
        <b className="mono" style={{ fontSize: 11 }}>{data.label}</b>
      </div>
      {data.text && <div className="gnode-sub">{data.text}</div>}
    </Shell>
  )
}

// Thinking nodes: questions (open/answered), hypotheses, advisor feedback,
// answers — the reasoning that surrounds experiments, visible on the canvas.
function ThoughtNode(kind) {
  return function Thought({ data }) {
    return (
      <Shell kind={kind}>
        <div className="gnode-head">
          <span className="gnode-kind">{data.type || kind}</span>
          {kind === 'question' && (
            <span style={{ marginLeft: 'auto' }}>
              <Stamp value={data.answered ? 'answered' : 'open'} tone={data.answered ? 'ok' : 'warn'} />
            </span>
          )}
        </div>
        {data.source && <div className="gnode-kind" style={{ marginTop: 2 }}>{data.source}</div>}
        <div className="gnode-sub" style={{ WebkitLineClamp: 4 }}>{data.text}</div>
      </Shell>
    )
  }
}

export const nodeTypes = {
  experiment: ExperimentNode,
  finding: FindingNode,
  claim: ClaimNode,
  citation: CitationNode,
  paper: PaperNode,
  code: CodeNode,
  question: ThoughtNode('question'),
  hypothesis: ThoughtNode('hypothesis'),
  feedback: ThoughtNode('feedback'),
  thought: ThoughtNode('thought'),
  note: ThoughtNode('note'),
}
