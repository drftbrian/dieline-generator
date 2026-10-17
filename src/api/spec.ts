import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { SpecPatch, Specification } from './types'

export function useSpecification(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.spec(projectId ?? ''),
    queryFn: () => api<Specification>(`/projects/${projectId}/specification`),
    enabled: !!projectId && enabled,
    staleTime: Infinity,
  })
}

/** PATCH with If-Match so concurrent edits surface as SPEC_CONFLICT (409). */
export function usePatchSpecification(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ patch, version }: { patch: SpecPatch; version?: number }) =>
      api<Specification>(`/projects/${projectId}/specification`, {
        method: 'PATCH',
        json: patch,
        headers: version !== undefined ? { 'If-Match': String(version) } : undefined,
      }),
    onSuccess: (spec) => {
      qc.setQueryData(keys.spec(projectId), spec)
      qc.invalidateQueries({ queryKey: keys.project(projectId) })
    },
  })
}

export function useConfirmStructure(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api<{ job_id: string }>(`/projects/${projectId}/specification/confirm`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.project(projectId) })
      qc.invalidateQueries({ queryKey: keys.spec(projectId) })
    },
  })
}
