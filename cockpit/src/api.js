// Tiny API client for the Python reref backend (proxied to /api in dev).
export const api = (p) => fetch(p).then((r) => r.json())
export const post = (p, body) =>
  fetch(p, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json())

export const getOverview = () => api('/api/overview')
export const getMetricDefs = () => api('/api/metric_defs')
export const getGraph = (slug) => api('/api/graph/' + encodeURIComponent(slug))
export const getProject = (slug) => api('/api/project/' + encodeURIComponent(slug))
export const getRuns = (slug) => api('/api/project/' + encodeURIComponent(slug) + '/runs')
export const getPapers = () => api('/api/papers')
export const getPaperUsage = (key) => api('/api/paper/' + encodeURIComponent(key) + '/usage')
export const getFinding = (id) => api('/api/finding/' + id)
export const getClaim = (id) => api('/api/claim/' + id)
export const adjudicate = (id, verdict, reasoning) =>
  post('/api/finding/adjudicate', { id, verdict, reasoning, by: 'cockpit' })
export const addNote = (project, body, title) => post('/api/note', { project, body, title })
export const addLog = (project, type, body, extra = {}) =>
  post('/api/log', { project, type, body, source: 'cockpit', ...extra })
export const addClaim = (project, text, kind) => post('/api/claim', { project, text, kind })
export const createProject = (slug, title) => post('/api/project', { slug, title })
export const addExperiment = (project, slug, title, hypothesis, parent) =>
  post('/api/experiment', { project, slug, title, hypothesis, parent })
export const setExperimentParent = (project, slug, parent) =>
  post('/api/experiment/parent', { project, slug, parent })
export const relateClaims = (claim_id, related_id, kind, note) =>
  post('/api/claim/relate', { claim_id, related_id, kind, note })
export const linkExperimentToClaim = (project, experiment, claim_id, stance, note) =>
  post('/api/claim/link_experiment', { project, experiment, claim_id, stance, note })
export const saveLayout = (project, positions) =>
  post('/api/graph/layout', { project, positions })
export const search = (q) => api('/api/search?q=' + encodeURIComponent(q))
export const getConfigFiles = (project) =>
  api('/api/config/files' + (project ? '?project=' + encodeURIComponent(project) : ''))
export const getConfigFile = (scope, name, project) =>
  api(`/api/config/file?scope=${scope}&name=${encodeURIComponent(name)}` +
      (project ? '&project=' + encodeURIComponent(project) : ''))
export const saveConfigFile = (scope, name, content, project) =>
  post('/api/config/file', { scope, name, content, project })
export const defineMetric = (def) => post('/api/metric_def', def)
export const saveProjectSettings = (slug, settings) =>
  post('/api/project/settings', { slug, ...settings })
export const getRubric = () => api('/api/rubric')
export const getHealth = (slug) => api('/api/health/' + encodeURIComponent(slug))
