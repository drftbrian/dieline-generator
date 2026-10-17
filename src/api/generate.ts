import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { GenerateOut, MergeIn } from './types'

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
