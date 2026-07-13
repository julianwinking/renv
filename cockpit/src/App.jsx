import React, { useCallback, useEffect, useRef, useState } from 'react'
import { getOverview, getMetricDefs, search } from './api.js'
import Overview from './views/Overview.jsx'
import GraphView from './views/GraphView.jsx'
import Experiments from './views/Experiments.jsx'
import Papers from './views/Papers.jsx'
import Claims from './views/Claims.jsx'
import Findings from './views/Findings.jsx'
import Timeline from './views/Timeline.jsx'

const I = {
  overview: <path d="M2 2h4.5v6.5H2zM8.5 2H13v4H8.5zM8.5 7.5H13V13H8.5zM2 10h4.5v3H2z" />,
  graph: <path d="M2 7h3M9 4h3M9 10h3M5 7c2 0 2-3 4-3M5 7c2 0 2 3 4 3M2.5 7m-1.3 0a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0-2.6 0M12 4m-1.3 0a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0-2.6 0M12 10m-1.3 0a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0-2.6 0" fill="none" stroke="currentColor" strokeWidth="1.2" />,
  experiments: <path d="M6 2v4L2.5 12a1 1 0 0 0 .9 1.5h8.2a1 1 0 0 0 .9-1.5L9 6V2M4.5 2h6M5 9.5h5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />,
  papers: <path d="M3.5 1.5h6L12 4v9.5a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1zM5 6h5M5 8.5h5M5 11h3" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />,
  claims: <path d="M7.5 1.5 13 4.5v6l-5.5 3-5.5-3v-6zM7.5 7.5V13M7.5 7.5 13 4.5M7.5 7.5 2 4.5" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />,
  findings: <path d="M7.5 2 14 13H1zM7.5 6v3.2M7.5 11.2v.4" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />,
  timeline: <path d="M7.5 7.5m-6 0a6 6 0 1 0 12 0a6 6 0 1 0-12 0M7.5 4.5v3l2.2 1.5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />,
}

const VIEWS = ['overview', 'graph', 'experiments', 'papers', 'claims', 'findings', 'timeline']

function initialTheme() {
  const saved = localStorage.getItem('reref-theme')
  if (saved) return saved
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [overview, setOverview] = useState(null)
  const [defs, setDefs] = useState({})
  const [slug, setSlug] = useState(null)
  const [view, setView] = useState(() => {
    const h = location.hash.replace('#/', '')
    return VIEWS.includes(h) ? h : 'overview'
  })
  const [theme, setTheme] = useState(initialTheme)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('reref-sidebar') === 'collapsed')
  const [hits, setHits] = useState(null)
  const searchRef = useRef(null)

  useEffect(() => {
    localStorage.setItem('reref-sidebar', collapsed ? 'collapsed' : 'open')
  }, [collapsed])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('reref-theme', theme)
  }, [theme])

  useEffect(() => { location.hash = '#/' + view }, [view])

  useEffect(() => {   // deep links: react to external hash navigation too
    const onHash = () => {
      const h = location.hash.replace('#/', '')
      if (VIEWS.includes(h)) setView(h)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const loadOverview = useCallback(async () => {
    const o = await getOverview()
    setOverview(o)
    setSlug((cur) => cur || o.projects[0]?.slug || null)
  }, [])

  useEffect(() => {
    loadOverview()
    getMetricDefs().then(setDefs)
  }, [loadOverview])

  const runSearch = async (q) => {
    if (!q.trim()) { setHits(null); return }
    setHits(await search(q))
  }

  const project = overview?.projects.find((p) => p.slug === slug)
  const counts = overview?.counts || {}
  const inv = overview?.invariants
  const openFindings = project?.open_findings || 0

  const PanelIcon = (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <rect x="1.5" y="2.5" width="13" height="11" rx="2" />
      <path d="M6 2.5v11" />
    </svg>
  )

  return (
    <div className="app">
      {!collapsed && (
      <aside>
        <div className="brand-row">
          <h1 className="brand">
            <span className="re">re</span>ref
            <small>research cockpit</small>
          </h1>
          <button className="iconbtn" title="Collapse sidebar" onClick={() => setCollapsed(true)}>
            {PanelIcon}
          </button>
        </div>

        <div className="eyebrow">Project</div>
        {(overview?.projects || []).map((p) => (
          <button key={p.slug} className={`proj ${p.slug === slug ? 'active' : ''}`}
                  onClick={() => setSlug(p.slug)}>
            <span className="dot" />
            <span>{p.slug}</span>
          </button>
        ))}
        {overview && overview.projects.length === 0 && (
          <div className="muted" style={{ padding: '4px 9px' }}>
            none yet — <span className="mono">reref new &lt;slug&gt;</span>
          </div>
        )}

        <div className="eyebrow">Views</div>
        {VIEWS.map((v) => (
          <button key={v} className={`navitem ${view === v ? 'active' : ''}`} onClick={() => setView(v)}>
            <svg viewBox="0 0 15 15" fill="currentColor">{I[v]}</svg>
            <span style={{ textTransform: 'capitalize' }}>{v}</span>
            {v === 'findings' && openFindings > 0 && <span className="badge">{openFindings}</span>}
          </button>
        ))}

        <div className="side-counts">
          <b>{counts.paper ?? 0}</b> papers · <b>{counts.run ?? 0}</b> runs<br />
          <b>{counts.claim ?? 0}</b> claims · <b>{counts.note ?? 0}</b> notes
        </div>
      </aside>
      )}

      <div className="main">
        <div className="topbar">
          {collapsed && (
            <button className="iconbtn" title="Show sidebar" onClick={() => setCollapsed(false)}>
              {PanelIcon}
            </button>
          )}
          <h2>
            {project ? project.slug : 'reref'} <span className="crumb">/ {view}</span>
          </h2>
          <div className="searchbox">
            <input
              ref={searchRef}
              placeholder="Search papers, claims, log, notes…"
              onKeyDown={(e) => { if (e.key === 'Enter') runSearch(e.target.value); if (e.key === 'Escape') { setHits(null); e.target.value = '' } }}
              onBlur={() => setTimeout(() => setHits(null), 200)}
            />
            {hits && (
              <div className="search-pop">
                {hits.map((h, i) => (
                  <div key={i} className="search-hit">
                    <span className="chip">{h.kind}</span> <b>{h.title}</b>
                    <div className="snippet" dangerouslySetInnerHTML={{
                      __html: (h.snippet || '').replace(/</g, '&lt;').replace(/\[/g, '<b>').replace(/\]/g, '</b>'),
                    }} />
                  </div>
                ))}
                {!hits.length && <div className="search-hit muted">No matches in the store.</div>}
              </div>
            )}
          </div>
          {inv && (
            <span className={`ledger ${inv.clean ? '' : 'dirty'}`}
                  title={inv.clean ? 'every result entry traces to a run' : `${inv.violations} §0 violation(s) — run reref log check`}>
              <span className="lamp" />
              §0 ledger {inv.clean ? 'clean' : `${inv.violations} violation${inv.violations > 1 ? 's' : ''}`}
            </span>
          )}
          <button className="iconbtn" title="Toggle theme"
                  onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? (
              <svg width="13" height="13" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.2">
                <circle cx="7.5" cy="7.5" r="3.2" /><path d="M7.5 1v1.8M7.5 12.2V14M1 7.5h1.8M12.2 7.5H14M3 3l1.3 1.3M10.7 10.7 12 12M12 3l-1.3 1.3M4.3 10.7 3 12" strokeLinecap="round" />
              </svg>
            ) : (
              <svg width="13" height="13" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.2">
                <path d="M13 9.5A6 6 0 0 1 5.5 2 6 6 0 1 0 13 9.5z" strokeLinejoin="round" />
              </svg>
            )}
          </button>
        </div>

        <div className={`content ${view === 'graph' ? 'full' : ''}`}>
          {!slug && <div className="loading">no project selected</div>}
          {slug && view === 'overview' && <Overview slug={slug} project={project} defs={defs} counts={counts} />}
          {slug && view === 'graph' && <GraphView slug={slug} defs={defs} onMutate={loadOverview} />}
          {slug && view === 'experiments' && <Experiments slug={slug} defs={defs} />}
          {view === 'papers' && <Papers />}
          {slug && view === 'claims' && <Claims slug={slug} />}
          {slug && view === 'findings' && <Findings slug={slug} />}
          {slug && view === 'timeline' && <Timeline slug={slug} />}
        </div>
      </div>
    </div>
  )
}
