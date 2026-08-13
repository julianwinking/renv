import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import {
  LIBRARY, loadWorkspace, openTab, closePane, closeKey, toggleSplit,
  dropTab, undockTab, placeTab, moveView, pruneViews, renameDoc, activeView, isSplit,
} from './paperWorkspace.js'

const paper = (key, title = key) => ({ type: 'paper', key, title })
const wsOf = (...paneLists) => ({
  views: paneLists.map((panes, i) => ({ id: 'v' + i, panes })),
  active: 'v0',
})

describe('loadWorkspace', () => {
  it('starts empty', () => {
    assert.deepEqual(loadWorkspace(null), { views: [], active: LIBRARY })
  })

  it('keeps the views shape', () => {
    const raw = { views: [{ id: 'a', panes: [paper('p1')] }], active: 'a' }
    assert.deepEqual(loadWorkspace(raw), raw)
  })

  it('migrates a legacy split into one paired tab', () => {
    const next = loadWorkspace({
      tabs: [paper('a'), paper('b'), paper('c')],
      active: 'a',
      split: 'b',
    })
    assert.equal(next.views.length, 2)
    assert.deepEqual(next.views[0].panes.map((p) => p.key), ['a', 'b'])
    assert.equal(next.views[1].panes[0].key, 'c')
    assert.equal(next.active, next.views[0].id)
  })

  it('migrates singles when there was no split', () => {
    const next = loadWorkspace({ tabs: [paper('a')], active: 'a' })
    assert.equal(next.views.length, 1)
    assert.equal(next.active, next.views[0].id)
  })
})

describe('openTab', () => {
  it('appends a new view', () => {
    const next = openTab({ views: [], active: LIBRARY }, paper('a'))
    assert.equal(next.views.length, 1)
    assert.equal(next.active, next.views[0].id)
  })

  it('focuses the view that already holds the paper', () => {
    const ws = wsOf([paper('a'), paper('b')])
    const next = openTab(ws, paper('b'))
    assert.equal(next.views.length, 1)
    assert.equal(next.active, 'v0')
  })
})

describe('toggleSplit', () => {
  it('opens an empty right pane', () => {
    const next = toggleSplit(wsOf([paper('a')]), 'v0')
    assert.equal(next.views[0].panes.length, 2)
    assert.equal(next.views[0].panes[1], null)
    assert.equal(next.active, 'v0')
  })

  it('cancels a waiting split', () => {
    const next = toggleSplit(wsOf([paper('a'), null]), 'v0')
    assert.deepEqual(next.views[0].panes.map((p) => p?.key), ['a'])
  })
})

describe('dropTab', () => {
  it('drops left of a single to make a split', () => {
    const ws = { views: [{ id: 'v0', panes: [paper('a')] }, { id: 'v1', panes: [paper('b')] }], active: 'v0' }
    const next = dropTab(ws, 'left', 'b')
    assert.deepEqual(next.views[0].panes.map((p) => p.key), ['b', 'a'])
    assert.equal(next.views.length, 1)
  })

  it('drops right of a single to make a split', () => {
    const ws = { views: [{ id: 'v0', panes: [paper('a')] }, { id: 'v1', panes: [paper('b')] }], active: 'v0' }
    const next = dropTab(ws, 'right', 'b')
    assert.deepEqual(next.views[0].panes.map((p) => p.key), ['a', 'b'])
    assert.equal(next.views.length, 1)
  })

  it('fills a waiting vacancy from either side', () => {
    const ws = { views: [{ id: 'v0', panes: [paper('a'), null] }, { id: 'v1', panes: [paper('b')] }], active: 'v0' }
    assert.deepEqual(dropTab(ws, 'right', 'b').views[0].panes.map((p) => p.key), ['a', 'b'])
    assert.deepEqual(dropTab(ws, 'left', 'b').views[0].panes.map((p) => p.key), ['b', 'a'])
  })

  it('displaces the occupied side of a full split', () => {
    const ws = {
      views: [{ id: 'v0', panes: [paper('a'), paper('b')] }, { id: 'v1', panes: [paper('c')] }],
      active: 'v0',
    }
    const next = dropTab(ws, 'left', 'c')
    assert.deepEqual(next.views[0].panes.map((p) => p.key), ['c', 'b'])
    assert.equal(next.views[1].panes[0].key, 'a')
  })

  it('swaps sides when dragging within a split', () => {
    const ws = wsOf([paper('a'), paper('b')])
    const next = dropTab(ws, 'right', 'a')
    assert.deepEqual(next.views[0].panes.map((p) => p.key), ['b', 'a'])
    assert.equal(next.views.length, 1)
  })

  it('is a no-op when dragging a lone tab onto itself', () => {
    const ws = wsOf([paper('a')])
    assert.deepEqual(dropTab(ws, 'right', 'a'), ws)
  })

  it('ignores drops on the library', () => {
    const ws = { views: [{ id: 'v0', panes: [paper('a')] }], active: LIBRARY }
    assert.deepEqual(dropTab(ws, 'left', 'a'), ws)
  })

  it('drops onto a non-active view when targetId is set', () => {
    const ws = {
      views: [
        { id: 'v0', panes: [paper('a')] },
        { id: 'v1', panes: [paper('b')] },
        { id: 'v2', panes: [paper('c')] },
      ],
      active: 'v0',
    }
    const next = dropTab(ws, 'right', 'c', 'v1')
    const pair = next.views.find((v) => v.id === 'v1')
    assert.deepEqual(pair.panes.map((p) => p.key), ['b', 'c'])
    assert.equal(next.active, 'v1')
    assert.equal(next.views.length, 2)
    assert.equal(next.views[0].panes[0].key, 'a')
  })

  it('keeps a waiting split when the lone filled chip is dropped on itself', () => {
    const ws = wsOf([paper('a'), null])
    assert.deepEqual(dropTab(ws, 'right', 'a'), ws)
  })
})

describe('undockTab / placeTab', () => {
  it('pulls a chip out of a pair into its own tab after the leftover', () => {
    const ws = { views: [{ id: 'v0', panes: [paper('a'), paper('b')] }, { id: 'v1', panes: [paper('c')] }], active: 'v0' }
    const next = undockTab(ws, 'b')
    assert.equal(next.views.length, 3)
    assert.deepEqual(next.views[0].panes.map((p) => p.key), ['a'])
    assert.equal(next.views[1].panes[0].key, 'c')
    assert.equal(next.views[2].panes[0].key, 'b')
    assert.equal(next.active, next.views[2].id)
    assert.equal(isSplit(next.views[0]), false)
  })

  it('inserts the extracted tab before a given view', () => {
    const ws = { views: [{ id: 'v0', panes: [paper('a'), paper('b')] }, { id: 'v1', panes: [paper('c')] }], active: 'v0' }
    const next = undockTab(ws, 'b', 'v0')
    assert.equal(next.views[0].panes[0].key, 'b')
    assert.deepEqual(next.views[1].panes.map((p) => p.key), ['a'])
    assert.equal(next.views[2].panes[0].key, 'c')
  })

  it('is a no-op on a single tab', () => {
    const ws = wsOf([paper('a')])
    assert.deepEqual(undockTab(ws, 'a'), ws)
  })

  it('placeTab undocks a pair chip and reorders a single', () => {
    const pair = { views: [{ id: 'v0', panes: [paper('a'), paper('b')] }], active: 'v0' }
    const pulled = placeTab(pair, 'a')
    assert.equal(pulled.views.length, 2)
    assert.equal(pulled.views[0].panes[0].key, 'b')
    assert.equal(pulled.views[1].panes[0].key, 'a')

    const singles = { views: [{ id: 'v0', panes: [paper('a')] }, { id: 'v1', panes: [paper('b')] }], active: 'v1' }
    const moved = placeTab(singles, 'b', 'v0')
    assert.deepEqual(moved.views.map((v) => v.panes[0].key), ['b', 'a'])
    assert.equal(moved.active, 'v1')
  })

  it('moveView is a no-op when dropping a view onto itself', () => {
    const ws = wsOf([paper('a')], [paper('b')])
    assert.deepEqual(moveView(ws, 'v0', 'v0'), ws)
  })
})

describe('closePane', () => {
  it('collapses a split to the remaining pane', () => {
    const next = closePane(wsOf([paper('a'), paper('b')]), 'v0', 1)
    assert.deepEqual(next.views[0].panes.map((p) => p.key), ['a'])
  })

  it('removes the view when the last pane closes', () => {
    const next = closeKey(wsOf([paper('a')]), 'a')
    assert.deepEqual(next, { views: [], active: LIBRARY })
  })
})

describe('pruneViews', () => {
  it('drops papers that left the corpus and keeps a vacancy', () => {
    const ws = {
      views: [
        { id: 'v0', panes: [paper('gone')] },
        { id: 'v1', panes: [paper('ok'), null] },
      ],
      active: 'v0',
    }
    const next = pruneViews(ws, [{ key: 'ok', has_pdf: true }])
    assert.equal(next.views.length, 1)
    assert.equal(next.views[0].panes[0].key, 'ok')
    assert.equal(next.views[0].panes[1], null)
    assert.equal(next.active, LIBRARY)
  })
})

describe('renameDoc', () => {
  it('updates the tab title', () => {
    const ws = wsOf([{ type: 'doc', key: 'doc:1', docId: 1, title: 'old' }])
    const next = renameDoc(ws, 1, 'new')
    assert.equal(next.views[0].panes[0].title, 'new')
  })
})

describe('activeView / isSplit', () => {
  it('reads the focused view', () => {
    const ws = wsOf([paper('a'), paper('b')])
    assert.equal(isSplit(activeView(ws)), true)
    assert.equal(activeView({ views: [], active: LIBRARY }), null)
  })
})
