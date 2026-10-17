import type { Job, JobStage } from '@/api/types'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'

type StageKey = keyof typeof ko.analyze.stages
const JOB_STAGES = ['validate', 'preview', 'extract', 'separations', 'structure', 'render']
const label = (key: string, done: boolean) =>
  (done ? ko.analyze.stageDone : ko.analyze.stages)[key as StageKey] ?? key

function summaryText(stage: JobStage): string | null {
  const s = stage.summary as Record<string, unknown> | null | undefined
  if (!s) return null
  if (stage.key === 'extract') {
    return ko.analyze.extractSummary(Number(s.vectors ?? 0), Number(s.images ?? 0), Number(s.text ?? 0))
  }
  if (stage.key === 'structure') return ko.analyze.structureSummary(Number(s.pending ?? 0))
  if (stage.key === 'validate' && Number(s.page_count ?? 1) > 1) return `${s.page_count}페이지`
  return null
}

/**
 * Seven-step progress list: the upload step (already done when this screen opens)
 * followed by the analysis job's stages. Each stage can fail on its own.
 */
export function AnalysisProgress({ job }: { job: Job | undefined }) {
  const stages: JobStage[] = job?.stages ?? JOB_STAGES.map((key) => ({ key, status: 'pending' }))
  const rows: JobStage[] = [{ key: 'upload', status: 'done' }, ...stages]
  const current = rows.find((r) => r.status === 'running')
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <ol className="space-y-2.5" aria-live="polite">
        {rows.map((r) => {
          const summary = summaryText(r)
          return (
            <li key={r.key} className="flex items-start gap-3 text-sm">
              <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center">
                {r.status === 'running' ? (
                  <Spinner className="size-3.5 text-accent" />
                ) : r.status === 'done' ? (
                  <span className="text-emerald-600" aria-hidden>
                    ✓
                  </span>
                ) : r.status === 'failed' ? (
                  <span className="text-red-600" aria-hidden>
                    ✕
                  </span>
                ) : (
                  <span className="size-1.5 rounded-full bg-line" aria-hidden />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={cn(
                    r.status === 'pending' || r.status === 'skipped' ? 'text-ink-muted' : 'text-ink',
                    r.status === 'running' && 'font-medium',
                  )}
                >
                  {label(r.key, r.status === 'done')}
                  {r.status === 'skipped' && ` · ${ko.analyze.skipped}`}
                  {r.status === 'failed' && ` · ${ko.analyze.failedStage}`}
                </span>
                {summary && <span className="ml-2 text-xs text-ink-muted">{summary}</span>}
                {r.status === 'failed' && r.message && (
                  <span className="block text-xs text-red-700">{r.message}</span>
                )}
              </span>
            </li>
          )
        })}
      </ol>
      {current && <span className="sr-only">{label(current.key, false)}</span>}
    </div>
  )
}
