// The plan: phases and milestones on a time axis (Gantt). Plans are intent,
// not evidence — items are freely editable/deletable, unlike the ledger.
// The activity overlay projects the existing log onto the same axis so you
// can see when what kind of progress actually happened.
import React, { useEffect, useMemo, useState } from 'react'
import { getPlan, addPlanItem, updatePlanItem, deletePlanItem, getProject } from '../api.js'
import { Stamp, Section, Empty, timeAgo } from '../ui.jsx'

const DAY = 86400000
const PX = 26                                   // px per day
const parse = (s) => new Date(s + 'T00:00:00Z')
const iso = (d) => d.toISOString().slice(0, 10)
const addDays = (d, n) => new Date(d.getTime() + n * DAY)

const TONE_COLOR = {
  done: 'var(--ok)', overdue: 'var(--bad)', active: 'var(--accent)', future: 'var(--line-strong)',
}

function itemState(it, today) {
  if (it.status === 'done') return 'done'
  if (it.due < today) return 'overdue'
  if (it.kind === 'milestone') return it.due === today ? 'active' : 'future'
  if (it.start && it.start > today) return 'future'
  return 'active'
}

export default function Plan({ slug }) {
  const [items, setItems] = useState(null)
  const [activity, setActivity] = useState(null)   // {date: [types]}
  const [showActivity, setShowActivity] = useState(true)
  const [draft, setDraft] = useState(null)         // new-item form
  const [sel, setSel] = useState(null)             // item being edited
  const [err, setErr] = useState(null)

  const today = iso(new Date())

  const load = () => getPlan(slug).then(setItems)
  useEffect(() => {
    setItems(null); setSel(null); setErr(null)
    load()
    getProject(slug).then((d) => {
      const by = {}
      for (const e of [...(d.log || []), ...(d.notes || []).map((n) => ({ ...n, type: 'note' }))]) {
        const day = (e.ts || '').slice(0, 10)
        if (day) (by[day] = by[day] || []).push(e.type)
      }
      setActivity(by)
    })
  }, [slug])

  const range = useMemo(() => {
    const dates = [today]
    for (const it of items || []) {
      if (it.start) dates.push(it.start)
      dates.push(it.due)
    }
    for (const d of Object.keys(activity || {})) dates.push(d)
    dates.sort()
    let min = addDays(parse(dates[0]), -3)
    let max = addDays(parse(dates[dates.length - 1]), 10)
    if ((max - min) / DAY < 28) max = addDays(min, 28)
    return { min, max, days: Math.round((max - min) / DAY) }
  }, [items, activity, today])

  if (!items) return <div className="loading">reading the plan…</div>

  const x = (dateStr) => ((parse(dateStr) - range.min) / DAY) * PX
  const width = range.days * PX

  // month labels across the axis
  const months = []
  for (let d = new Date(range.min); d < range.max; d = addDays(d, 1)) {
    if (d.getUTCDate() === 1 || +d === +range.min) {
      months.push({ left: ((d - range.min) / DAY) * PX,
                    label: d.toLocaleDateString('en', { month: 'short', year: 'numeric', timeZone: 'UTC' }) })
    }
  }

  const save = async () => {
    setErr(null)
    const r = draft.id
      ? await updatePlanItem(draft.id, { title: draft.title, start: draft.kind === 'phase' ? draft.start || null : null, due: draft.due, note: draft.note })
      : await addPlanItem(slug, { title: draft.title, kind: draft.kind, start: draft.kind === 'phase' ? draft.start || undefined : undefined, due: draft.due, note: draft.note })
    if (r && r.error) { setErr(r.error); return }
    setDraft(null)
    load()
  }

  const form = draft && (
    <div className="detail" style={{ display: 'grid', gap: 8, borderTop: draft?.id ? '1px solid var(--line)' : undefined }}>
      <div style={{ display: 'flex', gap: 6 }}>
        {['phase', 'milestone'].map((k) => (
          <button key={k} className="btn ghost"
                  style={{ textTransform: 'capitalize', ...(draft.kind === k ? { color: 'var(--accent)', borderColor: 'var(--accent)' } : {}) }}
                  disabled={!!draft.id}
                  onClick={() => setDraft({ ...draft, kind: k })}>{k}</button>
        ))}
      </div>
      <input className="text" placeholder="title, e.g. NeurIPS abstract deadline / Dimension-sweep experiments"
             value={draft.title || ''} autoFocus
             onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
      <div style={{ display: 'grid', gridTemplateColumns: draft.kind === 'phase' ? '1fr 1fr' : '1fr', gap: 8 }}>
        {draft.kind === 'phase' && (
          <label className="muted" style={{ fontSize: 11.5 }}>start
            <input className="text" type="date" value={draft.start || ''}
                   onChange={(e) => setDraft({ ...draft, start: e.target.value })} />
          </label>
        )}
        <label className="muted" style={{ fontSize: 11.5 }}>{draft.kind === 'phase' ? 'due' : 'date'}
          <input className="text" type="date" value={draft.due || ''}
                 onChange={(e) => setDraft({ ...draft, due: e.target.value })} />
        </label>
      </div>
      <input className="text" placeholder="note (optional)" value={draft.note || ''}
             onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
      {err && <div style={{ color: 'var(--bad)', fontSize: 12 }}>{err}</div>}
      <div className="gnode-actions" style={{ marginTop: 0 }}>
        <button className="btn" onClick={save} disabled={!(draft.title || '').trim() || !draft.due}>
          {draft.id ? 'Save changes' : 'Add to plan'}
        </button>
        {draft.id && (
          <button className="btn ghost" onClick={async () => {
            const it = items.find((i) => i.id === draft.id)
            await updatePlanItem(draft.id, { status: it.status === 'done' ? 'planned' : 'done' })
            setDraft(null); load()
          }}>{items.find((i) => i.id === draft.id)?.status === 'done' ? 'Reopen' : 'Mark done'}</button>
        )}
        {draft.id && (
          <button className="btn danger" onClick={async () => { await deletePlanItem(draft.id); setDraft(null); load() }}>
            Delete
          </button>
        )}
        <button className="btn ghost" onClick={() => setDraft(null)}>Cancel</button>
      </div>
    </div>
  )

  return (
    <>
      <div className="pagehead">
        <h1>Timeline</h1>
        <div className="sub">what should be done until when — deadlines, submission phases, work blocks</div>
      </div>

      <Section
        title="Plan"
        aside={
          <span>
            <button className="rowbtn" style={{ display: 'inline', width: 'auto', cursor: 'pointer',
                                                color: showActivity ? 'var(--accent)' : 'inherit' }}
                    onClick={() => setShowActivity(!showActivity)}>
              activity overlay
            </button>
            <button className="rowbtn" style={{ display: 'inline', width: 'auto', marginLeft: 12,
                                                color: 'var(--accent)', cursor: 'pointer' }}
                    onClick={() => { setSel(null); setDraft({ kind: 'phase' }) }}>
              + add item
            </button>
          </span>
        }
      >
        {items.length === 0 && !draft && (
          <Empty>No plan yet — add a deadline or a phase, e.g. a conference submission window.</Empty>
        )}
        {items.length > 0 && (
          <div className="gantt">
            <div className="gantt-labels">
              <div className="gantt-head" />
              {items.map((it) => (
                <button key={it.id} className="gantt-label rowbtn" onClick={() => setDraft({ ...it })}>
                  <span className="gantt-swatch" style={{ background: TONE_COLOR[itemState(it, today)] }} />
                  <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {it.title}
                  </span>
                  {it.status === 'done' && <Stamp value="done" />}
                </button>
              ))}
              {showActivity && activity && <div className="gantt-label muted" style={{ cursor: 'default' }}>activity</div>}
            </div>

            <div className="gantt-chart">
              <div style={{ width, position: 'relative' }}>
                <div className="gantt-head" style={{ width }}>
                  {months.map((m, i) => (
                    <span key={i} className="gantt-month" style={{ left: m.left }}>{m.label}</span>
                  ))}
                </div>
                <div className="gantt-body"
                     style={{ width, backgroundSize: `${PX * 7}px 100%` }}>
                  <div className="gantt-today" style={{ left: x(today) + PX / 2 }} title={`today · ${today}`} />
                  {items.map((it) => {
                    const state = itemState(it, today)
                    return (
                      <div key={it.id} className="gantt-row">
                        {it.kind === 'phase' ? (
                          <button
                            className={`gantt-bar bar-${state}`}
                            style={{ left: x(it.start || it.due), width: Math.max(x(it.due) - x(it.start || it.due) + PX, PX) }}
                            title={`${it.title}\n${it.start || it.due} → ${it.due}${it.note ? '\n' + it.note : ''}`}
                            onClick={() => setDraft({ ...it })}
                          />
                        ) : (
                          <button
                            className={`gantt-ms bar-${state}`}
                            style={{ left: x(it.due) + PX / 2 - 6 }}
                            title={`${it.title}\n${it.due}${it.note ? '\n' + it.note : ''}`}
                            onClick={() => setDraft({ ...it })}
                          />
                        )}
                      </div>
                    )
                  })}
                  {showActivity && activity && (
                    <div className="gantt-row">
                      {Object.entries(activity).map(([day, types]) => (
                        <span key={day} className="gantt-dot"
                              style={{ left: x(day) + PX / 2 - 3.5,
                                       width: Math.min(7 + (types.length - 1) * 2, 13),
                                       height: Math.min(7 + (types.length - 1) * 2, 13) }}
                              title={`${day}\n${types.join(', ')}`} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
        {draft && form}
      </Section>

      <div style={{ height: 14 }} />

      <Section title="Items" aside={`${items.filter((i) => i.status !== 'done').length} open`}>
        {items.map((it) => (
          <button key={it.id} className="rowbtn" onClick={() => setDraft({ ...it })}>
            <div className="row">
              <span className="gantt-swatch" style={{ background: TONE_COLOR[itemState(it, today)] }} />
              <span className="chip">{it.kind}</span>
              <div className="grow">{it.title}{it.note && <span className="muted"> — {it.note}</span>}</div>
              <span className="num faint">{it.start ? `${it.start} → ${it.due}` : it.due}</span>
              {it.edited && <span className="when" title="last edited">✎ {timeAgo(it.edited)}</span>}
            </div>
          </button>
        ))}
        {!items.length && <Empty>Nothing planned yet.</Empty>}
      </Section>
    </>
  )
}
