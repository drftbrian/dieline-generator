import type { ProjectStatus } from '@/api/types'

/** Which workspace screen a project in this status belongs on. */
export function routeForStatus(status: ProjectStatus): 'analyze' | 'review' | 'studio' {
  if (status === 'needs_review') return 'review'
  if (status === 'ready') return 'studio'
  return 'analyze'
}
