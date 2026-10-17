import type { Version } from '@/api/types'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { pick, useVersions } from './versions'

/** The finished version the canvas shows right now (null in ① 원본 or when there is none yet). */
export function useShownVersion(projectId: string): Version | null {
  const { flats, merges } = useVersions(projectId)
  const view = useCanvasStore((s) => s.view)
  const flatId = useCanvasStore((s) => s.flatId)
  const mergeId = useCanvasStore((s) => s.mergeId)
  if (view === 'flat') return pick(flats, flatId)
  if (view === 'merge') return pick(merges, mergeId)
  return null
}
