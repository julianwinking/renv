// Compiled manuscript preview: PDF.js pages, numbered citation hover cards,
// and Overleaf-style SyncTeX (double-click a spot → editor; gutter arrow → here).
import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { writePdfUrl } from '../api.js'
import { navigate, routePath } from '../nav.js'
import {
  findRange, findRefMarkers, findSpanCiteMarkers, paintRects,
  parseCiteHref, snippetAtPoint,
} from '../pdfhl.js'
import { Stamp } from '../ui.jsx'

function lookupCite(rows, sourceId, start) {
  const list = rows || []
  return list.find((c) => c.source_id === sourceId && (start == null || c.src_start === start))
    || list.find((c) => c.source_id === sourceId)
}

function keyForNum(citeNumbers, n) {
  for (const [k, v] of Object.entries(citeNumbers || {})) {
    if (v === n) return k
  }
  return null
}

function annotUrl(a) {
  return a.url || a.unsafeUrl || a.action?.uri || a.annotation?.url || ''
}

export default forwardRef(function ManuscriptPdf({
  slug, bust, hasPdf, citations, citeNumbers, onMarker, onSyncPdf,
  status, log, errors, engine, onWeave, onCompile,
}, ref) {
  const [ready, setReady] = useState(false)
  const [err, setErr] = useState('')
  const [scale, setScale] = useState(1.15)
  const [logOpen, setLogOpen] = useState(false)
  const [citePop, setCitePop] = useState(null)
  const docScrollRef = useRef(null)
  const containerRef = useRef(null)
  const bodyRef = useRef(null)
  const pagesRef = useRef([])
  const pdfRef = useRef(null)
  const pdfjsRef = useRef(null)
  const renderTok = useRef(0)
  const scaleRef = useRef(scale)
  scaleRef.current = scale
  const citesRef = useRef(citations)
  citesRef.current = citations
  const numsRef = useRef(citeNumbers)
  numsRef.current = citeNumbers || {}
  const onMarkerRef = useRef(onMarker)
  onMarkerRef.current = onMarker
  const onSyncPdfRef = useRef(onSyncPdf)
  onSyncPdfRef.current = onSyncPdf
  const hidePop = useRef(0)

  useImperativeHandle(ref, () => ({
    showLine({ page, x, y, text } = {}) {
      const pages = pagesRef.current
      if (!pages.length) return
      pages.forEach((p) => {
        p.hlEl.querySelectorAll('.pv-mark-sync, .pv-mark-flash').forEach((el) => el.remove())
      })
      const sc = scaleRef.current
      if (page && Number.isFinite(x) && Number.isFinite(y)) {
        const rec = pages.find((p) => p.page === page) || pages[0]
        const el = document.createElement('div')
        el.className = 'pv-mark pv-mark-sync'
        el.style.left = `${x * sc - 10}px`
        el.style.top = `${y * sc - 10}px`
        el.style.width = '20px'
        el.style.height = '20px'
        rec.hlEl.appendChild(el)
        rec.pageEl.scrollIntoView({ block: 'center', inline: 'nearest' })
        setTimeout(() => el.remove(), 1400)
        return
      }
      if (text) {
        for (const rec of pages) {
          const range = findRange(rec.textLayerEl, text)
          if (!range) continue
          const els = paintRects(range, rec.hlEl, rec.pageEl, 'pv-mark pv-mark-search pv-mark-flash')
          rec.pageEl.scrollIntoView({ block: 'center', inline: 'nearest' })
          setTimeout(() => els.forEach((e) => e.remove()), 1400)
          return
        }
      }
    },
  }))

  useEffect(() => {
    let cancelled = false
    setReady(false); setErr(''); setCitePop(null)
    if (!hasPdf) return undefined
    ;(async () => {
      try {
        const pdfjs = await import('pdfjs-dist')
        const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
        pdfjs.GlobalWorkerOptions.workerSrc =
          workerUrl + (workerUrl.includes('?') ? '&' : '?') + 'rev=1'
        const doc = await pdfjs.getDocument(writePdfUrl(slug, bust)).promise
        if (cancelled) { doc.destroy(); return }
        pdfjsRef.current = pdfjs
        pdfRef.current = doc
        await renderPages(1.15)
        if (!cancelled) setReady(true)
      } catch (e) {
        if (!cancelled) setErr(String(e?.message || e))
      }
    })()
    return () => { cancelled = true; try { pdfRef.current?.destroy() } catch {} }
  }, [slug, bust, hasPdf]) // eslint-disable-line

  useEffect(() => { if (ready) renderPages(scale) }, [scale]) // eslint-disable-line
  useEffect(() => { if (ready) paintMarkers() }, [citations, citeNumbers, ready])

  async function renderPages(useScale) {
    const pdfjs = pdfjsRef.current, doc = pdfRef.current, container = containerRef.current
    if (!pdfjs || !doc || !container) return
    const tok = ++renderTok.current
    container.innerHTML = ''
    pagesRef.current = []
    const dpr = window.devicePixelRatio || 1
    for (let n = 1; n <= doc.numPages; n++) {
      if (tok !== renderTok.current) return
      const page = await doc.getPage(n)
      const vp = page.getViewport({ scale: useScale })
      const pageEl = document.createElement('div')
      pageEl.className = 'pv-page'
      pageEl.style.width = vp.width + 'px'
      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(vp.width * dpr)
      canvas.height = Math.floor(vp.height * dpr)
      canvas.style.width = vp.width + 'px'
      canvas.style.height = vp.height + 'px'
      const ctx = canvas.getContext('2d')
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const textLayerEl = document.createElement('div')
      textLayerEl.className = 'textLayer'
      textLayerEl.style.setProperty('--scale-factor', useScale)
      textLayerEl.style.width = vp.width + 'px'
      textLayerEl.style.height = vp.height + 'px'
      const hlEl = document.createElement('div')
      hlEl.className = 'pv-hl'
      pageEl.append(canvas, textLayerEl, hlEl)
      container.appendChild(pageEl)
      await page.render({ canvasContext: ctx, viewport: vp }).promise
      const textContent = await page.getTextContent()
      const tl = new pdfjs.TextLayer({
        textContentSource: textContent, container: textLayerEl, viewport: vp,
      })
      tl.render()
      pageEl.addEventListener('dblclick', (e) => {
        const r = pageEl.getBoundingClientRect()
        const sc = scaleRef.current
        onSyncPdfRef.current?.({
          page: n,
          x: (e.clientX - r.left) / sc,
          y: (e.clientY - r.top) / sc,
          snippet: snippetAtPoint(textLayerEl, e.clientX, e.clientY),
        })
      })
      pagesRef.current.push({ page: n, pageEl, textLayerEl, hlEl, viewport: vp })
    }
    paintMarkers()
  }

  function bindMark(el, payload) {
    el.style.pointerEvents = 'auto'
    el.style.cursor = 'pointer'
    el.title = payload.quote
      ? `[${payload.num || '?'}] ${payload.source_id}`
      : (payload.source_id || '')
    const open = () => {
      clearTimeout(hidePop.current)
      const body = bodyRef.current
      if (!body) { setCitePop(payload); return }
      const br = body.getBoundingClientRect()
      const er = el.getBoundingClientRect()
      setCitePop({
        ...payload,
        x: Math.max(8, er.left - br.left + body.scrollLeft),
        y: er.bottom - br.top + body.scrollTop + 6,
      })
    }
    el.addEventListener('mouseenter', open)
    el.addEventListener('mouseleave', () => {
      hidePop.current = setTimeout(() => setCitePop(null), 180)
    })
    el.addEventListener('click', (e) => {
      e.stopPropagation()
      open()
      onMarkerRef.current?.(payload)
    })
  }

  function payloadFor(sourceId, start, end, num) {
    const hit = lookupCite(citesRef.current, sourceId, start)
    const numbers = numsRef.current || {}
    return {
      source_id: sourceId,
      start: start ?? hit?.src_start,
      end: end ?? hit?.src_end,
      num: num ?? numbers[sourceId],
      quote: hit?.quote,
      support: hit?.support,
      citation: hit,
    }
  }

  async function paintMarkers() {
    const doc = pdfRef.current
    if (!doc) return
    for (const p of pagesRef.current) {
      p.hlEl.innerHTML = ''
      let linked = 0
      try {
        const page = await doc.getPage(p.page)
        const annots = await page.getAnnotations()
        const vp = p.viewport || page.getViewport({ scale: scaleRef.current })
        for (const a of annots) {
          const parsed = parseCiteHref(annotUrl(a))
          if (!parsed || !a.rect) continue
          const [x1, y1, x2, y2] = a.rect
          const a1 = vp.convertToViewportPoint(x1, y1)
          const a2 = vp.convertToViewportPoint(x2, y2)
          const left = Math.min(a1[0], a2[0])
          const top = Math.min(a1[1], a2[1])
          const w = Math.abs(a2[0] - a1[0])
          const h = Math.abs(a2[1] - a1[1])
          if (w < 1 || h < 1) continue
          const el = document.createElement('div')
          el.className = 'pv-mark pv-mark-cite'
          el.style.left = `${left}px`
          el.style.top = `${top}px`
          el.style.width = `${w}px`
          el.style.height = `${h}px`
          p.hlEl.appendChild(el)
          bindMark(el, payloadFor(parsed.source_id, parsed.start, parsed.end))
          linked++
        }
      } catch { /* annotation layer is optional */ }
      if (linked) continue
      for (const m of findSpanCiteMarkers(p.textLayerEl)) {
        const payload = payloadFor(m.source_id, m.start, m.end)
        const els = paintRects(m.range, p.hlEl, p.pageEl, 'pv-mark pv-mark-cite', {
          source: m.source_id, start: String(m.start), end: String(m.end),
        })
        els.forEach((el) => bindMark(el, payload))
      }
      const valid = new Set(Object.values(numsRef.current || {}))
      if (!valid.size) continue
      for (const m of findRefMarkers(p.textLayerEl, valid)) {
        const n = m.nums[0]
        const key = keyForNum(numsRef.current, n)
        if (!key) continue
        const payload = payloadFor(key, undefined, undefined, n)
        const els = paintRects(m.range, p.hlEl, p.pageEl, 'pv-mark pv-mark-cite', {
          source: key, num: String(n),
        })
        els.forEach((el) => bindMark(el, payload))
      }
    }
  }

  const compiling = status === 'running'
  const failed = status === 'error'
  const noPdf = status === 'no-engine' || status === 'missing'

  return (
    <div className="tx-pdf">
      <div className="tx-chrome">
        <span className="tx-title">PDF</span>
        <div className="tx-chrome-actions">
          {onWeave && (
            <button className="tx-tool ghost" onClick={onWeave}
                    title="Regenerate results_table.tex and references.bib from the store">Weave</button>
          )}
          {onCompile && (
            <button className="tx-tool primary" onClick={onCompile} disabled={compiling}
                    title="⌘/Ctrl+Enter — weave, then compile">
              {compiling ? 'Compiling…' : 'Recompile'}
            </button>
          )}
          {ready && (
            <span className="pv-zoom" title={engine || undefined}>
              <button className="pv-tbtn" onClick={() => setScale((s) => Math.max(0.6, s - 0.1))}>−</button>
              <span className="pv-zoom-n">{Math.round(scale * 100)}%</span>
              <button className="pv-tbtn" onClick={() => setScale((s) => Math.min(2.4, s + 0.1))}>+</button>
            </span>
          )}
          <button className={`tx-tool ghost ${logOpen ? 'on' : ''}`} onClick={() => setLogOpen((v) => !v)}>Log</button>
        </div>
      </div>
      <div className="tx-pdf-body" ref={bodyRef}>
        {compiling && <div className="tx-pdf-msg">Compiling…</div>}
        {noPdf && !compiling && (
          <div className="tx-pdf-msg">
            <b>No PDF yet.</b>
            <p className="muted">
              {status === 'no-engine'
                ? 'No LaTeX engine on PATH (latexmk, tectonic, or pdflatex). The editor, weave, and \\spancite still work — install TeX Live or tectonic to preview.'
                : `Click Recompile to weave numbers from the store and build the PDF.${engine ? ` Engine: ${engine}.` : ''}`}
            </p>
            <p className="muted">Double-click text in the PDF to jump to the source line. The editor gutter arrow jumps the other way.</p>
          </div>
        )}
        {failed && !compiling && (
          <div className="tx-pdf-msg">
            <b>Compile failed.</b>
            {(errors || []).slice(0, 6).map((e, i) => <div key={i} className="mono" style={{ color: 'var(--bad)', fontSize: 11.5 }}>{e}</div>)}
            <p className="muted">Open the log for the full TeX output.</p>
          </div>
        )}
        {err && ready === false && status !== 'running' && status !== 'no-engine' && status !== 'missing' && (
          <div className="tx-pdf-msg muted">{err}</div>
        )}
        <div className="pv-doc" ref={docScrollRef} style={{ display: ready ? 'block' : 'none' }}>
          <div className="pv-pages" ref={containerRef} />
        </div>
        {citePop && (
          <div
            className="tx-cite-pop"
            style={{ left: citePop.x, top: citePop.y }}
            onMouseEnter={() => clearTimeout(hidePop.current)}
            onMouseLeave={() => { hidePop.current = setTimeout(() => setCitePop(null), 180) }}
          >
            <div className="tx-cite-pop-h">
              <span className="tx-cite-n">[{citePop.num || '?'}]</span>
              <button className="tx-key" type="button"
                      onClick={() => navigate(routePath(slug, 'papers', citePop.source_id))}>
                {citePop.source_id}
              </button>
              {citePop.support && <Stamp value={citePop.support} />}
            </div>
            {citePop.quote && <div className="tx-hit-q">“{citePop.quote}”</div>}
            {(citePop.start != null && citePop.end != null) && (
              <div className="mono faint">{citePop.start}–{citePop.end}</div>
            )}
            <div className="tx-cite-pop-actions">
              <button className="tx-tool ghost" type="button"
                      onClick={() => onMarkerRef.current?.(citePop)}>Show in editor</button>
              <button className="tx-tool ghost" type="button"
                      onClick={() => navigate(routePath(slug, 'papers', citePop.source_id))}>
                Open source
              </button>
            </div>
          </div>
        )}
      </div>
      {logOpen && (
        <pre className="tx-log">{log || '(empty)'}</pre>
      )}
    </div>
  )
})
