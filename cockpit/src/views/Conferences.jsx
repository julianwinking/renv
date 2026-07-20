// Tools → Conferences: the ai-deadlines feed (cached server-side, works
// offline). Telescope data — a deadline only becomes research state when you
// adopt it into the plan, which creates a normal plan_item deadline.
import React, { useEffect, useMemo, useState } from 'react'
import { getConferences, addPlanItem, deletePlanItem, getPlan } from '../api.js'
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
    try { return JSON.parse(localStorage.getItem('renv-conf-subs')) || DEFAULT_SUBS }
    catch { return DEFAULT_SUBS }
  })
  const [planned, setPlanned] = useState({})   // plan-item title → plan item id

  const planKey = (c) => `${c.title} ${c.year} deadline`

  useEffect(() => {
    getConferences().then((c) => {
      if (c && c.error) setErr(c.error)
      else setAll(asArray(c))
    })
  }, [])

  const syncPlanned = () => getPlan(slug).then((p) => {
    const map = {}
    for (const it of asArray(p)) map[it.title] = it.id
    setPlanned(map)
  })

  useEffect(() => {   // which conferences are already adopted into the plan?
    if (slug) syncPlanned()
  }, [slug])

  useEffect(() => { localStorage.setItem('renv-conf-subs', JSON.stringify(subs)) }, [subs])

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

  const toggle = async (c) => {
    const key = planKey(c)
    const pid = planned[key]
    if (pid) {
      await deletePlanItem(pid)
    } else {
      await addPlanItem(slug, {
        title: key, kind: 'deadline', due: (c.deadline || '').slice(0, 10),
        note: c.link,
      })
    }
    syncPlanned()   // the store decides — never trust optimistic local state
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
        {upcoming.map((c) => {
          const isPlanned = !!planned[planKey(c)]
          return (
            <div className="row" key={c.id}
                 style={isPlanned ? { background: 'var(--accent-soft)' } : null}>
              <span className="num" style={{
                minWidth: 44, fontWeight: 600,
                color: c.left <= 7 ? 'var(--bad)' : c.left <= 30 ? 'var(--warn)' : 'var(--muted)',
              }}>
                {c.left}d
              </span>
              <div className="grow">
                <a href={c.link} target="_blank" rel="noreferrer"
                   style={{ color: isPlanned ? 'var(--accent)' : 'var(--ink)',
                            fontWeight: 400, textDecoration: 'none' }}>
                  <b style={{ fontWeight: 600 }}>{c.title}</b> {c.year}
                </a>{' '}
                <span className="muted">· {c.place}</span>
                <div className="muted" style={{ fontSize: 11.5 }}>
                  <Mono>{(c.deadline || '').slice(0, 16)}</Mono> {c.timezone}
                  {c.abstract_deadline && <> · abstract <Mono>{c.abstract_deadline.slice(0, 10)}</Mono></>}
                  {c.date && <> · {c.date}</>}
                </div>
              </div>
              {asArray(c.sub).map((s) => <span key={s} className="chip">{s}</span>)}
              <button className="btn ghost" style={{ fontSize: 11, padding: '1px 8px',
                        ...(isPlanned ? { color: 'var(--accent)', borderColor: 'var(--accent)' } : null) }}
                      title={isPlanned ? 'remove from the plan' : 'adopt as a plan deadline'}
                      onClick={() => toggle(c)}>
                {isPlanned ? 'Planned ✓' : '→ Plan'}
              </button>
            </div>
          )
        })}
        {!upcoming.length && (
          <Empty>No upcoming deadlines in the selected categories — pick more above.</Empty>
        )}
      </Section>
    </>
  )
}
