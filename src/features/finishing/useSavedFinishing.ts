import { useFinishingWarnings } from '@/api/finishing'
import { isDirty, useFinishingStore } from '@/stores/useFinishingStore'

/** The saved revision and whether it has any enabled finish (the server only knows saved state). */
export function useSaved(projectId: string) {
  const revision = useFinishingStore((s) => (s.projectId === projectId ? s.saved.revision : 0))
  const hasFinishes = useFinishingStore((s) => s.projectId === projectId && s.saved.assignments.some((a) => a.enabled))
  const pending = useFinishingStore((s) => s.projectId === projectId && (s.status === 'saving' || isDirty(s)))
  return { revision, hasFinishes, pending }
}

/** Manufacturing checks of the saved revision (shared query; errors never block saving). */
export function useWarnings(projectId: string) {
  const { revision, hasFinishes } = useSaved(projectId)
  return useFinishingWarnings(projectId, revision, hasFinishes)
}
