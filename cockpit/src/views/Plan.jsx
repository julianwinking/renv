// The plan: phases and milestones on a time axis (Gantt). Plans are intent,
// not evidence — items are freely editable/deletable, unlike the ledger.
// The activity overlay projects the existing log onto the same axis so you
// can see when what kind of progress actually happened.
import React, { useEffect, useMemo, useState } from 'react'
import { getPlan, addPlanItem, updatePlanItem, deletePlanItem, getProject } from '../api.js'
import { asArray, Stamp, Confirm } from '../ui.jsx'

const DAY = 86400000
const ZOOMS = [10, 18, 26, 42, 64]              // px per day
const parse = (s) => new Date(s + 'T00:00:00Z')
const iso = (d) => d.toISOString().slice(0, 10)
const addDays = (d, n) => new Date(d.getTime() + n * DAY)

const TONE_COLOR = {
  done: 'var(--ok)', overdue: 'var(--bad)', active: 'var(--accent)', future: 'var(--line-strong)',
}
// activity lane: one color per entry type, stacked by share
const TYPE_COLOR = {
  decision: 'var(--accent)', hypothesis: 'var(--citation)', observation: 'var(--muted)',
  result: 'var(--ok)', blocker: 'var(--bad)', question: 'var(--warn-dot)',
  feedback: 'var(--code-kind)', note: 'var(--paper-kind)',
}

function itemState(it, today) {
  if (it.status === 'done') return 'done'
  if (it.due < today) return 'overdue'
  if (it.kind !== 'phase') return it.due === today ? 'active' : 'future'
  if (it.start && it.start > today) return 'future'
  return 'active'
}

export default function Plan({ slug }) {
  const [items, setItems] = useState(null)
  const [activity, setActivity] = useState(null)   // {date: [types]}
  const [draft, setDraft] = useState(null)         // new-item form
  const [sel, setSel] = useState(null)             // item being edited
  const [err, setErr] = useState(null)
  const [zoom, setZoom] = useState(2)              // index into ZOOMS
  const PX = ZOOMS[zoom]
  const [labelW, setLabelW] = useState(() =>
    Number(localStorage.getItem('reref-gantt-labels')) || 230)

  const startLabelResize = (e) => {
    e.preventDefault()
    const x0 = e.clientX
    const w0 = labelW
    let w = w0
    const move = (ev) => { w = Math.min(420, Math.max(140, w0 + ev.clientX - x0)); setLabelW(w) }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      localStorage.setItem('reref-gantt-labels', String(w))
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }
  const chartRef = React.useRef(null)
  const zoomRef = React.useRef(zoom)
  zoomRef.current = zoom
  const [chartW, setChartW] = useState(1200)

  useEffect(() => {   // grid must always fill the visible width, at any zoom
    const el = chartRef.current
    if (!el) return
    const measure = () => setChartW(el.clientWidth)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [items === null])

  // trackpad pinch (arrives as ctrl+wheel) zooms, anchored on the cursor date
  useEffect(() => {
    const el = chartRef.current
    if (!el) return
    let acc = 0
    const onWheel = (e) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      acc += e.deltaY
      if (Math.abs(acc) < 20) return
      const dir = acc > 0 ? -1 : 1
      acc = 0
      const z = zoomRef.current
      const nz = Math.min(ZOOMS.length - 1, Math.max(0, z + dir))
      if (nz === z) return
      const rect = el.getBoundingClientRect()
      const cx = e.clientX - rect.left
      const days = (el.scrollLeft + cx) / ZOOMS[z]
      setZoom(nz)
      requestAnimationFrame(() => { el.scrollLeft = days * ZOOMS[nz] - cx })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [items === null])
  const [preview, setPreview] = useState(null)     // live dates while dragging
  const [confirm, setConfirm] = useState(null)     // pending deadline move
  const justDragged = React.useRef(false)

  const shiftDate = (s, days) => iso(addDays(parse(s), days))

  // drag a bar edge ('start' | 'due') or a whole single-date item ('move')
  const beginDrag = (e, it, mode) => {
    e.preventDefault()
    e.stopPropagation()
    const x0 = e.clientX
    const dates = (delta) => {
      let start = it.start, due = it.due
      if (mode === 'start') {
        const s = shiftDate(it.start, delta)
        start = s > due ? due : s                        // never past the end
      } else if (mode === 'due') {
        const d2 = shiftDate(it.due, delta)
        due = it.start && d2 < it.start ? it.start : d2  // never before the start
      } else {
        due = shiftDate(it.due, delta)
        if (it.start) start = shiftDate(it.start, delta)
      }
      return { start, due }
    }
    const onMove = (ev) => {
      const delta = Math.round((ev.clientX - x0) / PX)
      setPreview({ id: it.id, ...dates(delta) })
    }
    const onUp = (ev) => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      setPreview(null)
      const delta = Math.round((ev.clientX - x0) / PX)
      if (!delta) return
      justDragged.current = true
      setTimeout(() => { justDragged.current = false }, 50)
      const d = dates(delta)
      const fields = mode === 'start' ? { start: d.start }
        : mode === 'due' ? { due: d.due } : { start: d.start, due: d.due }
      const apply = async () => { await updatePlanItem(it.id, fields); load() }
      const movesDeadline = (it.kind === 'deadline' || it.end_deadline) && d.due !== it.due
      if (movesDeadline) {
        setConfirm({
          title: 'Move deadline?',
          body: <>“{it.title}” moves from <b className="mono">{it.due}</b> to <b className="mono">{d.due}</b>.</>,
          onConfirm: () => { setConfirm(null); apply() },
        })
      } else {
        apply()
      }
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const today = iso(new Date())

  const load = () => getPlan(slug).then((i) => setItems(asArray(i)))
  useEffect(() => {
    setItems(null); setSel(null); setErr(null)
    load()
    getProject(slug).then((d) => {
      const by = {}
      for (const e of [...(d.log || []), ...(d.notes || []).map((n) => ({ ...n, type: 'note' }))]) {
        const day = (e.ts || '').slice(0, 10)
        if (!day) continue
        by[day] = by[day] || {}
        by[day][e.type] = (by[day][e.type] || 0) + 1
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
    // dates continue to the right page edge even when zoomed far out
    const minDays = Math.ceil(chartW / PX) + 1
    if ((max - min) / DAY < minDays) max = addDays(min, minDays)
    return { min, max, days: Math.round((max - min) / DAY) }
  }, [items, activity, today, chartW, PX])

  if (!items) return <div className="loading">reading the plan…</div>

  const x = (dateStr) => ((parse(dateStr) - range.min) / DAY) * PX
  const width = range.days * PX

  // axis: months always; finer ticks appear as the zoom deepens
  const months = []
  const ticks = []
  for (let d = new Date(range.min); d < range.max; d = addDays(d, 1)) {
    const left = ((d - range.min) / DAY) * PX
    if (d.getUTCDate() === 1 || +d === +range.min) {
      months.push({ left, label: d.toLocaleDateString('en', { month: 'short', year: 'numeric', timeZone: 'UTC' }) })
    }
    const dow = d.getUTCDay()
    if (PX >= 42) {                                  // daily numbers, weekends faint
      ticks.push({ left, label: String(d.getUTCDate()), faint: dow === 0 || dow === 6 })
    } else if (PX >= 18 && dow === 1) {              // Mondays with the date
      ticks.push({ left, label: `${d.getUTCDate()}.${d.getUTCMonth() + 1}`, faint: false })
    }
  }

  const save = async () => {
    setErr(null)
    const extras = {
      prepared: draft.kind === 'deadline' || (draft.kind === 'phase' && draft.end_deadline)
        ? (draft.prepared ? 1 : 0) : 0,
      end_deadline: draft.kind === 'phase' && draft.end_deadline ? 1 : 0,
    }
    const r = draft.id
      ? await updatePlanItem(draft.id, { title: draft.title, start: draft.kind === 'phase' ? draft.start || null : null, due: draft.due, note: draft.note, ...extras })
      : await addPlanItem(slug, { title: draft.title, kind: draft.kind, start: draft.kind === 'phase' ? draft.start || undefined : undefined, due: draft.due, note: draft.note, ...extras })
    if (r && r.error) { setErr(r.error); return }
    setDraft(null)
    load()
  }

  const form = draft && (
    <div className="detail" style={{ display: 'grid', gap: 8, borderTop: draft?.id ? '1px solid var(--line)' : undefined }}>
      <div style={{ display: 'flex', gap: 6 }}>
        {['phase', 'milestone', 'deadline'].map((k) => (
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
      {draft.kind === 'phase' && (
        <label className="muted" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 7 }}>
          <input type="checkbox" checked={!!draft.end_deadline}
                 onChange={(e) => setDraft({ ...draft, end_deadline: e.target.checked })} />
          this phase ends in a deadline
        </label>
      )}
      {(draft.kind === 'deadline' || (draft.kind === 'phase' && draft.end_deadline)) && (
        <label className="muted" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 7 }}>
          <input type="checkbox" checked={!!draft.prepared}
                 onChange={(e) => setDraft({ ...draft, prepared: e.target.checked })} />
          already prepared for it
        </label>
      )}
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
      <div className="pagehead" style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
        <h1>Timeline</h1>
        <span className="gantt-tools">
          <button className="gtool sq" disabled={zoom === 0}
                  onClick={() => setZoom(Math.max(0, zoom - 1))} title="Zoom out">−</button>
          <button className="gtool sq" disabled={zoom === ZOOMS.length - 1}
                  onClick={() => setZoom(Math.min(ZOOMS.length - 1, zoom + 1))} title="Zoom in">+</button>
        </span>
      </div>

      {items.length === 0 && !draft && (
        <div className="muted" style={{ padding: '30px 2px' }}>
          No plan yet — add a deadline or a phase, e.g. a conference submission window.
        </div>
      )}
      {items.length > 0 && (
          <div className="gantt gantt-page">
            <div className="gantt-labels" style={{ width: labelW }}>
              <div className="side-resize" onMouseDown={startLabelResize} title="Drag to resize" />
              <div className="gantt-head" />
              {items.map((it) => (
                <button key={it.id} className="gantt-label rowbtn" onClick={() => setDraft({ ...it })}>
                  <span className="gantt-swatch" style={{ background: TONE_COLOR[itemState(it, today)] }} />
                  <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {it.title}
                  </span>
                  {it.status === 'done' ? <Stamp value="done" />
                    : (it.kind === 'deadline' || it.end_deadline)
                      ? <Stamp value={it.prepared ? 'prepared' : 'unprepared'} tone={it.prepared ? 'ok' : 'warn'} />
                      : null}
                </button>
              ))}
              {activity && <div className="gantt-label tall muted" style={{ cursor: 'default' }}>Activity</div>}
              <button className="gantt-label add rowbtn"
                      onClick={() => { setSel(null); setDraft({ kind: 'phase' }) }}>
                + Add item
              </button>
            </div>

            <div className="gantt-chart" ref={chartRef}>
              <div style={{ width, position: 'relative' }}>
                <div className="gantt-head" style={{ width }}>
                  {months.map((m, i) => (
                    <span key={i} className="gantt-month" style={{ left: m.left }}>{m.label}</span>
                  ))}
                  {ticks.map((t, i) => (
                    <span key={`t${i}`} className={`gantt-tick ${t.faint ? 'faint' : ''}`}
                          style={{ left: t.left }}>{t.label}</span>
                  ))}
                </div>
                <div className="gantt-body"
                     style={{ width, backgroundSize: `${PX >= 42 ? PX : PX * 7}px 100%` }}>
                  <div className="gantt-today" style={{ left: x(today) + PX / 2 }} title={`today · ${today}`} />
                  {items.map((it) => {
                    const state = itemState(it, today)
                    const dl = it.kind === 'deadline' || it.end_deadline
                    const prep = dl ? (it.prepared ? '\nprepared ✓' : '\nNOT prepared') : ''
                    // live-preview dates while dragging
                    const disp = preview && preview.id === it.id
                      ? { ...it, start: preview.start, due: preview.due } : it
                    const open = () => { if (!justDragged.current) setDraft({ ...it }) }
                    return (
                      <div key={it.id} className="gantt-row">
                        {it.kind === 'phase' && (
                          <div
                            role="button" tabIndex={0}
                            className={`gantt-bar bar-${state}`}
                            style={{ left: x(disp.start || disp.due), width: Math.max(x(disp.due) - x(disp.start || disp.due) + PX, PX) }}
                            title={`${it.title}\n${disp.start || disp.due} → ${disp.due}${prep}${it.note ? '\n' + it.note : ''}`}
                            onClick={open}
                            onKeyDown={(e) => e.key === 'Enter' && open()}
                          >
                            <span className="gantt-handle left" title="drag to move the start"
                                  onMouseDown={(e) => beginDrag(e, it, 'start')} />
                            <span className="gantt-handle right" title="drag to move the end"
                                  onMouseDown={(e) => beginDrag(e, it, 'due')} />
                          </div>
                        )}
                        {(it.kind !== 'phase' || !!it.end_deadline) && (
                          <button
                            className={`gantt-ms bar-${state} ${dl && !it.prepared && it.status !== 'done' ? 'ms-unprepared' : ''}`}
                            style={{ left: x(disp.due) + PX / 2 - 6 }}
                            title={`${it.title}\n${disp.due}${prep}${it.note ? '\n' + it.note : ''}\n(drag to move)`}
                            onMouseDown={(e) => beginDrag(e, it, it.kind === 'phase' ? 'due' : 'move')}
                            onClick={open}
                          />
                        )}
                      </div>
                    )
                  })}
                  {activity && (
                    <div className="gantt-row tall">
                      {Object.entries(activity).map(([day, counts]) => {
                        const total = Object.values(counts).reduce((a, b) => a + b, 0)
                        const barH = Math.min(10 + total * 5, 60)
                        const tip = `${day}\n` + Object.entries(counts)
                          .map(([t, n]) => `${n}× ${t}`).join(', ')
                        let acc = 0
                        return (
                          <span key={day} className="gantt-stack"
                                style={{ left: x(day) + PX / 2 - Math.min(PX - 2, 10) / 2,
                                         width: Math.min(PX - 2, 10), height: barH }}
                                title={tip}>
                            {Object.entries(counts).map(([t, n]) => {
                              const h = Math.max((n / total) * barH, 2)
                              const seg = (
                                <span key={t} style={{ position: 'absolute', bottom: acc, left: 0, right: 0,
                                                       height: h, background: TYPE_COLOR[t] || 'var(--citation)' }} />
                              )
                              acc += h
                              return seg
                            })}
                          </span>
                        )
                      })}
                    </div>
                  )}
                  <div className="gantt-row add" role="button" tabIndex={0}
                       title="Add a phase, milestone, or deadline"
                       onClick={() => { setSel(null); setDraft({ kind: 'phase' }) }}
                       onKeyDown={(e) => e.key === 'Enter' && setDraft({ kind: 'phase' })} />
                </div>
              </div>
            </div>
          </div>
      )}
      {draft && <div className="card" style={{ marginTop: 14 }}>{form}</div>}
      <Confirm open={!!confirm} title={confirm?.title} body={confirm?.body}
               confirmLabel="Move deadline" onConfirm={confirm?.onConfirm}
               onCancel={() => setConfirm(null)} />
    </>
  )
}
