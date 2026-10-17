import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import { keys } from './keys'
import type { Project } from './types'

const ACTIVE: Project['status'][] = ['uploading', 'analyzing', 'rendering']

export function useProjects() {
  return useQuery({
    queryKey: keys.projects,
    queryFn: () => api<Project[]>('/projects'),
    refetchInterval: (q) => (q.state.data?.some((p) => ACTIVE.includes(p.status)) ? 2000 : false),
  })
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: keys.project(id ?? ''),
    queryFn: () => api<Project>(`/projects/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status) ? 1500 : false),
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api<Project>('/projects', { method: 'POST', json: { name }, idempotent: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  })
}

export function useRenameProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api<Project>(`/projects/${id}`, { method: 'PATCH', json: { name } }),
    onSuccess: (p) => {
      qc.setQueryData(keys.project(id), p)
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/projects/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  })
}


export const isApiError = (e: unknown): e is ApiError => e instanceof ApiError
