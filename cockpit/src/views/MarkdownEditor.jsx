// Obsidian-style live markdown (MDXEditor / Lexical): shortcuts render inline,
// the stored format stays markdown (onChange emits markdown; insert() drops
// markdown at the cursor). Heavy, so callers lazy-load it.
import React, { forwardRef, useImperativeHandle, useRef } from 'react'
import {
  MDXEditor,
  BlockTypeSelect, BoldItalicUnderlineToggles, CodeToggle, CreateLink,
  DiffSourceToggleWrapper, InsertCodeBlock, InsertTable, InsertThematicBreak,
  ListsToggle, Separator, UndoRedo,
  codeBlockPlugin, codeMirrorPlugin, diffSourcePlugin, headingsPlugin,
  linkDialogPlugin, linkPlugin, listsPlugin, markdownShortcutPlugin,
  quotePlugin, tablePlugin, thematicBreakPlugin, toolbarPlugin,
} from '@mdxeditor/editor'
import '@mdxeditor/editor/style.css'

function MdToolbar() {
  return (
    <DiffSourceToggleWrapper options={['rich-text', 'source']}>
      <UndoRedo />
      <Separator />
      <BoldItalicUnderlineToggles options={['Bold', 'Italic']} />
      <CodeToggle />
      <Separator />
      <BlockTypeSelect />
      <Separator />
      <ListsToggle options={['bullet', 'number']} />
      <Separator />
      <CreateLink />
      <InsertThematicBreak />
      <InsertTable />
      <InsertCodeBlock />
    </DiffSourceToggleWrapper>
  )
}

// Built once — MDXEditor remounts if the plugins array identity changes.
const PLUGINS = [
  headingsPlugin(),
  listsPlugin(),
  quotePlugin(),
  thematicBreakPlugin(),
  linkPlugin(),
  linkDialogPlugin(),
  tablePlugin(),
  codeBlockPlugin({ defaultCodeBlockLanguage: 'txt' }),
  codeMirrorPlugin({
    codeBlockLanguages: {
      txt: 'Plain',
      '': 'Plain',
      md: 'Markdown',
      bash: 'Bash',
      python: 'Python',
      js: 'JavaScript',
      json: 'JSON',
      tex: 'TeX',
    },
  }),
  diffSourcePlugin({ viewMode: 'rich-text' }),
  toolbarPlugin({ toolbarContents: () => <MdToolbar />, toolbarClassName: 'renv-mdx-toolbar' }),
  markdownShortcutPlugin(),
]

const TO_MD = { bullet: '-', emphasis: '*', fence: '`', listItemIndent: 'one', rule: '-' }

export default forwardRef(function MarkdownEditor({
  markdown, onChange, onError, className, contentEditableClassName,
  placeholder, spellCheck = true, autoFocus, suppressHtmlProcessing = true,
}, ref) {
  const ed = useRef(null)
  useImperativeHandle(ref, () => ({
    insert: (text) => { ed.current?.insertMarkdown(text); ed.current?.focus() },
  }))
  const dark = typeof document !== 'undefined' && document.documentElement.dataset.theme === 'dark'
  return (
    <MDXEditor
      ref={ed}
      markdown={markdown || ''}
      onChange={(md, initialNormalize) => { if (!initialNormalize) onChange?.(md) }}
      onError={onError}
      className={['renv-mdx', dark ? 'dark-theme' : '', className].filter(Boolean).join(' ')}
      contentEditableClassName={contentEditableClassName || 'nd-mdx'}
      placeholder={placeholder}
      spellCheck={spellCheck}
      autoFocus={autoFocus}
      trim={false}
      suppressHtmlProcessing={suppressHtmlProcessing}
      toMarkdownOptions={TO_MD}
      plugins={PLUGINS}
    />
  )
})
