import type { ReactNode } from 'react'
import { ApiError } from '@/api/client'
import { useJob } from '@/api/jobs'
import type { Verify, Version } from '@/api/types'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { kindLabel } from './versions'

const g = ko.studio.generation
const v = ko.studio.flat.verify

/** Right-hand panel shell shared by ② and ③. */
export function StepPanel({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-y-auto border-l border-line bg-surface">
      <div className="space-y-1 border-b border-line p-4">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-ink-muted">{intro}</p>
      </div>
      <div className="flex flex-col gap-4 p-4 text-sm">{children}</div>
    </aside>
  )
}

const MARK: Record<string, string> = { done: '✓', running: '…', failed: '✗', skipped: '–', pending: '○' }

/** Stage-by-stage progress of a running version's job. */
export function JobStages({ version }: { version: Version }) {
  const { data: job } = useJob(version.job_id)
  return (
    <div className="rounded-md border border-line bg-canvas/60 p-3 text-xs">
      <p className="mb-1.5 flex items-center gap-1.5 font-medium">
        <Spinner className="size-3" /> v{version.number} {kindLabel(version)}
      </p>
      <ul className="space-y-0.5">
        {(job?.stages ?? []).map((s) => (
          <li key={s.key} className={cn('flex gap-1.5', s.status === 'running' ? 'text-ink' : 'text-ink-muted')}>
            <span className="w-3 text-center">{MARK[s.status] ?? '○'}</span>
            {g.stages[s.key] ?? s.key}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Why a version failed, in the shared error style. */
export function VersionError({ version }: { version: Version }) {
  if (!version.error) return null
  return <ErrorNotice error={new ApiError(422, version.error as ConstructorParameters<typeof ApiError>[1])} />
}

const pct = (x: number) => `${(x * 100).toFixed(x < 0.01 ? 2 : 1)}%`

/** The verify gate's verdict: the print must match the original. */
export function VerifyResult({ verify }: { verify: Verify | null }) {
  if (!verify) return null
  return (
    <div
      className={cn(
        'rounded-md border p-3 text-xs',
        verify.match ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-red-200 bg-red-50 text-red-900',
      )}
    >
      <p className="font-medium">{v.title}</p>
      <p className="mt-0.5">{verify.match ? v.ok : v.bad}</p>
      <p className="mt-1 opacity-80">
        {v.changed(pct(verify.changed_ratio))}
        {verify.detail_match != null && ` · ${v.detail(pct(verify.detail_match))}`}
        {verify.colour_delta_e_median != null && ` · ${v.colour(verify.colour_delta_e_median.toFixed(1))}`}
      </p>
    </div>
  )
}
