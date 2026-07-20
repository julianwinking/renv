// Clean-URL routing over the History API (no `#`). Paths look like `/overview`
// or `/papers/<key>`. The server serves the SPA shell for any such route, so
// reloads and deep links resolve; assets and /api keep their real responses.

// Navigate to a path. pushState does NOT emit popstate, so we dispatch one —
// App listens for popstate and re-parses location.pathname, which keeps every
// navigation (sidebar, search hit, graph node, Back/Forward) on one code path.
export function navigate(path) {
  if (location.pathname === path) return
  history.pushState(null, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

// pathname → {slug, view, focus}. Every page lives under its project, so a
// different project can be open in each browser tab:
//   /<slug>                       → that project's overview
//   /<slug>/<view>                → a view (graph, claims, settings, …)
//   /<slug>/<view>/<focus>        → a deep link (paper key, claim id, exp slug)
export function parsePath(views) {
  const seg = location.pathname.replace(/^\/+/, '').split('/').filter(Boolean)
  return {
    slug: seg[0] ? decodeURIComponent(seg[0]) : null,
    view: views.includes(seg[1]) ? seg[1] : 'overview',
    focus: seg[2] ? decodeURIComponent(seg[2]) : null,
  }
}

// Build a route path from parts (slug required; view/focus optional).
export function routePath(slug, view = 'overview', focus = null) {
  return '/' + encodeURIComponent(slug) + '/' + view +
    (focus ? '/' + encodeURIComponent(focus) : '')
}
