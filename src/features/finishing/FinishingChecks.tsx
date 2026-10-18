import { useState } from 'react'
import { finishingPlatesUrl, useFinishingPreflight, useFinishingSweep } from '@/api/finishing'
import type { FinishingWarning } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { useShownVersion } from '@/features/studio/useShownVersion'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { useObjectUrl } from './useObjectUrl'
import { useSaved, useWarnings } from './useSavedFinishing'

const t = ko.studio.finishing.assign

const levelTone: Record<FinishingWarning['level'], string> = {
  error: 'text-red-700',
  warning: 'text-amber-700',
  info: 'text-slate-600',
}
const levelDot: Record<FinishingWarning['level'], string> = {
  error: 'bg-red-500',
  warning: 'bg-amber-500',
  info: 'bg-slate-400',
}

/** One check as a small coloured line: message, then the hint. */
export function WarningLine({ w }: { w: FinishingWarning }) {
  return (
    <li className={cn('flex gap-1.5 text-[11px] leading-snug', levelTone[w.level])}>
      <span aria-hidden className={cn('mt-[5px] size-1.5 shrink-0 rounded-full', levelDot[w.level])} />
      <span className="min-w-0">
        {w.message}
        {w.hint && <span className="block text-ink-muted">{w.hint}</span>}
      </span>
    </li>
  )
}

/** 제조 점검: checks that belong to no single assignment, with error/warning counts for all. */
export function FinishChecks({ projectId }: { projectId: string }) {
  const { hasFinishes } = useSaved(projectId)
  const warnings = useWarnings(projectId)
  if (!hasFinishes) return null
  const all = warnings.data?.warnings ?? []
  const general = all.filter((w) => w.assignment_id == null)
  const errors = all.filter((w) => w.level === 'error').length
  const cautions = all.filter((w) => w.level === 'warning').length
  return (
    <section className="space-y-1.5 rounded-md border border-line p-2.5">
      <div className="flex items-center justify-between gap-2">
        <h5 className="text-xs font-semibold">{t.checks.title}</h5>
        {warnings.data && (
          <span
            className={cn(
              'text-[11px] tabular-nums',
              errors > 0 ? 'text-red-700' : cautions > 0 ? 'text-amber-700' : 'text-ink-muted',
            )}
          >
            {t.checks.counts(errors, cautions)}
          </span>
        )}
      </div>
      {warnings.error ? (
        <ErrorNotice error={warnings.error} />
      ) : !warnings.data ? (
        <p className="flex items-center gap-1.5 text-[11px] text-ink-muted">
          <Spinner className="size-3" /> {t.checks.loading}
        </p>
      ) : general.length === 0 ? (
        <p className="text-[11px] text-ink-muted">{t.checks.none}</p>
      ) : (
        <ul className="space-y-1">
          {general.map((w, i) => (
            <WarningLine key={`${w.code}-${i}`} w={w} />
          ))}
        </ul>
      )}
      {errors > 0 && <p className="text-[11px] text-ink-muted">{t.checks.nonBlocking}</p>}
      <p className="text-[10px] text-ink-muted">{t.checks.note}</p>
    </section>
  )
}

/** 판 파일 내려받기: one vector PDF per finish + the spec JSON, zipped, for the saved revision. */
export function FinishPlates({ projectId }: { projectId: string }) {
  const { revision, hasFinishes, pending } = useSaved(projectId)
  const pre = useFinishingPreflight(projectId, revision, hasFinishes)
  if (!hasFinishes || revision <= 0) return null
  const link =
    'inline-flex h-8 w-full items-center justify-center rounded-md border px-3 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'
  const issues = pre.data?.issues ?? []
  return (
    <section className="space-y-1.5 rounded-md border border-line p-2.5">
      {pre.isPending ? (
        <p className="text-[11px] text-ink-muted">{t.plates.checking}</p>
      ) : pre.data && !pre.data.exact ? (
        <div className="space-y-1.5 rounded-md border border-red-200 bg-red-50 p-2" role="alert">
          <p className="text-xs font-medium text-red-800">{t.plates.blockedTitle}</p>
          <p className="text-[11px] text-red-800">{t.plates.blockedBody}</p>
          <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-red-800">
            {issues.map((i) => (
              <li key={`${i.assignment_id}:${i.target}`}>{t.plates.issue(i.name, i.message)}</li>
            ))}
          </ul>
          <a
            href={finishingPlatesUrl(projectId, revision, true)}
            download
            className={cn(link, 'border-red-300 bg-surface text-red-800 hover:bg-red-100')}
          >
            {t.plates.draft}
          </a>
        </div>
      ) : (
        <a
          href={finishingPlatesUrl(projectId, revision)}
          download
          className={cn(link, 'border-line bg-surface hover:bg-canvas')}
        >
          {t.plates.download}
        </a>
      )}
      <p className="text-[11px] text-ink-muted">{t.plates.body}</p>
      {pending && <p className="text-[11px] text-amber-700">{t.plates.unsaved}</p>}
    </section>
  )
}

/** 빛 움직여 보기: on demand, an animated GIF of the finished area under a moving light. */
export function FinishSweep({ projectId }: { projectId: string }) {
  const version = useShownVersion(projectId)
  const { revision, hasFinishes, pending } = useSaved(projectId)
  const light = useCanvasStore((s) => s.finishLight)
  // Same rule as the canvas overlay: a finished flat render that knows its frame, without baked finishes.
  const usable = !!version && version.kind === 'flat' && version.status === 'done' && !!version.frame
  const blocked = !usable
    ? t.save.noVersion
    : version.finishing
      ? t.save.notSource
      : pending
        ? t.save.unsaved
        : null
  const key = `${version?.id}:${revision}:${light}`
  const [wanted, setWanted] = useState<string | null>(null)
  const sweep = useFinishingSweep(projectId, version?.id ?? null, revision, light, !blocked && wanted === key)
  const url = useObjectUrl(!blocked ? sweep.data : null)
  if (!hasFinishes) return null

  const loading = sweep.isFetching
  return (
    <section className="space-y-2 rounded-md border border-line p-2.5">
      <div className="flex items-center justify-between gap-2">
        <h5 className="text-xs font-semibold">{t.sweep.title}</h5>
        <span className="text-[11px] text-ink-muted">{t.sweep.light(ko.studio.finishing.view.lights[light])}</span>
      </div>
      <p className="text-[11px] text-ink-muted">{t.sweep.body}</p>
      <Button
        variant="secondary"
        className="h-8 w-full justify-center text-xs"
        disabled={!!blocked || loading}
        onClick={() => {
          if (wanted === key) void sweep.refetch()
          else setWanted(key)
        }}
      >
        {url ? t.sweep.again : t.sweep.run}
      </Button>
      {blocked && <p className="text-[11px] text-ink-muted">{blocked}</p>}
      {loading && (
        <p className="flex items-center gap-1.5 text-[11px] text-ink-muted" role="status">
          <Spinner className="size-3" /> {t.sweep.loading}
        </p>
      )}
      {!blocked && sweep.error && !loading && <ErrorNotice error={sweep.error} />}
      {url && !loading && (
        <img src={url} alt={t.sweep.alt} className="block h-auto w-full max-w-full rounded-md border border-line" />
      )}
    </section>
  )
}
