// Tiny API client for the Python reref backend (proxied to /api in dev).
export const api = (p) => fetch(p).then((r) => r.json())
export const post = (p, body) =>
  fetch(p, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json())

export const getOverview = () => api('/api/overview')
export const getGraph = (slug) => api('/api/graph/' + encodeURIComponent(slug))
export const getProject = (slug) => api('/api/project/' + encodeURIComponent(slug))
export const getFinding = (id) => api('/api/finding/' + id)
export const getClaim = (id) => api('/api/claim/' + id)
export const adjudicate = (id, verdict, reasoning) =>
  post('/api/finding/adjudicate', { id, verdict, reasoning, by: 'cockpit' })
export const addNote = (project, body) => post('/api/note', { project, body })
export const search = (q) => api('/api/search?q=' + encodeURIComponent(q))
