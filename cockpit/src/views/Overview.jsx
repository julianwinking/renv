import React, { useEffect, useState } from 'react'
import { getProject, getRuns, getPlan, getArgument } from '../api.js'
import { asArray, Stamp, Metrics, Section, Empty, Mono, timeAgo, Provenance } from '../ui.jsx'

const CRIT_LABEL = { 3: 'thesis', 2: 'thesis-critical', 1: 'contribution', 0: '' }

export default function Overview({ slug, project, defs, counts }) {
  const [data, setData] = useState(null)
  const [runs, setRuns] = useState([])
  const [plan, setPlan] = useState([])
  const [arg, setArg] = useState(null)

  useEffect(() => {
    let live = true
    getProject(slug).then((d) => live && setData(d))
    getRuns(slug).then((r) => live && setRuns(asArray(r)))
    getPlan(slug).then((p) => live && setPlan(asArray(p)))
    getArgument(slug).then((a) => live && setArg(a && !a.error ? a : null))
    return () => { live = false }
  }, [slug])

  if (!data) return <div className="loading">reading the store…</div>

  const claims = data.claims || []
  const supported = claims.filter((c) => c.status === 'supported').length
  const openFindings = (data.findings || []).filter((f) => f.status === 'open')
  const log = (data.log || []).slice(0, 6)

  // the next deadline: standalone or at a phase's end, not done, not past
  const today = new Date().toISOString().slice(0, 10)
  const nextDl = plan
    .filter((i) => i.status !== 'done' && (i.kind === 'deadline' || i.end_deadline) && i.due >= today)
    .sort((a, b) => (a.due < b.due ? -1 : 1))[0]
  const dlDays = nextDl
    ? Math.round((new Date(nextDl.due + 'T00:00:00Z') - new Date(today + 'T00:00:00Z')) / 86400000)
    : null

  return (
    <>
      <div className="pagehead">
        <h1>{project?.title || slug}</h1>
      </div>

      <div className="stats">
        <div className="stat"><b>{data.experiments.length}</b><span>experiments</span></div>
        <div className="stat"><b>{runs.length}</b><span>runs</span></div>
        <div className="stat"><b>{supported}/{claims.length}</b><span>claims backed</span></div>
        <div className={`stat ${openFindings.length ? 'alert' : ''}`}>
          <b>{openFindings.length}</b><span>open findings</span>
        </div>
        <div className="stat"><b>{counts.paper ?? 0}</b><span>papers</span></div>
        {nextDl && (
          <div className={`stat ${!nextDl.prepared && dlDays <= 7 ? 'alert' : ''}`}
               title={`${nextDl.title} · ${nextDl.due}${nextDl.prepared ? ' · prepared' : ' · not prepared yet'}`}>
            <b>{dlDays}d</b>
            <span>to deadline{nextDl.prepared ? ' ✓' : ''}</span>
          </div>
        )}
      </div>

      {arg && (arg.contradictions.length > 0 || arg.summary.broken_foundations > 0) && (
        <div className="alerts">
          {arg.contradictions.map((x, i) => (
            <div className="alert-row bad" key={`c${i}`}>
              <span className="alert-tag">Contradiction</span>
              <span>Two supported claims contradict each other: “{x.a_text.slice(0, 60)}…” vs “{x.b_text.slice(0, 60)}…”</span>
            </div>
          ))}
          {arg.summary.broken_foundations > 0 && (
            <div className="alert-row warn">
              <span className="alert-tag">Foundation</span>
              <span>{arg.summary.broken_foundations} claim(s) rest on a refuted lemma — supported on their own, but their argument is undermined.</span>
            </div>
          )}
        </div>
      )}

      {arg && arg.frontier.length > 0 && (
        <>
          <Section title="Next up" aside="open, thesis-critical claims — ranked">
            {arg.frontier.slice(0, 6).map((f) => (
              <div className="row" key={f.id}>
                <Stamp value={f.status} />
                <div className="grow">
                  {f.text}
                  <div className="muted" style={{ fontSize: 11.5 }}>→ {f.next}</div>
                </div>
                {CRIT_LABEL[f.criticality] && <span className="chip">{CRIT_LABEL[f.criticality]}</span>}
              </div>
            ))}
          </Section>
          <div style={{ height: 14 }} />
        </>
      )}

      <div className="grid cols-2">
        <Section title="Latest runs" aside={`${runs.length} recorded`}>
          {runs.slice(0, 6).map((r) => (
            <div className="row" key={r.id}>
              <Mono>#{r.id}</Mono>
              <div className="grow">
                <Mono>{r.experiment}</Mono>{' '}
                <span style={{ marginLeft: 6 }}><Metrics defs={defs} metrics={r.metrics} /></span>
              </div>
              <Stamp value={r.status} />
              <Provenance run={r} />
              <span className="when">{timeAgo(r.started)}</span>
            </div>
          ))}
          {!runs.length && (
            <Empty>No runs recorded yet — <code>reref exp run …</code> puts the first number in the ledger.</Empty>
          )}
        </Section>

        <Section title="Claims" aside="Status derived from evidence">
          {claims.map((c) => (
            <div className="row" key={c.id}>
              <Stamp value={c.status} />
              <div className="grow">{c.text}</div>
              <span className="chip">{c.kind}</span>
            </div>
          ))}
          {!claims.length && (
            <Empty>No claims yet — <code>reref claim add</code> states the thesis your runs must back.</Empty>
          )}
        </Section>
      </div>

      <div style={{ height: 14 }} />

      <Section title="Recent log" aside="Newest first">
        {log.map((e) => (
          <div className="row" key={e.id}>
            <Stamp value={e.type} tone={e.type === 'result' ? 'ok' : e.type === 'blocker' ? 'bad' : 'idle'} />
            <div className="grow" style={{ whiteSpace: 'pre-wrap' }}>{e.body_md}</div>
            <span className="when">{timeAgo(e.ts)}</span>
          </div>
        ))}
        {!log.length && (
          <Empty>The decision log is empty — <code>reref log add …</code> records the why before the work.</Empty>
        )}
      </Section>
    </>
  )
}
