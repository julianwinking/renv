// Paper workspace: the tab bar is a list of views. A view is one tab-bar
// item — either a single paper/note, or a split pair (one side may be empty
// while waiting for a drop). Other views stay independent, so you can have
// several splits plus ordinary tabs at once.
//
// Docking libraries (dockview, flexlayout, …) are built for IDE-style nested
// grids; @dnd-kit / react-resizable-panels cover reorder and resize, not this
// model. The domain is two panes and a tab bar, so the state lives here.

export const LIBRARY = 'library'

const newId = () => (crypto.randomUUID ? crypto.randomUUID() : 'v' + Math.random().toString(36).slice(2, 10))

const withActive = (views, active) => ({
  views,
  active: active === LIBRARY || views.some((v) => v.id === active) ? active : LIBRARY,
})

// After a tab is dragged out: drop empty views, collapse a leftover pane to a
// single. Intentional vacancies ([tab, null] from the split button) are never
// run through this — only toggleSplit creates those.
const compactView = (view) => {
  const filled = view.panes.filter(Boolean)
  if (!filled.length) return null
  return { ...view, panes: filled.length === 2 ? view.panes.slice(0, 2) : filled }
}

const isView = (v) => v && v.id && Array.isArray(v.panes) && v.panes.length >= 1 && v.panes.length <= 2

export function loadWorkspace(raw) {
  if (!raw || typeof raw !== 'object') return { views: [], active: LIBRARY }
  if (Array.isArray(raw.views)) return withActive(raw.views.filter(isView), raw.active || LIBRARY)
  return migrateLegacy(raw)
}

// previous shape: { tabs, active: key, split: key }
function migrateLegacy({ tabs = [], active = LIBRARY, split = null }) {
  const list = Array.isArray(tabs) ? tabs : []
  const byKey = new Map(list.map((t) => [t.key, t]))
  const canPair = split && active && active !== LIBRARY && active !== split
    && byKey.has(active) && byKey.has(split)
  if (canPair) {
    const used = new Set([active, split])
    const views = [
      { id: newId(), panes: [byKey.get(active), byKey.get(split)] },
      ...list.filter((t) => !used.has(t.key)).map((t) => ({ id: newId(), panes: [t] })),
    ]
    return { views, active: views[0].id }
  }
  const views = list.map((t) => ({ id: newId(), panes: [t] }))
  const nextActive = active === LIBRARY || !byKey.has(active)
    ? LIBRARY
    : views.find((v) => v.panes.some((p) => p?.key === active))?.id || LIBRARY
  return { views, active: nextActive }
}

export function pruneViews(ws, papers) {
  const ok = (p) => !p || p.type !== 'paper' || papers.some((x) => x.key === p.key && x.has_pdf)
  const views = ws.views.map((v) => {
    const panes = v.panes.map((p) => (ok(p) ? p : null))
    const filled = panes.filter(Boolean)
    if (!filled.length) return null
    const waiting = v.panes.length === 2 && v.panes.some((p) => !p)
    if (waiting && filled.length === 1) return { ...v, panes }
    return { ...v, panes: filled }
  }).filter(Boolean)
  const next = withActive(views, ws.active)
  const same = next.active === ws.active && next.views.length === ws.views.length
    && next.views.every((v, i) => v.id === ws.views[i].id
      && v.panes.length === ws.views[i].panes.length
      && v.panes.every((p, j) => p === ws.views[i].panes[j]))
  return same ? ws : next
}

export function openTab(ws, tab) {
  const existing = ws.views.find((v) => v.panes.some((p) => p?.key === tab.key))
  if (existing) return { views: ws.views, active: existing.id }
  const view = { id: newId(), panes: [tab] }
  return { views: [...ws.views, view], active: view.id }
}

export function closePane(ws, viewId, index) {
  const views = ws.views.map((v) => {
    if (v.id !== viewId) return v
    const panes = v.panes.slice()
    panes[index] = null
    // closing a side of a split collapses to the remaining pane
    const filled = panes.filter(Boolean)
    if (!filled.length) return null
    return { ...v, panes: filled }
  }).filter(Boolean)
  return withActive(views, ws.active)
}

export function closeKey(ws, key) {
  const v = ws.views.find((x) => x.panes.some((p) => p?.key === key))
  if (!v) return ws
  return closePane(ws, v.id, v.panes.findIndex((p) => p?.key === key))
}

export function renameDoc(ws, docId, title) {
  return {
    ...ws,
    views: ws.views.map((v) => ({
      ...v,
      panes: v.panes.map((p) => (p?.docId === docId ? { ...p, title } : p)),
    })),
  }
}

// Single tab → split with an empty right pane. Click again to cancel.
export function toggleSplit(ws, viewId) {
  const views = ws.views.map((v) => {
    if (v.id !== viewId) return v
    if (v.panes.length === 1 && v.panes[0]) return { ...v, panes: [v.panes[0], null] }
    const filled = v.panes.filter(Boolean)
    if (v.panes.length === 2 && filled.length === 1) return { ...v, panes: filled }
    return v
  })
  return { views, active: viewId }
}

export function dropTab(ws, side, key, targetId) {
  const { views } = ws
  const dest = targetId || ws.active
  if (dest === LIBRARY || (side !== 'left' && side !== 'right')) return ws
  const target = views.find((v) => v.id === dest)
  const source = views.find((v) => v.panes.some((p) => p?.key === key))
  if (!target || !source) return ws
  const tab = source.panes.find((p) => p?.key === key)
  const targetFilled = target.panes.filter(Boolean)
  if (source.id === target.id && targetFilled.length === 1 && targetFilled[0].key === key) return ws

  const host = (source.id === target.id
    ? target.panes.map((p) => (p?.key === key ? null : p))
    : target.panes).filter(Boolean)

  let displaced = null
  let panes
  if (host.length <= 1) {
    const other = host[0]
    panes = !other ? [tab] : (side === 'left' ? [tab, other] : [other, tab])
  } else {
    displaced = side === 'left' ? host[0] : host[1]
    const kept = side === 'left' ? host[1] : host[0]
    panes = side === 'left' ? [tab, kept] : [kept, tab]
  }

  const next = []
  for (const v of views) {
    if (v.id === source.id && v.id !== target.id) {
      const c = compactView({ ...v, panes: v.panes.map((p) => (p?.key === key ? null : p)) })
      if (c) next.push(c)
      continue
    }
    if (v.id === target.id) {
      next.push({ ...target, panes })
      if (displaced && displaced.key !== tab.key) next.push({ id: newId(), panes: [displaced] })
      continue
    }
    next.push(v)
  }
  return { views: next, active: target.id }
}

export function activeView(ws) {
  return ws.views.find((v) => v.id === ws.active) || null
}

export function isSplit(view) {
  return !!view && view.panes.length === 2
}
