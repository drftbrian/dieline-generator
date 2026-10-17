import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef } from 'react'
import { api } from './client'
import { keys } from './keys'
import type { Job } from './types'

const FINISHED: Job['status'][] = ['done', 'failed', 'cancelled']

// What each job type changes on the server.
const INVALIDATES: Record<Job['type'], (pid: string) => ReadonlyArray<readonly unknown[]>> = {
  analyze: (pid) => [keys.spec(pid), keys.project(pid), keys.projects],
  render: (pid) => [keys.spec(pid), keys.project(pid), keys.history(pid), keys.projects],
  generate: (pid) => [keys.history(pid), keys.project(pid), keys.projects],
  merge: (pid) => [keys.history(pid), keys.project(pid), keys.projects],
}

/** Poll a job every second until it finishes, then refresh what it changed. */
export function useJob(jobId: string | null | undefined, onFinish?: (job: Job) => void) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: keys.job(jobId ?? ''),
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && FINISHED.includes(q.state.data.status) ? false : 1000),
  })
  const reported = useRef<string | null>(null)
  const cb = useRef(onFinish)
  useLayoutEffect(() => {
    cb.current = onFinish
  })
  const job = query.data
  useEffect(() => {
    if (!job || !FINISHED.includes(job.status) || reported.current === job.id) return
    reported.current = job.id
    for (const key of INVALIDATES[job.type](job.project_id)) qc.invalidateQueries({ queryKey: key })
    cb.current?.(job)
  }, [job, qc])
  return query
}

export function cancelJob(jobId: string) {
  return api<void>(`/jobs/${jobId}/cancel`, { method: 'POST' })
}

export const isFinished = (job: Job | undefined) => !!job && FINISHED.includes(job.status)
