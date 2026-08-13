// CodeMirror 6 LaTeX editor: stex highlighting, \\spancite decorations that
// carry store support status, click-to-inspect, and insert-at-cursor for the
// Cite palette. Heavy, so Write.jsx lazy-loads it. Remount with key={path}.
import React, { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import {
  autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap,
} from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import {
  StreamLanguage, bracketMatching, foldGutter, indentOnInput,
  syntaxHighlighting, defaultHighlightStyle,
} from '@codemirror/language'
import { stex } from '@codemirror/legacy-modes/mode/stex'
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search'
import { EditorState } from '@codemirror/state'
import {
  Decoration, EditorView, MatchDecorator, ViewPlugin, drawSelection,
  highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers,
} from '@codemirror/view'

const SPAN_RE = /\\spancite\{([^}]*)\}\{(\d+)\}\{(\d+)\}\{([^}]*)\}/g
const CITE_RE = /\\cite[tp]?\{([^}]+)\}/g

function themeExt(dark) {
  return EditorView.theme({
    '&': { height: '100%', fontSize: '13px', backgroundColor: 'transparent', color: 'var(--ink)' },
    '.cm-scroller': { fontFamily: 'var(--mono)', lineHeight: '1.55', overflow: 'auto' },
    '.cm-content': { caretColor: 'var(--accent)', padding: '10px 0 24px' },
    '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--faint)', border: 'none' },
    '.cm-activeLine': { backgroundColor: 'var(--accent-soft)' },
    '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--ink)' },
    '.cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground': {
      backgroundColor: 'var(--accent-soft) !important',
    },
    '.cm-cursor, &.cm-focused .cm-cursor': { borderLeftColor: 'var(--accent)' },
    '.cm-matchingBracket': { outline: '1px solid var(--accent)' },
  }, { dark })
}

function markPlugin(regexp, decoFor, click) {
  const decorator = new MatchDecorator({ regexp, decoration: decoFor })
  return ViewPlugin.fromClass(class {
    constructor(view) { this.decorations = decorator.createDeco(view) }
    update(u) { this.decorations = decorator.updateDeco(u, this.decorations) }
  }, {
    decorations: (v) => v.decorations,
    eventHandlers: click ? {
      click(e) {
        const t = e.target?.closest?.('.tx-span')
        if (!t) return
        click({
          source_id: t.dataset.source,
          start: +t.dataset.start,
          end: +t.dataset.end,
        })
      },
    } : undefined,
  })
}

export default forwardRef(function TexEditor(
  { doc, readOnly, onChange, onCiteClick, citations },
  ref,
) {
  const host = useRef(null)
  const viewRef = useRef(null)
  const citesRef = useRef(citations || new Map())
  citesRef.current = citations || new Map()
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const onCiteRef = useRef(onCiteClick)
  onCiteRef.current = onCiteClick

  useImperativeHandle(ref, () => ({
    insert(text) {
      const v = viewRef.current
      if (!v || v.state.readOnly) return
      const pos = v.state.selection.main.head
      v.dispatch({
        changes: { from: pos, to: pos, insert: text },
        selection: { anchor: pos + text.length },
      })
      v.focus()
    },
    selectedText() {
      const v = viewRef.current
      if (!v) return ''
      const { from, to } = v.state.selection.main
      return v.state.doc.sliceString(from, to)
    },
    focus() { viewRef.current?.focus() },
  }))

  useEffect(() => {
    if (!host.current) return
    const dark = document.documentElement.dataset.theme === 'dark'
    const spans = markPlugin(SPAN_RE, (m) => {
      const hit = citesRef.current.get(`${m[1]}:${m[2]}`)
      const kind = !hit ? 'missing' : (hit.support || 'partial')
      return Decoration.mark({
        class: `tx-span tx-span-${kind}`,
        attributes: {
          'data-source': m[1], 'data-start': m[2], 'data-end': m[3],
          title: (hit?.quote || m[4] || '').slice(0, 200),
        },
      })
    }, (s) => onCiteRef.current?.(s))
    const plains = markPlugin(CITE_RE, () => Decoration.mark({
      class: 'tx-cite-plain',
      attributes: { title: 'Bare \\cite — prefer \\spancite so the span lives in the store' },
    }))
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: doc || '',
        extensions: [
          lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(),
          drawSelection(), history(), foldGutter(), indentOnInput(),
          bracketMatching(), closeBrackets(), highlightSelectionMatches(),
          syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
          StreamLanguage.define(stex),
          autocompletion(),
          keymap.of([
            indentWithTab, ...closeBracketsKeymap, ...completionKeymap,
            ...searchKeymap, ...historyKeymap, ...defaultKeymap,
          ]),
          spans, plains,
          EditorView.updateListener.of((u) => {
            if (u.docChanged) onChangeRef.current?.(u.state.doc.toString())
          }),
          EditorState.readOnly.of(!!readOnly),
          themeExt(dark),
          EditorView.lineWrapping,
        ],
      }),
    })
    viewRef.current = view
    return () => { view.destroy(); viewRef.current = null }
  }, []) // remount via key= on the parent

  return <div className="tx-host" ref={host} />
})
