import { useQuery } from '@tanstack/react-query'
import type { components } from '@/types/api.gen'
import { api } from './client'
import { keys } from './keys'

export type Health = components['schemas']['Health']

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => api<Health>('/health'),
    refetchInterval: 15_000,
  })
}
