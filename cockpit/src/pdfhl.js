// Locate an anchored quote inside a rendered PDF.js text layer and paint it.
//
// Citations and notes are W3C text-quote anchors (exact + prefix/suffix). The
// PDF's own text (pdfminer) and PDF.js's text layer differ in whitespace and
// line breaks, so we match on WHITESPACE-NORMALIZED, lower-cased text and keep
// a map back to raw offsets — then build a real DOM Range and use its client
// rects. This is how PDF.js's own find-highlight works, and it needs no stored
// bounding boxes.

// Reduce to a lower-cased ALPHANUMERIC stream, keeping a map back to raw
// offsets. Dropping whitespace, hyphens and punctuation makes matching immune
// to the ways PDF text differs from a selection or from pdfminer: line breaks
// with no space between spans, soft hyphens at line ends, punctuation spacing.
function normalize(raw) {
  let norm = ''
  const map = []
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i].toLowerCase()
    if ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')) { norm += ch; map.push(i) }
  }
  return { norm, map }
}

// Walk the text nodes of a text layer once; expose raw page text + a lookup
// from a raw char index to the (textNode, offset) that holds it.
function buildIndex(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes = []
  const starts = []
  let text = ''
  let n
  while ((n = walker.nextNode())) {
    starts.push(text.length)
    nodes.push(n)
    text += n.data
  }
  const nodeAt = (idx) => {
    idx = Math.max(0, Math.min(idx, text.length))
    let lo = 0, hi = nodes.length - 1, ans = 0
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (starts[mid] <= idx) { ans = mid; lo = mid + 1 } else hi = mid - 1
    }
    const node = nodes[ans]
    return { node, offset: Math.min(idx - starts[ans], node.data.length) }
  }
  return { text, nodeAt }
}

// Find `quote` in the text layer; return a DOM Range or null. Falls back to a
// leading slice of the quote when the exact span isn't found (tolerates the
// odd extraction mismatch). `prefix` disambiguates repeated quotes.
export function findRange(textLayerEl, quote, { prefix = '' } = {}) {
  if (!quote) return null
  const { text, nodeAt } = buildIndex(textLayerEl)
  const P = normalize(text)
  const Q = normalize(quote)
  if (!Q.norm || !P.norm) return null

  const occ = []
  for (let s = P.norm.indexOf(Q.norm); s !== -1; s = P.norm.indexOf(Q.norm, s + 1)) occ.push(s)
  let start, len
  if (occ.length) {
    len = Q.norm.length
    start = occ[0]
    if (occ.length > 1 && prefix) {           // pick the occurrence with the best-matching lead-in
      const pn = normalize(prefix).norm.slice(-24)
      start = occ.reduce((best, o) =>
        P.norm.slice(Math.max(0, o - pn.length), o).endsWith(pn) ? o : best, occ[0])
    }
  } else {
    const head = Q.norm.slice(0, Math.min(Q.norm.length, 80))   // fallback: leading slice
    start = P.norm.indexOf(head)
    if (start === -1) return null
    len = head.length
  }
  const rawStart = P.map[start]
  const rawEnd = P.map[start + len - 1] + 1
  const a = nodeAt(rawStart)
  const b = nodeAt(rawEnd)
  const range = document.createRange()
  try {
    range.setStart(a.node, a.offset)
    range.setEnd(b.node, b.offset)
  } catch { return null }
  return range
}

// Every match of `query` on a text layer, as { range, snippet } — snippet is a
// short bit of surrounding raw text for the results list. Capped for safety.
export function findAllRanges(textLayerEl, query) {
  if (!query || query.length < 2) return []
  const { text, nodeAt } = buildIndex(textLayerEl)
  const P = normalize(text)
  const Q = normalize(query)
  if (!Q.norm) return []
  const out = []
  for (let s = P.norm.indexOf(Q.norm); s !== -1 && out.length < 100;
       s = P.norm.indexOf(Q.norm, s + 1)) {
    const rawStart = P.map[s]
    const rawEnd = P.map[s + Q.norm.length - 1] + 1
    const a = nodeAt(rawStart)
    const b = nodeAt(rawEnd)
    const range = document.createRange()
    try {
      range.setStart(a.node, a.offset)
      range.setEnd(b.node, b.offset)
    } catch { continue }
    const snippet = text.slice(Math.max(0, rawStart - 32), rawEnd + 32)
      .replace(/\s+/g, ' ').trim()
    out.push({ range, snippet })
  }
  return out
}

// Paint one absolutely-positioned box per client rect of `range` into `overlay`
// (positioned relative to `pageEl`). Returns the created elements.
export function paintRects(range, overlay, pageEl, className, dataset = {}) {
  const pr = pageEl.getBoundingClientRect()
  const made = []
  for (const r of range.getClientRects()) {
    if (r.width < 1 || r.height < 1) continue
    const div = document.createElement('div')
    div.className = className
    div.style.left = `${r.left - pr.left}px`
    div.style.top = `${r.top - pr.top}px`
    div.style.width = `${r.width}px`
    div.style.height = `${r.height}px`
    for (const k in dataset) div.dataset[k] = dataset[k]
    overlay.appendChild(div)
    made.push(div)
  }
  return made
}

// Turn the current text selection (inside `textLayerEl`) into an anchor:
// the quoted span plus surrounding context, and where to float the popover.
export function selectionAnchor(textLayerEl, pageEl) {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null
  const range = sel.getRangeAt(0)
  if (!textLayerEl.contains(range.commonAncestorContainer)) return null
  const quote = sel.toString().replace(/\s+/g, ' ').trim()
  if (quote.length < 3) return null

  const before = document.createRange()
  before.selectNodeContents(textLayerEl)
  before.setEnd(range.startContainer, range.startOffset)
  const prefix = before.toString().replace(/\s+/g, ' ').slice(-40)

  const after = document.createRange()
  after.selectNodeContents(textLayerEl)
  after.setStart(range.endContainer, range.endOffset)
  const suffix = after.toString().replace(/\s+/g, ' ').slice(0, 40)

  const rects = range.getClientRects()
  const last = rects[rects.length - 1]
  return { quote, prefix, suffix, clientX: last?.right ?? 0, clientY: last?.bottom ?? 0 }
}
