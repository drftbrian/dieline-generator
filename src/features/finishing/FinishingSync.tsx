import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { fetchFinishing, saveFinishing, useFinishingSpec } from '@/api/finishing'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import { ko } from '@/i18n/ko'
import { useShortcut } from '@/lib/shortcuts'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { finishingRedo, finishingUndo, isDirty, toPayload, useFinishingStore } from '@/stores/useFinishingStore'
import { toast } from '@/stores/useToastStore'

const t = ko.studio.finishing.assign
const DEBOUNCE = 600
const get = useFinishingStore.getState

/**
 * Keeps the working finishing list of a project in step with the server: loads it, saves it
 * ~600 ms after each change (base_revision = last saved revision), reloads on a conflict and
 * reverts on a rejected save. Also owns ⌘Z / ⇧⌘Z for the list while ② is shown.
 */
export function FinishingSync({ projectId }: { projectId: string }) {
  const qc = useQueryClient()
  const spec = useFinishingSpec(projectId)
  const assignments = useFinishingStore((s) => s.assignments)
  const ready = useFinishingStore((s) => s.projectId === projectId && s.status !== 'loading')
  const onFlat = useCanvasStore((s) => s.view === 'flat')

  // First load of this project (or a page reload): the server spec becomes the working copy.
  useEffect(() => {
    if (!spec.data || get().projectId === projectId) return
    get().hydrate(projectId, spec.data)
  }, [spec.data, projectId])
  useEffect(() => {
    if (spec.error && get().projectId !== projectId) get().setStatus('error', t.loadFailed)
  }, [spec.error, projectId])

  const inflight = useRef(false)
  const timer = useRef<number | undefined>(undefined)
  const saveRef = useRef<() => Promise<void>>(async () => {})

  const save = useCallback(async () => {
    window.clearTimeout(timer.current)
    const s = get()
    if (inflight.current || s.projectId !== projectId || !isDirty(s)) return
    inflight.current = true
    s.setStatus('saving')
    const sent = s.assignments
    let retry = true
    try {
      const res = await saveFinishing(projectId, s.saved.revision, sent.map(toPayload))
      qc.setQueryData(keys.finishing(projectId), res)
      if (get().projectId === projectId) get().savedAs(res, sent)
    } catch (e) {
      // Another project opened meanwhile: its working copy is not ours to touch.
      if (get().projectId !== projectId) {
        retry = false
        qc.invalidateQueries({ queryKey: keys.finishing(projectId) })
      } else if (e instanceof ApiError && e.status === 409) {
        try {
          const fresh = await fetchFinishing(projectId)
          get().hydrate(projectId, fresh)
          qc.setQueryData(keys.finishing(projectId), fresh)
          toast({ tone: 'warning', message: t.conflict })
        } catch (e2) {
          get().setStatus('error', e2 instanceof Error ? e2.message : t.loadFailed)
          retry = false
        }
      } else if (e instanceof ApiError && e.status === 422) {
        get().revert()
        toast({ tone: 'danger', message: t.rejected(e.message), duration: 8000 })
      } else {
        get().setStatus('error', e instanceof Error ? e.message : String(e))
        retry = false
      }
    } finally {
      inflight.current = false
    }
    // Changes made while the request was out go in the next save.
    if (retry && isDirty(get())) timer.current = window.setTimeout(() => void saveRef.current(), DEBOUNCE)
  }, [projectId, qc])
  useLayoutEffect(() => {
    saveRef.current = save
  })

  // Debounced autosave after each change of the working list.
  useEffect(() => {
    if (!ready || !isDirty(get())) return
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void save(), DEBOUNCE)
    return () => window.clearTimeout(timer.current)
  }, [assignments, ready, save])

  // Leaving the studio: send what is pending right away; closing the tab: warn first.
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (get().projectId === projectId && (isDirty(get()) || inflight.current)) e.preventDefault()
    }
    window.addEventListener('beforeunload', onUnload)
    return () => {
      window.removeEventListener('beforeunload', onUnload)
      void save()
    }
  }, [projectId, save])

  // "다시 저장" in the panel.
  const retryTick = useFinishingStore((s) => s.retryTick)
  useEffect(() => {
    if (retryTick > 0) void save()
  }, [retryTick, save])

  useShortcut({ key: 'z', mod: true }, () => finishingUndo(), onFlat && ready)
  useShortcut({ key: 'z', mod: true, shift: true }, () => finishingRedo(), onFlat && ready)
  return null
}
