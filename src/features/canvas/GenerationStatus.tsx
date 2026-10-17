import { useEffect, useState } from 'react'
import { cancelJob, useJob } from '@/api/jobs'
import type { Job, Version } from '@/api/types'
import { ProgressBar } from '@/components/ui/controls'
import { useVersions } from '@/features/studio/versions'
import { ko } from '@/i18n/ko'
import { formatDuration } from '@/lib/format'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { toast } from '@/stores/useToastStore'

const t = ko.studio.generation

/**
 * Tracks every running generation: a thin progress bar + status chip on the canvas, then
 * an automatic switch to the result (if the user hasn't touched the canvas since) or a toast.
 */
export function GenerationStatus({ projectId }: { projectId: string }) {
  const { versions } = useVersions(projectId)
  // Keep watching a job after history flips it to done, so its completion is still reported.
  const [watching, setWatching] = useState<Version[]>([])
  const running = versions.filter((v) => v.status === 'running' && v.job_id)
  const missing = running.filter((v) => !watching.some((w) => w.id === v.id))
  if (missing.length) setWatching((w) => [...w, ...missing.filter((m) => !w.some((x) => x.id === m.id))])

  if (!watching.length) return null
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex flex-col items-center gap-1">
      {watching.map((v) => (
        <RunningGeneration key={v.id} version={v} onDone={() => setWatching((w) => w.filter((x) => x.id !== v.id))} />
      ))}
    </div>
  )
}

function RunningGeneration({ version, onDone }: { version: Version; onDone: () => void }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const { data: job } = useJob(version.job_id, (j: Job) => {
    onDone()
    const show = () => useCanvasStore.getState().showVersion(version.id, version.kind)
    if (j.status === 'done') {
      if (useCanvasStore.getState().interactedAt < Date.parse(version.created_at)) show()
      else toast({ message: t.done(version.number), tone: 'success', actions: [{ label: t.view, onClick: show }] })
    } else if (j.status === 'failed') {
      toast({ message: t.failed(j.error?.message ?? '알 수 없는 오류'), tone: 'danger', duration: 0 })
    }
  })

  const stage = job?.stages.find((s) => s.status === 'running')?.key
  const elapsed = Math.max(0, (now - Date.parse(version.created_at)) / 1000)
  return (
    <div className="pointer-events-auto w-full">
      <ProgressBar value={job ? Math.max(0.05, job.progress) : null} className="h-0.5 rounded-none" />
      <div className="mt-2 flex justify-center">
        <div aria-live="polite" className="flex items-center gap-2 rounded-full border border-line bg-surface/95 px-3 py-1 text-xs shadow-sm">
          <span className="size-1.5 animate-pulse rounded-full bg-prov-generated" />
          <span className="font-medium">{t.running(t.kinds[version.kind], formatDuration(elapsed))}</span>
          {stage && <span className="text-ink-muted">· {t.stages[stage] ?? stage}</span>}
          {version.job_id && (
            <button
              type="button"
              className="ml-1 text-ink-muted hover:text-ink"
              onClick={() => version.job_id && void cancelJob(version.job_id)}
            >
              {t.cancel}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
