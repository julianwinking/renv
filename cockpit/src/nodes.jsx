import React, { useState } from 'react'
import { Handle, Position, NodeResizer } from '@xyflow/react'
import { adjudicate, updateRegion, deleteRegion } from './api.js'
import { Stamp, Metrics } from './ui.jsx'

export const REGION_COLORS = ['slate', 'teal', 'violet', 'amber', 'rose', 'blue']

// A labeled frame for grouping the canvas by phase/field. Drag it by the
// label bar (the rest is click-through so nodes on top stay usable); resize
// with the handles; rename inline; recolor; delete.
export function RegionNode({ id, data }) {
  const rid = Number(id.split(':')[1])
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(data.label || '')
  const [menu, setMenu] = useState(false)
  const [hover, setHover] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)

  const saveLabel = () => {
    setEditing(false)
    if (label !== data.label) { updateRegion(rid, { label }); data.onChange?.() }
  }
  const setColor = (c) => { setMenu(false); updateRegion(rid, { color: c }).then(() => data.onChange?.()) }
  const remove = () => deleteRegion(rid).then(() => data.onChange?.())

  return (
    <div className={`region region-${data.color || 'slate'}${hover ? ' hl' : ''}`}>
      <NodeResizer minWidth={140} minHeight={90} color="var(--line-strong)"
                   onResizeEnd={(_, p) => { updateRegion(rid, { x: p.x, y: p.y, w: p.width, h: p.height }); data.onChange?.() }} />
      {/* name + color + delete grouped top-right, mirroring the phase labels */}
      <div className="region-bar">
        {(data.phaseNames || []).length > 0 && (
          <span className="region-phase" title="Phases this region overlaps (derived from its surface — drag the region or the bands to change)">
            ⟡ {data.phaseNames.join(' · ')}
          </span>
        )}
        {editing ? (
          <input className="region-input nodrag" autoFocus value={label}
                 onChange={(e) => setLabel(e.target.value)} onBlur={saveLabel}
                 onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') { setLabel(data.label || ''); setEditing(false) } }} />
        ) : (
          <span className="region-name" title="Click to rename"
                onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
                onClick={(e) => { e.stopPropagation(); setLabel(data.label || ''); setEditing(true) }}>
            {data.label || 'Untitled region'}
          </span>
        )}
        <button className="region-btn nodrag" title="Color"
                onClick={() => setMenu(!menu)}>◑</button>
        {confirmDel ? (
          <button className="region-btn region-del-sure nodrag" title="Really delete this region"
                  onClick={remove} onMouseLeave={() => setConfirmDel(false)}>sure?</button>
        ) : (
          <button className="region-btn nodrag" title="Delete region"
                  onClick={() => setConfirmDel(true)}>✕</button>
        )}
        {menu && (
          <div className="region-menu nodrag">
            {REGION_COLORS.map((c) => (
              <button key={c} className={`region-swatch region-${c}`} title={c} onClick={() => setColor(c)} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Shell({ kind, children }) {
  return (
    <div className={`gnode gnode-${kind}`}>
      <Handle type="target" position={Position.Left} />
      {children}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

// Click a node's text to rename it inline (single click, no layout jump).
// Falls back to a plain span when the node kind has no editor.
function EditableText({ value, onSave, className, style, clamp = 3, placeholder }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(value)
  const shown = value || (placeholder ? <span className="faint">{placeholder}</span> : value)
  if (!onSave) return <div className={className} style={{ ...style, WebkitLineClamp: clamp }}>{shown}</div>
  if (editing) {
    return (
      <textarea
        className={`nodrag gnode-edit ${className}`} autoFocus value={text}
        style={style}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => { setEditing(false); if (text.trim() && text !== value) onSave(text.trim()) }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.target.blur() }
          if (e.key === 'Escape') { setText(value); setEditing(false) }
        }}
      />
    )
  }
  return (
    <div className={className} title="Click to edit"
         style={{ ...style, WebkitLineClamp: clamp, cursor: 'text' }}
         onClick={(e) => { e.stopPropagation(); setText(value); setEditing(true) }}>
      {shown}
    </div>
  )
}

// Experiment: status stamp + formatted metrics; click to reveal the hypothesis.
export function ExperimentNode({ data }) {
  const [open, setOpen] = useState(false)
  const [editingSlug, setEditingSlug] = useState(false)
  const [slug, setSlug] = useState(data.label)
  const saveSlug = () => {
    setEditingSlug(false)
    if (slug.trim() && slug !== data.label) data.onSaveSlug?.(slug.trim())
  }
  return (
    <Shell kind="experiment">
      <div className="gnode-head">
        {editingSlug ? (
          <input className="nodrag gnode-slug-edit mono" autoFocus value={slug}
                 size={Math.max(slug.length, 4)}
                 onChange={(e) => setSlug(e.target.value)} onBlur={saveSlug}
                 onKeyDown={(e) => {
                   if (e.key === 'Enter') { e.preventDefault(); e.target.blur() }
                   if (e.key === 'Escape') { setSlug(data.label); setEditingSlug(false) }
                 }} />
        ) : (
          <b className="mono" title="Click to rename" style={{ cursor: 'text' }}
             onClick={(e) => { e.stopPropagation(); setSlug(data.label); setEditingSlug(true) }}>
            {data.label}
          </b>
        )}
        <span style={{ marginLeft: 'auto', cursor: 'pointer' }}
              onClick={(e) => { e.stopPropagation(); setOpen(!open) }}>
          <Stamp value={data.status} />
        </span>
      </div>
      <EditableText className="gnode-sub" value={data.title} onSave={data.onSaveText} clamp={2} />
      <Metrics defs={data.defs} metrics={data.metrics} />
      {open && (
        <div className="gnode-sub" style={{ marginTop: 6 }}>
          <span className="gnode-kind">hypothesis · </span>
          <EditableText className="gnode-sub" style={{ display: 'inline' }} clamp={8}
                        value={data.hypothesis || ''} placeholder="click to add"
                        onSave={data.onSaveHyp} />
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
          <button className="btn ghost" onClick={() => setVerdict('accept')}>Accept</button>
          <button className="btn ghost" onClick={() => setVerdict('reject')}>Reject</button>
        </div>
      )}
      {verdict && (
        <>
          <textarea
            className="nodrag"
            placeholder={`Why ${verdict}?`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="gnode-actions">
            <button className="btn" onClick={submit}>Save</button>
            <button className="btn ghost" onClick={() => setVerdict(null)}>Cancel</button>
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
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          {data.onPromote && (
            <button className="gnode-promote nodrag" title="Spawn the experiment that will test this (pre-registered)"
                    onClick={(e) => { e.stopPropagation(); data.onPromote() }}>⚗</button>
          )}
          <Stamp value={data.status} />
        </span>
      </div>
      <EditableText className="gnode-sub" value={data.text} onSave={data.onSaveText} clamp={3} />
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
      {(data.title || data.onSaveText) && (
        <EditableText className="gnode-sub" value={data.title} onSave={data.onSaveText}
                      placeholder="(no title — click to add)" clamp={2} />
      )}
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

// A positional paper note: the reader's marginalia on a paper, anchored to a
// quoted span. Coloured by the note's colour; the quote grounds it, the body
// is editable inline. From here it can motivate an experiment or argue a claim.
export function PaperNoteNode({ data }) {
  return (
    <div className={`gnode gnode-pnote pv-c-${data.color || 'amber'}`}>
      <Handle type="target" position={Position.Left} />
      <div className="gnode-head">
        <span className="gnode-kind">{((data.note_kind || 'note') === 'note' ? 'annotation' : data.note_kind)} · {data.paper_key}</span>
        {data.page && <span className="gnode-kind" style={{ marginLeft: 'auto' }}>p{data.page}</span>}
      </div>
      {data.quote && <div className="gnode-sub quote">“{(data.quote || '').slice(0, 80)}{(data.quote || '').length > 80 ? '…' : ''}”</div>}
      <EditableText className="gnode-sub" value={data.text} placeholder="(no note text)"
                    onSave={data.onSaveText} clamp={3} />
      <Handle type="source" position={Position.Right} />
    </div>
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
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
            {data.onPromote && (
              <button className="gnode-promote nodrag" title="Spawn the experiment this motivates"
                      onClick={(e) => { e.stopPropagation(); data.onPromote() }}>⚗</button>
            )}
            {kind === 'question' && (
              <Stamp value={data.answered ? 'answered' : 'open'} tone={data.answered ? 'ok' : 'warn'} />
            )}
          </span>
        </div>
        {data.source && <div className="gnode-kind" style={{ marginTop: 2 }}>{data.source}</div>}
        <EditableText className="gnode-sub" value={data.text} onSave={data.onSaveText} clamp={4} />
      </Shell>
    )
  }
}

export const nodeTypes = {
  region: RegionNode,
  experiment: ExperimentNode,
  finding: FindingNode,
  claim: ClaimNode,
  citation: CitationNode,
  paper: PaperNode,
  pnote: PaperNoteNode,
  code: CodeNode,
  question: ThoughtNode('question'),
  hypothesis: ThoughtNode('hypothesis'),
  feedback: ThoughtNode('feedback'),
  decision: ThoughtNode('decision'),
  blocker: ThoughtNode('blocker'),
  observation: ThoughtNode('observation'),
  thought: ThoughtNode('thought'),
  note: ThoughtNode('note'),
}
