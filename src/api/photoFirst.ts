import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { Candidate, CandidateFace, GenerateOut, PanelChoice, TypographyIn } from './types'

// ③ AI 사진 글자 교정 (photo-first): an AI photo corrected with Figma's own lettering.

const candidatesKey = (pid: string) => ['candidates', pid] as const

export function useCandidates(projectId: string) {
  return useQuery({
    queryKey: candidatesKey(projectId),
    queryFn: () => api<Candidate[]>(`/projects/${projectId}/candidates`),
  })
}

/** The panels that can be a visible face of the closed carton. */
export function useCandidatePanels(projectId: string) {
  return useQuery({
    queryKey: ['candidate-panels', projectId],
    queryFn: () => api<PanelChoice[]>(`/projects/${projectId}/candidates/panels`),
    staleTime: 60_000,
  })
}

export function useUploadCandidate(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api<Candidate>(`/projects/${projectId}/candidates`, { method: 'POST', body: form })
    },
    onSettled: () => qc.invalidateQueries({ queryKey: candidatesKey(projectId) }),
  })
}

export function useSaveFaces(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, faces }: { id: string; faces: CandidateFace[] }) =>
      api<Candidate>(`/projects/${projectId}/candidates/${id}/faces`, { method: 'PUT', json: { faces } }),
    onSuccess: (c) =>
      qc.setQueryData<Candidate[]>(candidatesKey(projectId), (list) => list?.map((x) => (x.id === c.id ? c : x))),
  })
}

export function useDeleteCandidate(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/projects/${projectId}/candidates/${id}`, { method: 'DELETE' }),
    onSettled: () => qc.invalidateQueries({ queryKey: candidatesKey(projectId) }),
  })
}

export function useStartTypography(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TypographyIn) =>
      api<GenerateOut>(`/projects/${projectId}/typography`, { method: 'POST', json: body, idempotent: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.history(projectId) }),
  })
}

/** A saved intermediate of a photo-first version. */
export const versionLayerUrl = (projectId: string, versionId: string, layer: 'raw' | 'strict' | 'repair_preview') =>
  `/api/projects/${projectId}/versions/${versionId}/layers/${layer}`
