// A note document: a full markdown writing surface attached to a paper, opened
// as its own tab. Live rendering (Obsidian-style, via MDXEditor), autosave, and
// an insert() the workspace calls to drop a cited passage in at the cursor.
import React, { Suspense, useEffect, useRef, useState } from 'react'
import { getPaperDoc, updatePaperDoc, deletePaperDoc } from '../api.js'

const MarkdownEditor = React.lazy(() => import('./MarkdownEditor.jsx'))

export default function NoteDoc({ docId, project, registerInsert, onClose, onMutate, onTitle }) {
  const [doc, setDoc] = useState(null)
  const [title, setTitle] = useState('')
  const [saved, setSaved] = useState(true)
  const bodyRef = useRef('')
  const titleRef = useRef('')
  const editorRef = useRef(null)
  const saveTimer = useRef(0)
  titleRef.current = title

  useEffect(() => {
    let live = true
    getPaperDoc(docId).then((d) => {
      if (live && d && !d.error) { setDoc(d); setTitle(d.title); bodyRef.current = d.body_md || '' }
    })
    return () => { live = false }
  }, [docId])

  const flush = () => {
    clearTimeout(saveTimer.current)
    updatePaperDoc(docId, { title: titleRef.current, body_md: bodyRef.current })
      .then(() => { setSaved(true); onMutate && onMutate() })
  }
  const schedule = () => {
    setSaved(false)
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(flush, 700)
  }
  useEffect(() => () => flush(), [])                 // save on unmount

  // the workspace registers this doc's insert so PDF citations land at the cursor
  useEffect(() => {
    if (!registerInsert) return
    registerInsert(docId, (text) => editorRef.current?.insert(text))
    return () => registerInsert(docId, null)
  }, [docId, registerInsert])

  if (!doc) return <div className="loading">reading the note…</div>

  return (
    <div className="nd">
      <div className="nd-bar">
        <input className="nd-title" value={title}
               onChange={(e) => { setTitle(e.target.value); onTitle && onTitle(docId, e.target.value); schedule() }}
               onBlur={flush} placeholder="Untitled note" />
        <span className="nd-status faint">{saved ? 'saved' : 'saving…'}</span>
        <button className="btn ghost danger" style={{ fontSize: 11, padding: '2px 8px' }}
                onClick={async () => { await deletePaperDoc(docId); onMutate && onMutate(); onClose && onClose() }}>
          Delete
        </button>
      </div>
      <div className="nd-body">
        <Suspense fallback={<div className="loading" style={{ padding: 20 }}>loading editor…</div>}>
          <MarkdownEditor ref={editorRef} markdown={doc.body_md || ''}
                          onChange={(md) => { bodyRef.current = md; schedule() }} />
        </Suspense>
      </div>
    </div>
  )
}
