// Minimal, dependency-free Markdown → HTML for note documents. It escapes the
// input first, then applies a small block + inline grammar (headings, quotes,
// lists, code, bold/italic/code/links). Not CommonMark-complete — enough for
// notes, and safe to inject because everything is HTML-escaped up front.
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
}

export function renderMarkdown(md) {
  const lines = (md || '').replace(/\r\n/g, '\n').split('\n')
  const out = []
  let i = 0
  const isBlockStart = (l) => /^(#{1,6}\s|>|```|\s*[-*]\s|\s*\d+\.\s|-{3,}\s*$)/.test(l)
  while (i < lines.length) {
    const line = lines[i]
    if (/^```/.test(line)) {
      const buf = []; i++
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++ }
      i++
      out.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>')
      continue
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) { const n = h[1].length; out.push(`<h${n}>${inline(h[2])}</h${n}>`); i++; continue }
    if (/^(-{3,}|\*{3,})\s*$/.test(line)) { out.push('<hr>'); i++; continue }
    if (/^>\s?/.test(line)) {
      const buf = []
      while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i++ }
      out.push('<blockquote>' + renderMarkdown(buf.join('\n')) + '</blockquote>')
      continue
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { buf.push('<li>' + inline(lines[i].replace(/^\s*[-*]\s+/, '')) + '</li>'); i++ }
      out.push('<ul>' + buf.join('') + '</ul>')
      continue
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { buf.push('<li>' + inline(lines[i].replace(/^\s*\d+\.\s+/, '')) + '</li>'); i++ }
      out.push('<ol>' + buf.join('') + '</ol>')
      continue
    }
    if (/^\s*$/.test(line)) { i++; continue }
    const buf = []
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !isBlockStart(lines[i])) { buf.push(lines[i]); i++ }
    out.push('<p>' + inline(buf.join(' ')) + '</p>')
  }
  return out.join('\n')
}
