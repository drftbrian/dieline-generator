import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { History } from './types'

export function useHistory(projectId: string) {
  return useQuery({
    queryKey: keys.history(projectId),
    queryFn: () => api<History>(`/projects/${projectId}/history`),
    refetchInterval: (q) => (q.state.data?.versions.some((v) => v.status === 'running') ? 2000 : false),
  })
}

export function useDeleteVersion(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/projects/${projectId}/versions/${id}`, { method: 'DELETE' }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.history(projectId) })
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}
