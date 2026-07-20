// Obsidian-style live markdown editor (MDXEditor, built on Lexical): typing
// markdown renders inline via the shortcut plugin, and the stored format stays
// markdown (onChange gives markdown; insert() drops markdown at the cursor for
// cited passages). Heavy, so it is lazy-loaded by NoteDoc.
import React, { forwardRef, useImperativeHandle, useRef } from 'react'
import {
  MDXEditor, headingsPlugin, listsPlugin, quotePlugin, thematicBreakPlugin,
  linkPlugin, markdownShortcutPlugin,
} from '@mdxeditor/editor'
import '@mdxeditor/editor/style.css'

export default forwardRef(function MarkdownEditor({ markdown, onChange }, ref) {
  const ed = useRef(null)
  useImperativeHandle(ref, () => ({
    insert: (text) => { ed.current?.insertMarkdown(text); ed.current?.focus() },
  }))
  const dark = typeof document !== 'undefined' && document.documentElement.dataset.theme === 'dark'
  return (
    <MDXEditor
      ref={ed}
      markdown={markdown || ''}
      onChange={onChange}
      className={dark ? 'dark-theme' : ''}
      contentEditableClassName="nd-mdx"
      plugins={[
        headingsPlugin(), listsPlugin(), quotePlugin(), thematicBreakPlugin(),
        linkPlugin(), markdownShortcutPlugin(),
      ]}
    />
  )
})
