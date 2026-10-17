import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { Project } from './types'

type ImportOut = { project: Project; job_id: string }

export function useFigmaStatus() {
  return useQuery({
    queryKey: ['figma-status'],
    queryFn: () => api<{ configured: boolean }>('/figma/status'),
    staleTime: 60_000,
  })
}

/** Create a project from a Figma frame link (server exports the PDF and reads layer names). */
export function useImportFigma() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (url: string) =>
      api<ImportOut>('/projects/figma', { method: 'POST', json: { url }, idempotent: true }),
    onSuccess: (out) => {
      qc.setQueryData(keys.project(out.project.id), out.project)
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}
