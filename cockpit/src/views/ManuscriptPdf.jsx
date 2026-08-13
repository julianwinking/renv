// Compiled manuscript preview: PDF.js pages + clickable \\spancite markers
// ([key:start--end] as emitted by the preamble macro).
import React, { useEffect, useRef, useState } from 'react'
import { writePdfUrl } from '../api.js'
import { findSpanCiteMarkers, paintRects } from '../pdfhl.js'

export default function ManuscriptPdf({ slug, bust, citations, onMarker, status, log, errors, engine }) {
  const [ready, setReady] = useState(false)
  const [err, setErr] = useState('')
  const [scale, setScale] = useState(1.15)
  const [numPages, setNumPages] = useState(0)
  const [logOpen, setLogOpen] = useState(false)
  const docScrollRef = useRef(null)
  const containerRef = useRef(null)
  const pagesRef = useRef([])
  const pdfRef = useRef(null)
  const pdfjsRef = useRef(null)
  const renderTok = useRef(0)
  const citesRef = useRef(citations)
  citesRef.current = citations
  const onMarkerRef = useRef(onMarker)
  onMarkerRef.current = onMarker

  useEffect(() => {
    let cancelled = false
    setReady(false); setErr('')
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
        setNumPages(doc.numPages)
        await renderPages(1.15)
        if (!cancelled) setReady(true)
      } catch (e) {
        if (!cancelled) setErr(String(e?.message || e))
      }
    })()
    return () => { cancelled = true; try { pdfRef.current?.destroy() } catch {} }
  }, [slug, bust])

  useEffect(() => { if (ready) renderPages(scale) }, [scale]) // eslint-disable-line
  useEffect(() => { if (ready) paintMarkers() }, [citations, ready])

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
      pagesRef.current.push({ page: n, pageEl, textLayerEl, hlEl })
    }
    paintMarkers()
  }

  function paintMarkers() {
    for (const p of pagesRef.current) {
      p.hlEl.innerHTML = ''
      const marks = findSpanCiteMarkers(p.textLayerEl)
      for (const m of marks) {
        const hit = (citesRef.current || []).find(
          (c) => c.source_id === m.source_id && c.src_start === m.start)
        const cls = 'pv-mark pv-mark-cite' + (hit?.support === 'none' ? ' tx-span-none' : '')
        const els = paintRects(m.range, p.hlEl, p.pageEl, cls, {
          source: m.source_id, start: String(m.start), end: String(m.end),
        })
        for (const el of els) {
          el.style.pointerEvents = 'auto'
          el.style.cursor = 'pointer'
          el.title = (hit?.quote || `${m.source_id}:${m.start}–${m.end}`)
          el.addEventListener('click', (e) => {
            e.stopPropagation()
            onMarkerRef.current?.({ source_id: m.source_id, start: m.start, end: m.end, citation: hit })
          })
        }
      }
    }
  }

  const compiling = status === 'running'
  const failed = status === 'error'
  const noPdf = status === 'no-engine' || status === 'missing'

  return (
    <div className="tx-pdf">
      <div className="tx-pdf-bar">
        <span className="eyebrow" style={{ margin: 0 }}>PDF</span>
        {engine && <span className="mono faint" style={{ fontSize: 10.5 }}>{engine}</span>}
        <div className="pv-zoom" style={{ marginLeft: 'auto' }}>
          <button className="pv-tbtn" onClick={() => setScale((s) => Math.max(0.6, s - 0.1))} disabled={!ready}>−</button>
          <span className="pv-zoom-n">{Math.round(scale * 100)}%</span>
          <button className="pv-tbtn" onClick={() => setScale((s) => Math.min(2.4, s + 0.1))} disabled={!ready}>+</button>
        </div>
        {numPages > 0 && <span className="faint" style={{ fontSize: 11.5 }}>{numPages}p</span>}
        <button className={`pv-tbtn ${logOpen ? 'on' : ''}`} onClick={() => setLogOpen((v) => !v)}>Log</button>
      </div>
      <div className="tx-pdf-body">
        {compiling && <div className="tx-pdf-msg">Compiling…</div>}
        {noPdf && !compiling && (
          <div className="tx-pdf-msg">
            <b>No PDF yet.</b>
            <p className="muted">
              {status === 'no-engine'
                ? 'No LaTeX engine on PATH (latexmk, tectonic, or pdflatex). The editor, weave, and \\spancite still work — install TeX Live or tectonic to preview.'
                : 'Click Recompile to weave numbers from the store and build the PDF.'}
            </p>
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
      </div>
      {logOpen && (
        <pre className="tx-log">{log || '(empty)'}</pre>
      )}
    </div>
  )
}
