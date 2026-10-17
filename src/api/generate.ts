import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { EnhanceIn, GenerateOut, MergeIn } from './types'

/** ② 플랫 렌더: no options — the look is fixed on the server. */
export function useStartFlat(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api<GenerateOut>(`/projects/${projectId}/generate`, { method: 'POST', json: {}, idempotent: true }),
    // The server creates the version row immediately: history shows the placeholder at once.
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.history(projectId) }),
  })
}

/** ③ 레퍼런스 합성: our approved flat render in place of the reference's packaging. */
export function useStartMerge(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: MergeIn) =>
      api<GenerateOut>(`/projects/${projectId}/merge`, { method: 'POST', json: body, idempotent: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.history(projectId) }),
  })
}

/**
 * ② optional AI 재질 보정 of a finished code render. Always a new version; the source stays.
 * With `maps_from` it re-applies an earlier enhancement's maps at a new strength (no AI call).
 */
export function useStartEnhance(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sourceId, ...body }: Partial<EnhanceIn> & { sourceId: string }) =>
      api<GenerateOut>(`/projects/${projectId}/versions/${sourceId}/enhance`, {
        method: 'POST',
        json: { strength: 0.6, ...body },
        idempotent: true,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.history(projectId) }),
  })
}
