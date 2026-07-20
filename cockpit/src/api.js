// Tiny API client for the Python renv backend (proxied to /api in dev).
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
export const paperPdfUrl = (key) => '/api/paper/' + encodeURIComponent(key) + '/pdf'
export const getPaperAnchors = (key, project) =>
  api('/api/paper/' + encodeURIComponent(key) + '/anchors' +
      (project ? '?project=' + encodeURIComponent(project) : ''))
export const addPaper = (source, download = true) => post('/api/paper/add', { source, download })
export const getPaperReferences = (key) =>
  api('/api/paper/' + encodeURIComponent(key) + '/references')
export const buildPaperReferences = (key) => post('/api/reference/build', { key })
export const markReference = (id, verdict, comment) =>
  post('/api/reference/mark', { id, verdict, comment })
export const addReference = (id, download = true) => post('/api/reference/add', { id, download })
export const getInbox = () => api('/api/inbox')
export const markPaperRead = (key) => post('/api/paper/read', { key })
export const editPaper = (id, title) => post('/api/paper/update', { id, title })
export const addPaperNote = (note) => post('/api/paper/note', note)
export const getPaperDocs = (key, project) =>
  api('/api/paper/' + encodeURIComponent(key) + '/docs' +
      (project ? '?project=' + encodeURIComponent(project) : ''))
export const getPaperDoc = (id) => api('/api/paper/doc/' + id)
export const createPaperDoc = (doc) => post('/api/paper/doc', doc)
export const updatePaperDoc = (id, fields) => post('/api/paper/doc/update', { id, ...fields })
export const deletePaperDoc = (id) => post('/api/paper/doc/delete', { id })
export const updatePaperNote = (id, fields) => post('/api/paper/note/update', { id, ...fields })
export const deletePaperNote = (id) => post('/api/paper/note/delete', { id })
export const getFinding = (id) => api('/api/finding/' + id)
export const getClaim = (id) => api('/api/claim/' + id)
export const adjudicate = (id, verdict, reasoning) =>
  post('/api/finding/adjudicate', { id, verdict, reasoning, by: 'cockpit' })
export const addNote = (project, body, title) => post('/api/note', { project, body, title })
export const addLog = (project, type, body, extra = {}) =>
  post('/api/log', { project, type, body, source: 'cockpit', ...extra })
export const editLog = (id, body) => post('/api/log/edit', { id, body })
export const editNote = (id, body) => post('/api/note/edit', { id, body })
export const addClaim = (project, text, kind) => post('/api/claim', { project, text, kind })
export const editClaim = (id, text) => post('/api/claim/edit', { id, text })
export const getConnections = () => api('/api/connections')
export const addContextLink = (link) => post('/api/link', link)
export const createProject = (slug, title) => post('/api/project', { slug, title })
export const addExperiment = (project, slug, title, hypothesis, parent) =>
  post('/api/experiment', { project, slug, title, hypothesis, parent })
export const setExperimentParent = (project, slug, parent) =>
  post('/api/experiment/parent', { project, slug, parent })
export const editExperiment = (project, slug, fields) =>
  post('/api/experiment/update', { project, slug, ...fields })
export const relateClaims = (claim_id, related_id, kind, note) =>
  post('/api/claim/relate', { claim_id, related_id, kind, note })
export const linkExperimentToClaim = (project, experiment, claim_id, stance, note, grade) =>
  post('/api/claim/link_experiment', { project, experiment, claim_id, stance, note, grade })
export const linkCitationToClaim = (claim_id, citation_id, stance, note, grade) =>
  post('/api/claim/link', { claim_id, citation_id, stance, note, grade })
export const saveLayout = (project, positions) =>
  post('/api/graph/layout', { project, positions })
export const getRegions = (slug) => api('/api/regions/' + encodeURIComponent(slug))
export const addRegion = (project, r) => post('/api/region', { project, ...r })
export const updateRegion = (id, fields) => post('/api/region/update', { id, ...fields })
export const deleteRegion = (id) => post('/api/region/delete', { id })
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
export const getRemotes = () => api('/api/remotes')
export const getConferences = () => api('/api/conferences')
export const addRemote = (r) => post('/api/remote', r)
export const getHealth = (slug) => api('/api/health/' + encodeURIComponent(slug))
export const getSources = () => api('/api/sources')
export const getPlan = (slug) => api('/api/plan/' + encodeURIComponent(slug))
export const getPhases = (slug) => api('/api/phases/' + encodeURIComponent(slug))
export const setPhaseBand = (plan_item_id, x0, x1) =>
  post('/api/phase_band', { plan_item_id, x0, x1 })
export const clearPhaseBand = (plan_item_id) => post('/api/phase_band/clear', { plan_item_id })
export const setPhaseBandColor = (plan_item_id, color) =>
  post('/api/phase_band/color', { plan_item_id, color })
export const declareTest = (project, experiment, claim_id) =>
  post('/api/claim/test', { project, experiment, claim_id })
export const undeclareTest = (id) => post('/api/claim/test/delete', { id })
export const retractEvidence = (id, reason) =>
  post('/api/claim/evidence/retract', { id, reason })
export const confirmEvidence = (id) => post('/api/claim/evidence/confirm', { id })
export const deleteClaimRelation = (id) => post('/api/claim/relation/delete', { id })
export const deleteContextLink = (id) => post('/api/link/delete', { id })
export const runLint = (project) => post('/api/lint', { project })
export const getArgument = (slug) => api('/api/argument/' + encodeURIComponent(slug))
export const addPlanItem = (project, item) => post('/api/plan', { project, ...item })
export const updatePlanItem = (id, fields) => post('/api/plan/update', { id, ...fields })
export const deletePlanItem = (id) => post('/api/plan/delete', { id })
