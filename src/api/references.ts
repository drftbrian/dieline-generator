import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { Reference } from './types'

export const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const MAX_REFERENCE_MB = 10

const READING: Reference['analysis_status'][] = ['pending', 'stale']

export function useReferences(projectId: string) {
  return useQuery({
    queryKey: keys.references(projectId),
    queryFn: () => api<Reference[]>(`/projects/${projectId}/references`),
    // Claude's reading arrives a few seconds after upload (or after a stale re-read).
    refetchInterval: (q) => (q.state.data?.some((r) => READING.includes(r.analysis_status)) ? 2000 : false),
  })
}

export function useUploadReference(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api<Reference>(`/projects/${projectId}/references`, { method: 'POST', body: form })
    },
    onSettled: () => qc.invalidateQueries({ queryKey: keys.references(projectId) }),
  })
}

/** Run Claude's reading again (paid call). */
export function useReanalyzeReference(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<Reference>(`/projects/${projectId}/references/${id}/analyze`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.references(projectId) }),
  })
}

export function useDeleteReference(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/projects/${projectId}/references/${id}`, { method: 'DELETE' }),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.references(projectId) }),
  })
}
