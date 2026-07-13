// Tools → Conferences: the ai-deadlines feed (cached server-side, works
// offline). Telescope data — a deadline only becomes research state when you
// adopt it into the plan, which creates a normal plan_item deadline.
import React, { useEffect, useMemo, useState } from 'react'
import { getConferences, addPlanItem } from '../api.js'
import { asArray, Stamp, Section, Empty, Mono } from '../ui.jsx'

const DEFAULT_SUBS = ['ML', 'CV', 'RO']
const SUB_LABEL = {
  ML: 'machine learning', CV: 'computer vision', RO: 'robotics', NLP: 'NLP',
  SP: 'speech', DM: 'data mining', AP: 'applied', KR: 'knowledge repr.',
  HCI: 'HCI', CG: 'graphics',
}

function daysLeft(deadline) {
  const d = new Date((deadline || '').replace(' ', 'T'))
  if (Number.isNaN(+d)) return null
  return Math.ceil((d - Date.now()) / 86400000)
}

export default function Conferences({ slug }) {
  const [all, setAll] = useState(null)
  const [err, setErr] = useState(null)
  const [subs, setSubs] = useState(() => {
    try { return JSON.parse(localStorage.getItem('reref-conf-subs')) || DEFAULT_SUBS }
    catch { return DEFAULT_SUBS }
  })
  const [added, setAdded] = useState({})   // conference id → plan item created

  useEffect(() => {
    getConferences().then((c) => {
      if (c && c.error) setErr(c.error)
      else setAll(asArray(c))
    })
  }, [])

  useEffect(() => { localStorage.setItem('reref-conf-subs', JSON.stringify(subs)) }, [subs])

  const allSubs = useMemo(() => {
    const s = new Set()
    for (const c of all || []) asArray(c.sub).forEach((x) => s.add(x))
    return [...s].sort()
  }, [all])

  const upcoming = useMemo(() => {
    return (all || [])
      .filter((c) => asArray(c.sub).some((s) => subs.includes(s)))
      .map((c) => ({ ...c, left: daysLeft(c.deadline) }))
      .filter((c) => c.left !== null && c.left >= 0)
      .sort((a, b) => a.left - b.left)
  }, [all, subs])

  const adopt = async (c) => {
    const due = (c.deadline || '').slice(0, 10)
    const r = await addPlanItem(slug, {
      title: `${c.title} ${c.year} deadline`, kind: 'deadline', due,
      note: c.link,
    })
    if (!r.error) setAdded((a) => ({ ...a, [c.id]: true }))
  }

  if (err) {
    return (
      <>
        <div className="pagehead"><h1>Conferences</h1></div>
        <Section title="Deadlines"><Empty>{err}</Empty></Section>
      </>
    )
  }
  if (!all) return <div className="loading">fetching deadlines…</div>

  return (
    <>
      <div className="pagehead">
        <h1>Conferences</h1>
      </div>

      <Section title="Categories">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '4px 16px 12px' }}>
          {allSubs.map((s) => (
            <button key={s}
                    className="btn ghost"
                    style={subs.includes(s) ? { color: 'var(--accent)', borderColor: 'var(--accent)' } : null}
                    title={SUB_LABEL[s] || s}
                    onClick={() => setSubs(subs.includes(s) ? subs.filter((x) => x !== s) : [...subs, s])}>
              {s}
            </button>
          ))}
        </div>
      </Section>

      <div style={{ height: 14 }} />

      <Section title="Upcoming deadlines" aside={`${upcoming.length} in ${subs.join(', ') || '—'}`}>
        {upcoming.map((c) => (
          <div className="row" key={c.id}>
            <span className="num" style={{
              minWidth: 44, fontWeight: 600,
              color: c.left <= 7 ? 'var(--bad)' : c.left <= 30 ? 'var(--warn)' : 'var(--muted)',
            }}>
              {c.left}d
            </span>
            <div className="grow">
              <a href={c.link} target="_blank" rel="noreferrer"
                 style={{ color: 'var(--ink)', fontWeight: 500, textDecoration: 'none' }}>
                {c.title} {c.year}
              </a>{' '}
              <span className="muted">· {c.place}</span>
              <div className="muted" style={{ fontSize: 11.5 }}>
                <Mono>{(c.deadline || '').slice(0, 16)}</Mono> {c.timezone}
                {c.abstract_deadline && <> · abstract <Mono>{c.abstract_deadline.slice(0, 10)}</Mono></>}
                {c.date && <> · {c.date}</>}
              </div>
            </div>
            {asArray(c.sub).map((s) => <span key={s} className="chip">{s}</span>)}
            <button className="btn ghost" style={{ fontSize: 11, padding: '1px 8px' }}
                    disabled={!!added[c.id]}
                    onClick={() => adopt(c)}>
              {added[c.id] ? 'in plan ✓' : '→ plan'}
            </button>
          </div>
        ))}
        {!upcoming.length && (
          <Empty>No upcoming deadlines in the selected categories — pick more above.</Empty>
        )}
      </Section>
    </>
  )
}
