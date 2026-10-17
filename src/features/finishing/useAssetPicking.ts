import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { hitAssets } from '@/api/assets'
import { ApiError } from '@/api/client'
import { ko } from '@/i18n/ko'
import { useShortcut } from '@/lib/shortcuts'
import { useAssetSelectionStore } from '@/stores/useAssetSelectionStore'
import { useToastStore } from '@/stores/useToastStore'
import type { PickGeometry } from './geometry'

const HOVER_DELAY = 120 // ms of rest before asking the server what is under the pointer
const CACHE_MAX = 400

type Point = { x: number; y: number }
const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

/**
 * Canvas selection mode on ② 플랫 렌더: hover outlines, click / Shift+click / Alt+click,
 * "[" / "]" cycling through what lies under the last clicked point, Esc to clear.
 * Pass `geo: null` to switch everything off.
 */
export function useAssetPicking(projectId: string, geo: PickGeometry | null) {
  const store = useAssetSelectionStore.getState
  const active = !!geo
  const geoRef = useRef(geo)
  useLayoutEffect(() => {
    geoRef.current = geo
  })

  // Hit results per rounded page point (1 pt), per project.
  const cache = useRef<{ pid: string; map: Map<string, string[]> }>({ pid: projectId, map: new Map() })
  const timer = useRef<number | undefined>(undefined)
  const hoverReq = useRef<AbortController | null>(null)
  const clickReq = useRef<AbortController | null>(null)

  const lookup = useCallback(
    async (page: Point, signal: AbortSignal) => {
      if (cache.current.pid !== projectId) cache.current = { pid: projectId, map: new Map() }
      const map = cache.current.map
      const x = Math.round(page.x)
      const y = Math.round(page.y)
      const key = `${x},${y}`
      const hit = map.get(key)
      if (hit) return { key, candidates: hit }
      const candidates = await hitAssets(projectId, x, y, signal)
      if (map.size >= CACHE_MAX) map.delete(map.keys().next().value as string)
      map.set(key, candidates)
      return { key, candidates }
    },
    [projectId],
  )

  const cancelHover = useCallback(() => {
    window.clearTimeout(timer.current)
    hoverReq.current?.abort()
    hoverReq.current = null
  }, [])

  // Switching off (or to another project): stop pending work and forget the hover.
  useEffect(() => {
    if (!active) return
    return () => {
      cancelHover()
      clickReq.current?.abort()
      useAssetSelectionStore.getState().setHover(projectId, null)
    }
  }, [active, projectId, cancelHover])

  const onWorldMove = useCallback(
    (p: Point) => {
      const g = geoRef.current
      if (!g) return
      cancelHover()
      if (!g.inside(p)) {
        store().setHover(projectId, null)
        return
      }
      const page = g.toPage(p)
      const cached = cache.current.pid === projectId && cache.current.map.get(`${Math.round(page.x)},${Math.round(page.y)}`)
      if (cached) {
        store().setHover(projectId, cached[0] ?? null)
        return
      }
      timer.current = window.setTimeout(() => {
        const ctrl = new AbortController()
        hoverReq.current = ctrl
        lookup(page, ctrl.signal)
          .then(({ candidates }) => !ctrl.signal.aborted && store().setHover(projectId, candidates[0] ?? null))
          .catch((e) => !isAbort(e) && store().setHover(projectId, null))
      }, HOVER_DELAY)
    },
    [projectId, lookup, cancelHover, store],
  )

  const onWorldLeave = useCallback(() => {
    cancelHover()
    store().setHover(projectId, null)
  }, [projectId, cancelHover, store])

  const onWorldClick = useCallback(
    (p: Point, e: React.MouseEvent) => {
      const g = geoRef.current
      if (!g) return
      const shift = e.shiftKey
      const alt = e.altKey
      const s = store()
      if (!g.inside(p)) {
        if (!shift) s.clear(projectId)
        return
      }
      clickReq.current?.abort()
      const ctrl = new AbortController()
      clickReq.current = ctrl
      lookup(g.toPage(p), ctrl.signal)
        .then(({ key, candidates }) => {
          if (ctrl.signal.aborted) return
          const s = store()
          const top = candidates[0]
          if (!top) {
            if (!shift) s.clear(projectId)
            return
          }
          s.setHover(projectId, top)
          if (alt) {
            // Alt+click: the next candidate under the same point (or the parent on a new point).
            if (s.cycle[projectId]?.key !== key) {
              s.setCycle(projectId, { key, candidates, index: 0 })
              if (!(s.selected[projectId] ?? []).includes(top)) s.select(projectId, top)
            }
            store().stepCycle(projectId, 1)
            return
          }
          s.setCycle(projectId, { key, candidates, index: 0 })
          if (shift) s.toggle(projectId, top)
          else s.select(projectId, top)
        })
        .catch((err) => {
          if (isAbort(err)) return
          useToastStore.getState().push({
            tone: 'warning',
            message: err instanceof ApiError ? err.message : ko.studio.finishing.hitFailed,
          })
        })
    },
    [projectId, lookup, store],
  )

  useShortcut({ key: '[' }, () => store().stepCycle(projectId, -1), active)
  useShortcut({ key: ']' }, () => store().stepCycle(projectId, 1), active)
  useShortcut({ key: 'Escape' }, () => store().clear(projectId), active)

  return { onWorldMove, onWorldLeave, onWorldClick }
}
