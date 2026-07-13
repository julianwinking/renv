import React, { useCallback, useEffect, useRef, useState } from 'react'
import { getOverview, getMetricDefs, search, createProject, getHealth } from './api.js'
import Overview from './views/Overview.jsx'
import GraphView from './views/GraphView.jsx'
import Experiments from './views/Experiments.jsx'
import Papers from './views/Papers.jsx'
import Claims from './views/Claims.jsx'
import Findings from './views/Findings.jsx'
import Timeline from './views/Timeline.jsx'
import Plan from './views/Plan.jsx'
import { Instructions, Templates, Settings } from './views/Admin.jsx'
import Conferences from './views/Conferences.jsx'
import { ErrorBoundary } from './ui.jsx'

const I = {
  overview: <path d="M2 2h4.5v6.5H2zM8.5 2H13v4H8.5zM8.5 7.5H13V13H8.5zM2 10h4.5v3H2z" />,
  instructions: <path d="M3 2.5h7l2 2v8a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM5 6.5h5M5 9h5M5 11.5h3" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />,
  templates: <path d="M2 2.5h11v3H2zM2 7.5h4.5V13H2zM8.5 7.5H13V13H8.5z" fill="none" stroke="currentColor" strokeWidth="1.1" />,
  settings: <path d="M2.5 4.5h7M11.5 4.5h1M9.5 3.2v2.6M2.5 10.5h1M5.5 10.5h7M5.5 9.2v2.6" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />,
  conferences: <path d="M2.5 3.5h10a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-10a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1zM1.5 6.5h12M5 2v3M10 2v3M4.5 9h2M8.5 9h2M4.5 11.2h2" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />,
  graph: <path d="M2 7h3M9 4h3M9 10h3M5 7c2 0 2-3 4-3M5 7c2 0 2 3 4 3M2.5 7m-1.3 0a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0-2.6 0M12 4m-1.3 0a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0-2.6 0M12 10m-1.3 0a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0-2.6 0" fill="none" stroke="currentColor" strokeWidth="1.2" />,
  timeline: <path d="M2 3h6v2.2H2zM4.5 6.4h7v2.2h-7zM7 9.8h6V12H7z" />,
  experiments: <path d="M6 2v4L2.5 12a1 1 0 0 0 .9 1.5h8.2a1 1 0 0 0 .9-1.5L9 6V2M4.5 2h6M5 9.5h5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />,
  papers: <path d="M3.5 1.5h6L12 4v9.5a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1zM5 6h5M5 8.5h5M5 11h3" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />,
  claims: <path d="M7.5 1.5 13 4.5v6l-5.5 3-5.5-3v-6zM7.5 7.5V13M7.5 7.5 13 4.5M7.5 7.5 2 4.5" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />,
  findings: <path d="M7.5 2 14 13H1zM7.5 6v3.2M7.5 11.2v.4" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />,
  log: <path d="M7.5 7.5m-6 0a6 6 0 1 0 12 0a6 6 0 1 0-12 0M7.5 4.5v3l2.2 1.5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />,
}

const VIEWS = ['overview', 'graph', 'claims', 'experiments', 'papers', 'findings', 'timeline', 'log']
const ADMIN = ['instructions', 'templates', 'settings']
const TOOLS = ['conferences']
const ALL_VIEWS = [...VIEWS, ...ADMIN, ...TOOLS]

// routes: #/<view> or #/<view>/<focus> — a focus deep-links one entity
// (experiment slug, claim id, paper key, timeline entry) inside its view
function parseHash() {
  const seg = location.hash.replace(/^#\//, '').split('/')
  return {
    view: ALL_VIEWS.includes(seg[0]) ? seg[0] : 'overview',
    focus: seg[1] ? decodeURIComponent(seg[1]) : null,
  }
}

function initialTheme() {
  const saved = localStorage.getItem('reref-theme')
  if (saved) return saved
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [overview, setOverview] = useState(null)
  const [defs, setDefs] = useState({})
  const [slug, setSlug] = useState(null)
  const [route, setRoute] = useState(parseHash)
  const { view, focus } = route
  const setView = (v) => setRoute({ view: v, focus: null })
  const [theme, setTheme] = useState(initialTheme)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('reref-sidebar') === 'collapsed')
  const [sideW, setSideW] = useState(() => Number(localStorage.getItem('reref-sidebar-w')) || 228)
  const [hits, setHits] = useState(null)
  const [health, setHealth] = useState(null)
  const [healthOpen, setHealthOpen] = useState(false)
  const [hpos, setHpos] = useState({ top: 46, right: 12 })
  const [switcher, setSwitcher] = useState(false)   // false | 'list' | 'create'
  const [spos, setSpos] = useState({ top: 130, left: 12 })  // anchored under the switcher
  const [pfilter, setPfilter] = useState('')
  const [newProj, setNewProj] = useState({})
  const [perr, setPerr] = useState(null)
  const searchRef = useRef(null)

  const createProj = async () => {
    setPerr(null)
    const r = await createProject((newProj.slug || '').trim(), (newProj.title || '').trim())
    if (r && r.error) { setPerr(r.error); return }
    setSwitcher(false)
    setNewProj({})
    await loadOverview()
    setSlug(r.slug)
  }

  useEffect(() => {
    localStorage.setItem('reref-sidebar', collapsed ? 'collapsed' : 'open')
  }, [collapsed])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('reref-theme', theme)
  }, [theme])

  useEffect(() => {
    const h = '#/' + view + (focus ? '/' + encodeURIComponent(focus) : '')
    if (location.hash !== h) location.hash = h
    document.title = view.charAt(0).toUpperCase() + view.slice(1)
  }, [view, focus])

  useEffect(() => {   // deep links: react to external hash navigation too
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {   // ⌘K / Ctrl-K jumps into search
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        searchRef.current?.focus()
        searchRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
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

  useEffect(() => {
    if (slug) getHealth(slug).then(setHealth)
  }, [slug, view])

  const debounceRef = useRef(null)
  const runSearch = async (q) => {
    if (!q.trim()) { setHits(null); return }
    setHits(await search(q))
  }
  const onSearchInput = (q) => {   // live search while typing
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runSearch(q), 220)
  }

  const openHit = (h) => {   // a result click deep-links into its view
    if (h.project) setSlug(h.project)
    const go = {
      paper: () => '#/papers/' + encodeURIComponent(h.ref),
      card: () => '#/papers/' + encodeURIComponent(String(h.ref).split('/')[0]),
      claim: () => '#/claims/' + h.ref,
      log: () => '#/log/' + encodeURIComponent('log-' + h.ref),
      note: () => '#/log/' + encodeURIComponent('note-' + h.ref),
    }[h.kind]
    if (go) location.hash = go()
    setHits(null)
    if (searchRef.current) { searchRef.current.value = ''; searchRef.current.blur() }
  }

  const project = overview?.projects.find((p) => p.slug === slug)
  const counts = overview?.counts || {}
  const openFindings = project?.open_findings || 0

  const clampW = (w) => Math.min(400, Math.max(180, w))
  const startResize = (e) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = sideW
    let w = startW
    const move = (ev) => { w = clampW(startW + ev.clientX - startX); setSideW(w) }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      localStorage.setItem('reref-sidebar-w', String(w))
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const PanelIcon = (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <rect x="1.5" y="2.5" width="13" height="11" rx="2" />
      <path d="M6 2.5v11" />
    </svg>
  )

  return (
    <div className="app">
      {!collapsed && (
      <aside style={{ width: sideW }}>
        <div className="side-resize" onMouseDown={startResize} title="Drag to resize" />
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
        <button className="pswitch" onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          setSpos({ top: r.bottom + 6, left: r.left })
          setSwitcher('list'); setPfilter('')
        }}>
          <span className="dot"
                style={project?.status === 'archived' ? { background: 'var(--line-strong)' } : null} />
          <span className="pname">{slug || 'select project'}</span>
          <svg className="updown" width="12" height="12" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="1.4">
            <path d="M5 6l3-3 3 3M5 10l3 3 3-3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {switcher && (
          <>
            <div className="backdrop" onClick={() => setSwitcher(false)} />
            <div className="pdialog" style={{ top: spos.top, left: spos.left }}>
              {switcher === 'list' ? (
                <>
                  <div className="find">
                    <input
                      autoFocus placeholder="Find project…" value={pfilter}
                      onChange={(e) => setPfilter(e.target.value)}
                      onKeyDown={(e) => e.key === 'Escape' && setSwitcher(false)}
                    />
                    <kbd>Esc</kbd>
                  </div>
                  <div className="list">
                    {(() => {
                      const hits = (overview?.projects || []).filter((p) =>
                        (p.slug + ' ' + (p.title || '')).toLowerCase().includes(pfilter.toLowerCase()))
                      const groups = [
                        ['Active', hits.filter((p) => p.status !== 'archived')],
                        ['Archived', hits.filter((p) => p.status === 'archived')],
                      ]
                      return groups.filter(([, ps]) => ps.length).map(([label, ps]) => (
                        <div key={label}>
                          <div className="eyebrow" style={{ margin: '6px 9px 3px' }}>{label}</div>
                          {ps.map((p) => (
                            <button key={p.slug} className="item" onClick={() => { setSlug(p.slug); setSwitcher(false) }}>
                              <span className="dot" style={{
                                background: p.status === 'archived' ? 'var(--line-strong)'
                                  : p.slug === slug ? 'var(--accent)' : undefined,
                              }} />
                              <span style={p.status === 'archived' ? { color: 'var(--muted)' } : null}>{p.slug}</span>
                              {p.open_findings > 0 && <span className="badge" style={{ marginLeft: 'auto' }}>{p.open_findings}</span>}
                            </button>
                          ))}
                        </div>
                      ))
                    })()}
                    {overview && overview.projects.length === 0 && (
                      <div className="muted" style={{ padding: '6px 9px' }}>no projects yet</div>
                    )}
                  </div>
                  <div className="createrow">
                    <button className="item" onClick={() => { setSwitcher('create'); setPerr(null) }}>
                      <span style={{ width: 6, textAlign: 'center' }}>+</span> Create project
                    </button>
                  </div>
                </>
              ) : (
                <div style={{ padding: 12, display: 'grid', gap: 8 }}>
                  <div className="eyebrow" style={{ margin: 0 }}>new project</div>
                  <input className="text" autoFocus placeholder="slug, e.g. event-snow-simulator"
                         onChange={(e) => setNewProj({ ...newProj, slug: e.target.value })}
                         onKeyDown={(e) => { if (e.key === 'Escape') setSwitcher(false); if (e.key === 'Enter') createProj() }} />
                  <input className="text" placeholder="title (optional)"
                         onChange={(e) => setNewProj({ ...newProj, title: e.target.value })}
                         onKeyDown={(e) => { if (e.key === 'Enter') createProj() }} />
                  <div className="muted" style={{ fontSize: 11.5 }}>
                    Scaffolds projects/&lt;slug&gt; from the template (ideation, paper skeleton, own git repo).
                  </div>
                  {perr && <div style={{ color: 'var(--bad)', fontSize: 12 }}>{perr}</div>}
                  <div className="gnode-actions" style={{ marginTop: 0 }}>
                    <button className="btn" onClick={createProj} disabled={!(newProj.slug || '').trim()}>Create project</button>
                    <button className="btn ghost" onClick={() => setSwitcher('list')}>Back</button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        <div className="eyebrow">Views</div>
        {VIEWS.map((v) => {
          const n = { experiments: counts.experiment, papers: counts.paper,
                      claims: counts.claim, findings: counts.finding }[v]
          return (
            <button key={v} className={`navitem ${view === v ? 'active' : ''}`} onClick={() => setView(v)}>
              <svg viewBox="0 0 15 15" fill="currentColor">{I[v]}</svg>
              <span style={{ textTransform: 'capitalize' }}>{v}</span>
              {v === 'findings' && openFindings > 0
                ? <span className="badge">{openFindings}</span>
                : n != null && n > 0 ? <span className="count">{n}</span> : null}
            </button>
          )
        })}

        <div className="eyebrow">Admin</div>
        {ADMIN.map((v) => (
          <button key={v} className={`navitem ${view === v ? 'active' : ''}`} onClick={() => setView(v)}>
            <svg viewBox="0 0 15 15" fill="currentColor">{I[v]}</svg>
            <span style={{ textTransform: 'capitalize' }}>{v}</span>
          </button>
        ))}

        <div className="eyebrow">Tools</div>
        {TOOLS.map((v) => (
          <button key={v} className={`navitem ${view === v ? 'active' : ''}`} onClick={() => setView(v)}>
            <svg viewBox="0 0 15 15" fill="currentColor">{I[v]}</svg>
            <span style={{ textTransform: 'capitalize' }}>{v}</span>
          </button>
        ))}
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
            {TOOLS.includes(view) ? 'Tools' : project ? project.slug : 'reref'}{' '}
            <span className="crumb">/ {view.charAt(0).toUpperCase() + view.slice(1)}</span>
          </h2>
          <div className="searchbox">
            <input
              ref={searchRef}
              placeholder="Search papers, claims, log, notes…"
              onChange={(e) => onSearchInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') runSearch(e.target.value); if (e.key === 'Escape') { setHits(null); e.target.value = ''; e.target.blur() } }}
              onBlur={() => setTimeout(() => setHits(null), 200)}
            />
            <kbd>{navigator.platform.includes('Mac') ? '⌘K' : 'Ctrl K'}</kbd>
            {hits && (
              <div className="search-pop">
                {hits.map((h, i) => (
                  <div key={i} className="search-hit" onMouseDown={() => openHit(h)}>
                    <span className="chip">{h.kind}</span> <b>{h.title}</b>
                    {h.project && h.project !== slug && <span className="faint"> · {h.project}</span>}
                    <div className="snippet" dangerouslySetInnerHTML={{
                      __html: (h.snippet || '').replace(/</g, '&lt;').replace(/\[/g, '<b>').replace(/\]/g, '</b>'),
                    }} />
                  </div>
                ))}
                {!hits.length && <div className="search-hit muted">No matches in the store.</div>}
              </div>
            )}
          </div>
          {health && (
            <button className="healthbtn" title="Project health checks"
                    onClick={async (e) => {
                      const r = e.currentTarget.getBoundingClientRect()
                      setHpos({ top: r.bottom + 6, right: window.innerWidth - r.right })
                      setHealth(await getHealth(slug))
                      setHealthOpen(!healthOpen)
                    }}>
              <span className={`lamp lamp-${health.status}`} />
              Project health
            </button>
          )}
          {healthOpen && (
            <>
              <div className="backdrop" onClick={() => setHealthOpen(false)} />
              <div className="pdialog" style={{ top: hpos.top, left: 'auto', right: hpos.right, width: 330 }}>
                <div className="find" style={{ padding: '9px 12px' }}>
                  <span className="eyebrow" style={{ margin: 0 }}>project health</span>
                  <span className="mono faint" style={{ marginLeft: 'auto', fontSize: 10.5 }}>{slug}</span>
                </div>
                <div className="list">
                  {health.checks.map((c) => (
                    <div key={c.id} className="item" style={{ cursor: 'default', alignItems: 'flex-start' }}>
                      <span className={`lamp lamp-${c.status}`} style={{ marginTop: 5 }} />
                      <div>
                        <div style={{ fontWeight: 500 }}>{c.label}</div>
                        <div className="muted" style={{ fontSize: 11.5 }}>{c.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
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
          <ErrorBoundary key={view + '|' + slug}>
          {!slug && <div className="loading">no project selected</div>}
          {slug && view === 'overview' && <Overview slug={slug} project={project} defs={defs} counts={counts} />}
          {slug && view === 'graph' && <GraphView slug={slug} defs={defs} onMutate={loadOverview} />}
          {slug && view === 'timeline' && <Plan slug={slug} />}
          {slug && view === 'experiments' && <Experiments slug={slug} defs={defs} focus={focus} />}
          {view === 'papers' && <Papers focus={focus} />}
          {slug && view === 'claims' && <Claims slug={slug} focus={focus} />}
          {slug && view === 'findings' && <Findings slug={slug} />}
          {slug && view === 'log' && <Timeline slug={slug} focus={focus} />}
          {slug && view === 'instructions' && <Instructions slug={slug} />}
          {view === 'templates' && <Templates slug={slug} />}
          {slug && view === 'settings' && <Settings slug={slug} project={project} onMutate={loadOverview} />}
          {slug && view === 'conferences' && <Conferences slug={slug} />}
          </ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
