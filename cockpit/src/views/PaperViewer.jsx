// The paper viewer: the real PDF (PDF.js) with a reader toolbar (zoom, page
// nav, a Thumbnails/Outline/Search panel) plus the project's citations and the
// reader's positional annotations highlighted in place. Select text to attach a
// note, question, or hypothesis — each becomes a graph node. PDF.js is loaded
// lazily. The pages/thumbnails are written into dedicated refs that React never
// populates, so manual DOM never fights reconciliation.
import React, { useEffect, useRef, useState } from 'react'
import { paperPdfUrl, getPaperAnchors, addPaperNote, updatePaperNote, deletePaperNote,
         getPaperReferences, buildPaperReferences, markReference, addReference } from '../api.js'
import { findRange, findAllRanges, findRefMarkers, paintRects, selectionAnchor } from '../pdfhl.js'

// worst-first: a marker citing several refs shows the most actionable colour
const REF_SEVERITY = ['not_relevant', 'unknown', 'library']
const worstRefStatus = (statuses) =>
  REF_SEVERITY.find((s) => statuses.includes(s)) || 'library'

const REF_STATUS_LABEL = { library: 'in library', unknown: 'not in library', not_relevant: 'not relevant' }

// One reference entry (shared by the hover popup and the References sidebar):
// what the paper is, whether we hold it, and the add / dismiss-with-comment
// actions. `draft` is the open not-relevant comment form ({id, comment}).
function RefRow({ r, compact, draft, setDraft, onAdd, onDismiss, onClear }) {
  const authors = (() => {
    try { return JSON.parse(r.matched_authors || '[]') } catch { return [] }
  })()
  const label = r.matched_title ||
    (r.raw || '').replace(/^\[\d+\]\s*/, '').slice(0, compact ? 90 : 160)
  const formOpen = draft && draft.id === r.id
  return (
    <div className={`pv-refrow ${compact ? 'compact' : ''}`}>
      <div className="pv-refrow-head">
        <span className={`pv-refdot pv-ref-${r.status}`} />
        <span className="num faint">[{r.num}]</span>
        <span className={`pv-refstat pv-refstat-${r.status}`}>{REF_STATUS_LABEL[r.status]}</span>
        {r.matched_inbox ? <span className="pv-refstat pv-refstat-inbox">inbox · unread</span> : null}
      </div>
      <div className="pv-refrow-title">{label}{!r.matched_title && (r.raw || '').length > 160 ? '…' : ''}</div>
      {authors.length > 0 && (
        <div className="pv-refrow-auth faint">
          {authors.slice(0, 4).join(', ')}{authors.length > 4 ? ' …' : ''}{r.matched_year ? ` · ${r.matched_year}` : ''}
        </div>
      )}
      {r.status === 'not_relevant' && r.verdict_comment && (
        <div className="pv-refrow-why">“{r.verdict_comment}”</div>
      )}
      {formOpen ? (
        <div className="pv-refform" onMouseDown={(e) => e.stopPropagation()}>
          <textarea className="inline-edit" autoFocus placeholder="Why is it not relevant? (required)"
                    value={draft.comment}
                    onChange={(e) => setDraft({ id: r.id, comment: e.target.value })} />
          <div className="pv-refrow-tools">
            <button className="btn ghost" onClick={() => setDraft(null)}>Cancel</button>
            <button className="btn" disabled={!draft.comment.trim()}
                    onClick={() => onDismiss(r, draft.comment.trim())}>Mark not relevant</button>
          </div>
        </div>
      ) : (
        <div className="pv-refrow-tools">
          {r.status === 'unknown' && (r.arxiv || r.doi) && (
            <button className="btn" onClick={() => onAdd(r)}>＋ Add to library</button>
          )}
          {r.status === 'unknown' && !(r.arxiv || r.doi) && (
            <span className="faint pv-refrow-hint">no arXiv/DOI in entry — add via Library search</span>
          )}
          {r.status === 'unknown' && (
            <button className="btn ghost" onClick={() => setDraft({ id: r.id, comment: '' })}>✗ Not relevant</button>
          )}
          {r.status === 'not_relevant' && (
            <button className="btn ghost" onClick={() => onClear(r)}>Clear verdict</button>
          )}
          {r.status === 'library' && r.matched_key && (
            <span className="faint pv-refrow-hint">→ {r.matched_key}</span>
          )}
        </div>
      )}
    </div>
  )
}

const NOTE_COLORS = ['amber', 'teal', 'violet', 'rose', 'blue', 'slate']
const PanelIco = ({ side, size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect width="18" height="18" x="3" y="3" rx="2" />
    <path d={side === 'right' ? 'M15 3v18' : 'M9 3v18'} />
  </svg>
)
const KINDS = [
  ['note', 'Annotation', 'Add an annotation at this position…'],
  ['question', 'Question', 'Ask a question about this passage…'],
  ['hypothesis', 'Hypothesis', 'State a hypothesis this passage suggests…'],
]

export default function PaperViewer({ paperKey, title, project, onClose, onMutate, embedded = false,
                                      onCite, citeTargetTitle }) {
  const [anchors, setAnchors] = useState({ citations: [], notes: [] })
  const [status, setStatus] = useState('loading')
  const [err, setErr] = useState('')
  const [popover, setPopover] = useState(null)
  const [draft, setDraft] = useState({ body: '', color: 'amber', kind: 'note' })
  const [openNote, setOpenNote] = useState(null)
  const [refs, setRefs] = useState([])               // parsed reference entries + status
  const [refPop, setRefPop] = useState(null)         // { x, y, nums, pinned }
  const [refDraft, setRefDraft] = useState(null)     // { id, comment } not-relevant form
  const [refErr, setRefErr] = useState('')

  const [scale, setScale] = useState(1.35)
  const [numPages, setNumPages] = useState(0)
  const [curPage, setCurPage] = useState(1)
  const [panel, setPanel] = useState(null)          // null | thumbnails | outline | search
  const [panelW, setPanelW] = useState(() => Number(localStorage.getItem('renv-pv-panel')) || 264)
  const [showSide, setShowSide] = useState(() => localStorage.getItem('renv-pv-side') !== 'off')
  const [sideW, setSideW] = useState(() => Number(localStorage.getItem('renv-pv-sidew')) || 300)
  const [outline, setOutline] = useState(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)       // [{ page, snippet }] | null

  const docScrollRef = useRef(null)                  // the scrolling .pv-doc
  const pagesRef = useRef([])                        // [{ page, pageEl, textLayerEl, hlEl }]
  const containerRef = useRef(null)                  // .pv-pages (imperative)
  const thumbsRef = useRef(null)                     // .pv-thumbs (imperative)
  const pdfRef = useRef(null)                        // the pdf document
  const pdfjsRef = useRef(null)                      // the pdfjs module
  const renderTok = useRef(0)
  const pendingRef = useRef(null)                    // { range, pg } of the span being annotated
  const anchorsRef = useRef(anchors)
  anchorsRef.current = anchors
  const refsRef = useRef(refs)
  refsRef.current = refs
  const refPopRef = useRef(null)                     // mirrors refPop for the mousemove loop
  refPopRef.current = refPop
  const refPopHover = useRef(false)                  // pointer is inside the popup
  const refBuiltOnce = useRef(false)
  const refCloseTimer = useRef(0)

  const loadAnchors = () =>
    getPaperAnchors(paperKey, project).then((a) =>
      setAnchors({ citations: a.citations || [], notes: a.notes || [] }))

  // parsed references; auto-build once for a paper opened for the first time
  const loadRefs = async () => {
    let r = await getPaperReferences(paperKey)
    if (!r?.error && !(r.references || []).length && !refBuiltOnce.current) {
      refBuiltOnce.current = true
      r = await buildPaperReferences(paperKey)       // no text / no refs → error is fine
    }
    if (!r?.error) setRefs(r.references || [])
  }

  // ---- reading position: page + in-page fraction + zoom, per paper ---------
  // Survives refreshes and tab switches. Page+fraction (not raw scrollTop) so
  // the position also survives a zoom or DPR change.
  const posKey = `renv-pv-pos-${paperKey}`
  const posTimer = useRef(0)
  const savePos = () => {
    clearTimeout(posTimer.current)
    posTimer.current = setTimeout(() => {
      const cont = docScrollRef.current, pgs = pagesRef.current
      if (!cont || !pgs.length) return
      const y = cont.scrollTop
      const a = [...pgs].reverse().find((p) => p.pageEl.offsetTop <= y + 1) || pgs[0]
      const frac = (y - a.pageEl.offsetTop) / (a.pageEl.offsetHeight || 1)
      localStorage.setItem(posKey, JSON.stringify(
        { page: a.page, frac: Math.max(0, frac), scale }))
    }, 250)
  }

  // ---- load the document once, then render its pages -----------------------
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        let saved = null
        try { saved = JSON.parse(localStorage.getItem(posKey)) } catch {}
        const startScale = saved?.scale && saved.scale >= 0.6 && saved.scale <= 3 ? saved.scale : 1.35
        if (startScale !== 1.35) setScale(startScale)
        const pdfjs = await import('pdfjs-dist')
        const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
        pdfjs.GlobalWorkerOptions.workerSrc =
          workerUrl + (workerUrl.includes('?') ? '&' : '?') + 'rev=1'
        const doc = await pdfjs.getDocument(paperPdfUrl(paperKey)).promise
        if (cancelled) return
        pdfjsRef.current = pdfjs
        pdfRef.current = doc
        setNumPages(doc.numPages)
        doc.getOutline().then((o) => !cancelled && setOutline(o || []))
        await renderPages(startScale)
        if (cancelled) return
        if (saved?.page) {                       // put the reader back where they were
          const pg = pagesRef.current[Math.min(saved.page, pagesRef.current.length) - 1]
          const cont = docScrollRef.current
          if (pg && cont) cont.scrollTop = pg.pageEl.offsetTop + (saved.frac || 0) * pg.pageEl.offsetHeight
        }
        setStatus('ready')
      } catch (e) {
        if (!cancelled) { setErr(String(e?.message || e)); setStatus('error') }
      }
    })()
    return () => { cancelled = true; clearTimeout(posTimer.current); try { pdfRef.current?.destroy() } catch {} }
  }, [paperKey])

  // zoom → resize in place, keeping the exact page + scroll position
  useEffect(() => {
    if (status === 'ready') { rescale(scale); savePos() }
  }, [scale])

  // trackpad pinch arrives as ctrl/⌘+wheel — zoom the PDF, never the whole page
  useEffect(() => {
    const el = docScrollRef.current
    if (!el) return
    let acc = 0
    const onWheel = (e) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      acc += e.deltaY
      if (Math.abs(acc) < 12) return
      const dir = acc > 0 ? -1 : 1
      acc = 0
      setScale((s) => Math.min(3, Math.max(0.6, Math.round((s + dir * 0.05) * 100) / 100)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const startPanelResize = (e) => {
    e.preventDefault()
    const x0 = e.clientX, w0 = panelW
    let w = w0
    const move = (ev) => { w = Math.min(520, Math.max(190, w0 + ev.clientX - x0)); setPanelW(w) }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      localStorage.setItem('renv-pv-panel', String(w))
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const startSideResize = (e) => {           // right sidebar: drag its left edge
    e.preventDefault()
    const x0 = e.clientX, w0 = sideW
    let w = w0
    const move = (ev) => { w = Math.min(520, Math.max(220, w0 - (ev.clientX - x0))); setSideW(w) }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      localStorage.setItem('renv-pv-sidew', String(w))
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  useEffect(() => { loadAnchors() }, [paperKey, project])
  useEffect(() => { refBuiltOnce.current = false; setRefs([]); setRefPop(null); loadRefs() }, [paperKey])
  useEffect(() => { if (status === 'ready') repaintHighlights() }, [anchors, refs, status])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { if (popover) closePopover(); else onClose() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [popover, onClose])

  async function renderPages(useScale) {
    const pdfjs = pdfjsRef.current, doc = pdfRef.current, container = containerRef.current
    if (!pdfjs || !doc || !container) return
    const tok = ++renderTok.current
    container.innerHTML = ''
    pagesRef.current = []
    const dpr = window.devicePixelRatio || 1
    for (let i = 1; i <= doc.numPages; i++) {
      const page = await doc.getPage(i)
      if (tok !== renderTok.current) return
      const viewport = page.getViewport({ scale: useScale })
      const pageEl = document.createElement('div')
      pageEl.className = 'pv-page'
      pageEl.style.width = `${viewport.width}px`
      pageEl.style.height = `${viewport.height}px`
      pageEl.dataset.page = i
      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(viewport.width * dpr)
      canvas.height = Math.floor(viewport.height * dpr)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      const ctx = canvas.getContext('2d')
      ctx.scale(dpr, dpr)
      const textLayerEl = document.createElement('div')
      textLayerEl.className = 'textLayer'
      textLayerEl.style.setProperty('--scale-factor', useScale)
      const hlEl = document.createElement('div')
      hlEl.className = 'pv-hl'
      pageEl.append(canvas, hlEl, textLayerEl)
      container.appendChild(pageEl)
      await page.render({ canvasContext: ctx, viewport }).promise
      if (tok !== renderTok.current) return
      const tl = new pdfjs.TextLayer({
        textContentSource: await page.getTextContent(), container: textLayerEl, viewport,
      })
      await tl.render()
      // keep the page object + unscaled size so zoom can resize in place (no teardown)
      pagesRef.current.push({
        page: i, pageEl, textLayerEl, hlEl, canvas, pdfPage: page,
        w: viewport.width / useScale, h: viewport.height / useScale,
      })
    }
  }

  // Smooth zoom. Synchronously (this frame): resize page boxes, STRETCH the
  // existing canvas bitmap to the new size for an instant preview, and rescale
  // the text layer via its --scale-factor CSS var (no rebuild — PDF.js positions
  // it with calc(var(--scale-factor)*…)). Restore scroll + repaint highlights on
  // the settled layout. Then, in the background, re-render crisp canvases nearest
  // the viewport first, each rendered offscreen and swapped in (no blank flash).
  async function rescale(newScale) {
    const cont = docScrollRef.current, pgs = pagesRef.current
    if (!cont || !pgs.length) return
    const y = cont.scrollTop
    const a = [...pgs].reverse().find((p) => p.pageEl.offsetTop <= y + 1) || pgs[0]
    const frac = (y - a.pageEl.offsetTop) / (a.pageEl.offsetHeight || 1)
    for (const pg of pgs) {
      const w = pg.w * newScale, h = pg.h * newScale
      pg.pageEl.style.width = `${w}px`
      pg.pageEl.style.height = `${h}px`
      pg.canvas.style.width = `${w}px`          // stretch old bitmap → instant scaled preview
      pg.canvas.style.height = `${h}px`
      pg.textLayerEl.style.setProperty('--scale-factor', newScale)   // text rescales via CSS
    }
    cont.scrollTop = a.pageEl.offsetTop + frac * a.pageEl.offsetHeight
    repaintHighlights()

    const tok = ++renderTok.current
    const dpr = window.devicePixelRatio || 1
    const mid = cont.scrollTop + cont.clientHeight / 2
    const order = [...pgs].sort((p, q) =>
      Math.abs(p.pageEl.offsetTop + p.pageEl.offsetHeight / 2 - mid) -
      Math.abs(q.pageEl.offsetTop + q.pageEl.offsetHeight / 2 - mid))
    for (const pg of order) {
      if (tok !== renderTok.current) return
      const vp = pg.pdfPage.getViewport({ scale: newScale })
      const nc = document.createElement('canvas')
      nc.width = Math.floor(vp.width * dpr)
      nc.height = Math.floor(vp.height * dpr)
      nc.style.width = `${vp.width}px`
      nc.style.height = `${vp.height}px`
      const ctx = nc.getContext('2d')
      ctx.scale(dpr, dpr)
      await pg.pdfPage.render({ canvasContext: ctx, viewport: vp }).promise
      if (tok !== renderTok.current) return
      pg.canvas.replaceWith(nc)                  // swap crisp bitmap in, no blank
      pg.canvas = nc
    }
  }

  function repaintHighlights() {
    const { citations, notes } = anchorsRef.current
    const byNum = new Map(refsRef.current.map((r) => [r.num, r]))
    for (const pg of pagesRef.current) {
      pg.hlEl.querySelectorAll('.pv-mark-cite, .pv-mark-note, .pv-ref').forEach((el) => el.remove())
      for (const c of citations) {
        if (c.page && c.page !== pg.page) continue
        const r = findRange(pg.textLayerEl, c.quote, { prefix: c.prefix })
        if (r) paintRects(r, pg.hlEl, pg.pageEl, 'pv-mark pv-mark-cite', { kind: 'cite', id: `${c.id}` })
      }
      for (const n of notes) {
        if (n.page && n.page !== pg.page) continue
        const r = findRange(pg.textLayerEl, n.quote, { prefix: n.prefix })
        if (r) paintRects(r, pg.hlEl, pg.pageEl, `pv-mark pv-mark-note pv-c-${n.color}`, { kind: 'note', id: `${n.id}` })
      }
      if (byNum.size) {
        for (const mk of findRefMarkers(pg.textLayerEl, new Set(byNum.keys()))) {
          const st = worstRefStatus(mk.nums.map((n) => byNum.get(n).status))
          paintRects(mk.range, pg.hlEl, pg.pageEl, `pv-ref pv-ref-${st}`,
                     { kind: 'ref', nums: mk.nums.join(',') })
        }
      }
    }
  }

  // ---- reference markers: hover popup (Google-Scholar style) ---------------
  // The highlight layer is pointer-events:none, so hover is a manual rAF
  // hit-test against the painted ref boxes; the popup holds itself open while
  // the pointer is inside it (refPopHover).
  const refMoveTick = useRef(0)
  const onDocMouseMove = (e) => {
    if (refMoveTick.current) return
    const x = e.clientX, y = e.clientY
    refMoveTick.current = requestAnimationFrame(() => {
      refMoveTick.current = 0
      if (refPopRef.current?.pinned || refPopHover.current) return
      const pageEl = document.elementFromPoint(x, y)?.closest?.('.pv-page')
      const pg = pageEl && pagesRef.current.find((p) => p.pageEl === pageEl)
      let hit = null
      if (pg) {
        for (const m of pg.hlEl.children) {
          if (m.dataset.kind !== 'ref') continue
          const r = m.getBoundingClientRect()
          if (x >= r.left - 2 && x <= r.right + 2 && y >= r.top - 2 && y <= r.bottom + 2) { hit = { m, r }; break }
        }
      }
      if (hit) {
        clearTimeout(refCloseTimer.current)
        const nums = hit.m.dataset.nums.split(',').map(Number)
        const cur = refPopRef.current
        if (!cur || cur.nums.join(',') !== nums.join(',')) {
          setRefPop({ x: hit.r.left, y: hit.r.bottom + 6, nums, pinned: false })
          setRefDraft(null); setRefErr('')
        }
      } else if (refPopRef.current) {
        clearTimeout(refCloseTimer.current)
        refCloseTimer.current = setTimeout(() => {
          if (!refPopHover.current && !refPopRef.current?.pinned) setRefPop(null)
        }, 260)
      }
    })
  }
  const closeRefPop = () => { setRefPop(null); setRefDraft(null); setRefErr('') }

  const doAddRef = async (entry) => {
    setRefErr('')
    const r = await addReference(entry.id)
    if (r?.error) { setRefErr(r.error); return }
    await loadRefs()
    onMutate && onMutate()
  }
  const doMarkRef = async (entry, comment) => {
    setRefErr('')
    const r = await markReference(entry.id, 'not_relevant', comment)
    if (r?.error) { setRefErr(r.error); return }
    setRefDraft(null)
    await loadRefs()
  }
  const doClearRef = async (entry) => {
    const r = await markReference(entry.id, null)
    if (!r?.error) await loadRefs()
  }

  const clearPending = () => {
    pendingRef.current = null
    for (const pg of pagesRef.current) pg.hlEl.querySelectorAll('.pv-mark-pending').forEach((el) => el.remove())
  }
  const closePopover = () => { clearPending(); setPopover(null); window.getSelection()?.removeAllRanges() }

  // keep the selected span lit in the currently-chosen colour while the popover
  // is open, so you can see exactly what you're annotating
  useEffect(() => {
    const p = pendingRef.current
    if (!popover || !p) return
    p.pg.hlEl.querySelectorAll('.pv-mark-pending').forEach((el) => el.remove())
    paintRects(p.range, p.pg.hlEl, p.pg.pageEl, `pv-mark pv-mark-pending pv-c-${draft.color}`)
  }, [draft.color, popover])

  // ---- selecting text: open the add popover, keep the span visibly marked ---
  const onMouseUp = () => {
    const s = window.getSelection()
    if (!s || s.isCollapsed) return
    const pg = pagesRef.current.find((p) => p.textLayerEl.contains(s.anchorNode))
    if (!pg) return
    const a = selectionAnchor(pg.textLayerEl, pg.pageEl)
    if (!a) return
    const range = s.getRangeAt(0).cloneRange()
    clearPending()
    pendingRef.current = { range, pg }
    paintRects(range, pg.hlEl, pg.pageEl, 'pv-mark pv-mark-pending pv-c-amber')
    setPopover({ ...a, page: pg.page })
    setDraft({ body: '', color: 'amber', kind: 'note' })
  }

  const onDocClick = (e) => {
    const s = window.getSelection()
    if (s && !s.isCollapsed) return
    // the highlight layer is pointer-events:none (so it never blocks selection),
    // which means elementsFromPoint won't return the marks — hit-test manually
    // against the marks on the page under the click.
    const x = e.clientX, y = e.clientY
    const pageEl = document.elementFromPoint(x, y)?.closest?.('.pv-page')
    const pg = pageEl && pagesRef.current.find((p) => p.pageEl === pageEl)
    if (!pg) return
    let hit = null
    for (const m of pg.hlEl.children) {
      if (m.classList.contains('pv-mark-pending')) continue
      const r = m.getBoundingClientRect()
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) { hit = m; break }
    }
    if (!hit) { if (refPopRef.current?.pinned) closeRefPop(); return }
    const kind = hit.dataset.kind, id = hit.dataset.id
    if (kind === 'ref') {                            // click pins the hover popup
      const r = hit.getBoundingClientRect()
      setRefPop({ x: r.left, y: r.bottom + 6, nums: hit.dataset.nums.split(',').map(Number), pinned: true })
      setRefDraft(null); setRefErr('')
      return
    }
    if (!showSide) { setShowSide(true); localStorage.setItem('renv-pv-side', 'on') }  // reveal it
    if (kind === 'note') setOpenNote(Number(id))
    setTimeout(() => focusSidebar(kind === 'note' ? `note-${id}` : `cite-${id}`), 90)
  }

  // Scroll ONLY the intended container — scrollIntoView() walks up and scrolls
  // every scrollable ancestor (including the overflow:hidden app shell), which
  // is what was dragging the sidebar and topbar up.
  const scrollDocTo = (el, center) => {
    const cont = docScrollRef.current
    if (!cont || !el) return
    const cr = cont.getBoundingClientRect(), er = el.getBoundingClientRect()
    let top = cont.scrollTop + (er.top - cr.top)
    top -= center ? (cont.clientHeight - er.height) / 2 : 10
    cont.scrollTo({ top, behavior: 'smooth' })
  }
  const focusSidebar = (id) => {
    const el = document.getElementById(`pv-side-${id}`)
    if (!el) return
    const side = el.closest('.pv-side')
    if (side) { const cr = side.getBoundingClientRect(), er = el.getBoundingClientRect(); side.scrollTop += (er.top - cr.top) - 12 }
    el.classList.add('pv-flash'); setTimeout(() => el.classList.remove('pv-flash'), 1200)
  }
  const jumpToMark = (kind, id) => {
    for (const pg of pagesRef.current) {
      const mark = pg.hlEl.querySelector(`.pv-mark[data-kind="${kind}"][data-id="${id}"]`)
      if (mark) {
        scrollDocTo(mark, true)
        mark.classList.add('pv-mark-flash'); setTimeout(() => mark.classList.remove('pv-mark-flash'), 1400)
        return
      }
    }
  }

  // ---- toolbar: page nav + scroll spy + zoom -------------------------------
  const goToPage = (n) => {
    const pg = pagesRef.current[Math.max(0, Math.min(n, numPages) - 1)]
    if (pg) scrollDocTo(pg.pageEl, false)
  }
  const spyTick = useRef(0)
  const onDocScroll = () => {
    savePos()
    if (spyTick.current) return
    spyTick.current = requestAnimationFrame(() => {
      spyTick.current = 0
      const cont = docScrollRef.current
      if (!cont) return
      const y = cont.scrollTop + cont.clientHeight * 0.3
      let cur = 1
      for (const pg of pagesRef.current) { if (pg.pageEl.offsetTop <= y) cur = pg.page; else break }
      setCurPage(cur)
    })
  }
  const zoom = (d) => setScale((s) => Math.min(3, Math.max(0.6, Math.round((s + d) * 100) / 100)))

  // ---- thumbnails (rendered lazily into a dedicated ref) -------------------
  useEffect(() => {
    if (panel !== 'thumbnails' || status !== 'ready' || !thumbsRef.current) return
    let cancelled = false
    ;(async () => {
      const doc = pdfRef.current, host = thumbsRef.current
      host.innerHTML = ''
      for (let i = 1; i <= doc.numPages; i++) {
        const page = await doc.getPage(i)
        if (cancelled) return
        const vp = page.getViewport({ scale: 1 })
        const s = 150 / vp.width
        const v = page.getViewport({ scale: s })
        const cv = document.createElement('canvas')
        cv.width = v.width; cv.height = v.height
        const cell = document.createElement('button')
        cell.className = 'pv-thumb'
        cell.onclick = () => goToPage(i)
        const num = document.createElement('span'); num.className = 'pv-thumb-n'; num.textContent = i
        cell.append(cv, num)
        host.appendChild(cell)
        await page.render({ canvasContext: cv.getContext('2d'), viewport: v }).promise
      }
    })()
    return () => { cancelled = true }
  }, [panel, status])

  const openOutline = async (item) => {
    const doc = pdfRef.current
    try {
      const dest = typeof item.dest === 'string' ? await doc.getDestination(item.dest) : item.dest
      if (dest && dest[0]) goToPage((await doc.getPageIndex(dest[0])) + 1)
    } catch {}
  }

  const runSearch = (qv = query) => {
    const q = qv.trim()
    if (q.length < 2) { setResults(q ? [] : null); return }
    const found = []
    for (const pg of pagesRef.current) {
      findAllRanges(pg.textLayerEl, q).forEach((m, idx) => found.push({ page: pg.page, idx, snippet: m.snippet }))
    }
    setResults(found)
  }
  // click a result → scroll to that exact occurrence and keep it lit for 5s
  const jumpToSearch = (r) => {
    const pg = pagesRef.current[r.page - 1]
    if (!pg) return
    const m = findAllRanges(pg.textLayerEl, query.trim())[r.idx]
    if (!m) { goToPage(r.page); return }
    const made = paintRects(m.range, pg.hlEl, pg.pageEl, 'pv-mark pv-mark-search')
    scrollDocTo(made[0], true)
    setTimeout(() => made.forEach((el) => el.remove()), 5000)
  }

  const saveNote = async () => {
    const r = await addPaperNote({
      key: paperKey, project, quote: popover.quote, prefix: popover.prefix,
      suffix: popover.suffix, page: popover.page, body: draft.body, color: draft.color, kind: draft.kind,
    })
    if (r && r.error) { setErr(r.error); return }
    closePopover()
    await loadAnchors()
    onMutate && onMutate()
  }
  const saveNoteEdit = async (n, fields) => { await updatePaperNote(n.id, fields); await loadAnchors(); onMutate && onMutate() }
  const removeNote = async (n) => { await deletePaperNote(n.id); setOpenNote(null); await loadAnchors(); onMutate && onMutate() }

  const TABS = ['thumbnails', 'outline', 'search']
  const inner = (
    <>
      <div className="pv-bar">
        <div className="pv-tools">
          <button className={`pv-tbtn ${panel ? 'on' : ''}`} title="Thumbnails / outline / search"
                  onClick={() => setPanel(panel ? null : 'thumbnails')}><PanelIco side="left" /></button>
        </div>
        <div className="pv-centertools">
          <span className="pv-zoom">
            <button className="pv-tbtn" title="Zoom out" onClick={() => zoom(-0.1)}>−</button>
            <span className="pv-zoom-n">{Math.round(scale * 100)}%</span>
            <button className="pv-tbtn" title="Zoom in" onClick={() => zoom(0.1)}>＋</button>
          </span>
          <span className="pv-pagenav">
            <button className="pv-tbtn" title="Previous page" disabled={curPage <= 1} onClick={() => goToPage(curPage - 1)}>‹</button>
            <input className="pv-pageinput" value={curPage}
                   onChange={(e) => { const n = parseInt(e.target.value, 10); if (n) setCurPage(n) }}
                   onKeyDown={(e) => { if (e.key === 'Enter') goToPage(curPage) }} />
            <span className="faint">of {numPages || '…'}</span>
            <button className="pv-tbtn" title="Next page" disabled={curPage >= numPages} onClick={() => goToPage(curPage + 1)}>›</button>
          </span>
        </div>
        <div className="pv-bar-meta">
          <span className="pv-count-txt">
            {anchors.citations.length} citations · {anchors.notes.length} notes
            {refs.length > 0 && ` · ${refs.filter((r) => r.status === 'unknown').length} refs missing`}
          </span>
          <button className={`pv-tbtn ${showSide ? 'on' : ''}`} title="Toggle annotations panel"
                  onClick={() => { const v = !showSide; setShowSide(v); localStorage.setItem('renv-pv-side', v ? 'on' : 'off') }}>
            <PanelIco side="right" />
          </button>
          {!embedded && <button className="pv-x" onClick={onClose} title="Close (Esc)">✕</button>}
        </div>
      </div>

      <div className="pv-body">
        {panel && (
          <aside className="pv-panel" style={{ width: panelW }}>
            <div className="pv-panel-resize" onMouseDown={startPanelResize} title="Drag to resize" />
            <div className="pv-panel-tabs">
              {TABS.map((t) => (
                <button key={t} className={`pv-ptab ${panel === t ? 'on' : ''}`} onClick={() => setPanel(t)}>
                  {t[0].toUpperCase() + t.slice(1)}
                </button>
              ))}
              <button className="pv-ptab pv-ptab-x" title="Close panel" onClick={() => setPanel(null)}>✕</button>
            </div>
            <div className="pv-panel-divider" />
            {panel === 'thumbnails' && <div className="pv-thumbs" ref={thumbsRef} />}
            {panel === 'outline' && (
              <div className="pv-outline">
                {outline === null && <div className="pv-empty">reading…</div>}
                {outline && !outline.length && <div className="pv-empty">This PDF has no embedded outline.</div>}
                {(outline || []).map((it, i) => (
                  <button key={i} className="pv-oitem" onClick={() => openOutline(it)}>{it.title}</button>
                ))}
              </div>
            )}
            {panel === 'search' && (
              <div className="pv-search">
                <input className="pv-searchinput" autoFocus placeholder="Search this document…"
                       value={query} onChange={(e) => { setQuery(e.target.value); runSearch(e.target.value) }}
                       onKeyDown={(e) => { if (e.key === 'Enter') runSearch() }} />
                {results && <div className="pv-search-n">{results.length} match{results.length === 1 ? '' : 'es'}</div>}
                {(results || []).map((r, i) => (
                  <button key={i} className="pv-sresult" onClick={() => jumpToSearch(r)}>
                    <span className="faint num">p{r.page}</span>
                    <span className="pv-sr-snip">…{r.snippet}…</span>
                  </button>
                ))}
              </div>
            )}
          </aside>
        )}

        <div className="pv-doc" ref={docScrollRef} onScroll={onDocScroll} onMouseUp={onMouseUp}
             onClick={onDocClick} onMouseMove={onDocMouseMove}>
          <div className="pv-pages" ref={containerRef} />
          {status === 'loading' && <div className="loading pv-center">rendering the PDF…</div>}
          {status === 'error' && (
            <div className="pv-center muted" style={{ padding: 40, textAlign: 'center' }}>
              Could not render this PDF.<br /><span className="mono" style={{ fontSize: 12 }}>{err}</span>
            </div>
          )}
        </div>

        {showSide && (
        <aside className="pv-side" style={{ width: sideW }}>
          <div className="pv-side-resize" onMouseDown={startSideResize} title="Drag to resize" />
          <div className="pv-side-h">Annotations<span className="faint"> · select text to add</span></div>
          {!anchors.notes.length && <div className="pv-empty">Nothing yet. Highlight a passage in the PDF to anchor a note, question, or hypothesis.</div>}
          {anchors.notes.map((n) => (
            <div key={n.id} id={`pv-side-note-${n.id}`}
                 className={`pv-note pv-c-${n.color} ${openNote === n.id ? 'open' : ''}`}>
              <div className="pv-note-head" onClick={() => { setOpenNote(openNote === n.id ? null : n.id); jumpToMark('note', n.id) }}>
                <span className="pv-dot" />
                {(n.kind && n.kind !== 'note') && <span className={`pv-kindtag pv-kt-${n.kind}`}>{n.kind}</span>}
                <span className="pv-note-quote">“{(n.quote || '').slice(0, 60)}{(n.quote || '').length > 60 ? '…' : ''}”</span>
                {n.page && <span className="faint num">p{n.page}</span>}
              </div>
              {openNote === n.id && (
                <div className="pv-note-body">
                  <textarea className="inline-edit" defaultValue={n.body_md} placeholder="Your note…"
                            onBlur={(e) => e.target.value !== n.body_md && saveNoteEdit(n, { body_md: e.target.value })} />
                  <div className="pv-note-tools">
                    <div className="pv-swatches">
                      {NOTE_COLORS.map((c) => (
                        <button key={c} className={`pv-sw pv-c-${c} ${n.color === c ? 'on' : ''}`}
                                title={c} onClick={() => saveNoteEdit(n, { color: c })} />
                      ))}
                    </div>
                    <button className="pv-del" title="Delete annotation" onClick={() => removeNote(n)}>
                      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
                           strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 6h18" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        <line x1="10" x2="10" y1="11" y2="17" /><line x1="14" x2="14" y1="11" y2="17" />
                      </svg>
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          <div className="pv-side-h" style={{ marginTop: 14 }}>Citations</div>
          {!anchors.citations.length && <div className="pv-empty">This paper isn’t cited in {project} yet.</div>}
          {anchors.citations.map((c) => (
            <div key={c.id} id={`pv-side-cite-${c.id}`} className="pv-cite" onClick={() => jumpToMark('cite', c.id)}>
              <div className="pv-cite-quote">“{(c.quote || '').slice(0, 90)}{(c.quote || '').length > 90 ? '…' : ''}”</div>
              {c.claim_text && <div className="pv-cite-claim">→ {c.claim_text}</div>}
            </div>
          ))}

          <div className="pv-side-h" style={{ marginTop: 14 }}>
            References
            {refs.length > 0 && (
              <span className="faint"> · {refs.filter((r) => r.status === 'library').length}/{refs.length} in library</span>
            )}
          </div>
          {!refs.length && <div className="pv-empty">No numeric reference list parsed for this paper.</div>}
          {refs.map((r) => (
            <RefRow key={r.id} r={r} compact draft={refDraft} setDraft={setRefDraft}
                    onAdd={doAddRef} onDismiss={doMarkRef} onClear={doClearRef} />
          ))}
          {refErr && <div className="pv-referr">{refErr}</div>}
        </aside>
        )}
      </div>

      {popover && (
        <div className="pv-pop" style={{ left: popover.clientX, top: popover.clientY + 8 }}
             onMouseDown={(e) => e.stopPropagation()}>
          <div className="pv-kindsel">
            {KINDS.map(([k, label]) => (
              <button key={k} className={`pv-kind ${draft.kind === k ? 'on' : ''}`}
                      onClick={() => setDraft({ ...draft, kind: k })}>{label}</button>
            ))}
          </div>
          <div className="pv-pop-quote">“{popover.quote.slice(0, 80)}{popover.quote.length > 80 ? '…' : ''}”</div>
          <textarea className="inline-edit" autoFocus
                    placeholder={(KINDS.find(([k]) => k === draft.kind) || KINDS[0])[2]}
                    value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                    onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) saveNote() }} />
          <div className="pv-pop-tools">
            <div className="pv-swatches">
              {NOTE_COLORS.map((c) => (
                <button key={c} className={`pv-sw pv-c-${c} ${draft.color === c ? 'on' : ''}`}
                        title={c} onClick={() => setDraft({ ...draft, color: c })} />
              ))}
            </div>
            <button className="btn ghost" onClick={closePopover}>Cancel</button>
            <button className="btn" onClick={saveNote}>Add {(KINDS.find(([k]) => k === draft.kind) || KINDS[0])[1].toLowerCase()}</button>
          </div>
          {onCite && citeTargetTitle && (
            <button className="pv-cite-into"
                    onClick={() => { onCite({ quote: popover.quote, page: popover.page }); closePopover() }}>
              ↳ Cite this passage into “{citeTargetTitle}”
            </button>
          )}
        </div>
      )}

      {refPop && (
        <div className="pv-refpop"
             style={{ left: Math.max(8, Math.min(refPop.x, window.innerWidth - 400)),
                      top: Math.min(refPop.y, window.innerHeight - 220) }}
             onMouseEnter={() => { refPopHover.current = true; clearTimeout(refCloseTimer.current) }}
             onMouseLeave={() => { refPopHover.current = false; if (!refPop.pinned) setRefPop(null) }}
             onMouseDown={(e) => e.stopPropagation()}>
          {refPop.pinned && (
            <button className="pv-x pv-refpop-x" title="Close" onClick={closeRefPop}>✕</button>
          )}
          {refPop.nums.map((n) => {
            const r = refs.find((e) => e.num === n)
            return r ? (
              <RefRow key={r.id} r={r} draft={refDraft} setDraft={setRefDraft}
                      onAdd={doAddRef} onDismiss={doMarkRef} onClear={doClearRef} />
            ) : null
          })}
          {refErr && <div className="pv-referr">{refErr}</div>}
        </div>
      )}
    </>
  )

  if (embedded) return <div className="pv-embed">{inner}</div>
  return (
    <div className="pv-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="pv-modal">{inner}</div>
    </div>
  )
}
