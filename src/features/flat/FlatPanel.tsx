import { useStartFlat } from '@/api/generate'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { JobStages, StepPanel, VerifyResult, VersionError } from '@/features/studio/StepPanel'
import type { StudioRegionProps } from '@/features/studio/types'
import { isEnhanceable, isMergeSource, pick, useVersions } from '@/features/studio/versions'
import { ko } from '@/i18n/ko'
import { FinishingSection } from '@/features/finishing/FinishingSection'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { EnhanceFailure, EnhanceResult, EnhanceStart } from './EnhancePanel'

const t = ko.studio.flat

/**
 * ② 플랫 렌더: one flat, unfolded photoreal render in the fixed look, plus the optional
 * AI 재질 보정 of a finished code render (always a new version; the source never changes).
 */
export function FlatPanel({ project }: StudioRegionProps) {
  const pid = project.id
  const start = useStartFlat(pid)
  const { versions, flats } = useVersions(pid)
  const flatId = useCanvasStore((s) => s.flatId)
  const onFlat = useCanvasStore((s) => s.view === 'flat')
  const selected = pick(flats, flatId)
  const all = versions.filter((v) => v.kind === 'flat')
  const running = all.filter((v) => v.status === 'running')
  const last = all[all.length - 1]

  return (
    <StepPanel title={t.title} intro={t.intro}>
      <Button
        variant="primary"
        className="h-10 w-full justify-center"
        disabled={start.isPending}
        onClick={() => start.mutate(undefined, { onSuccess: () => useCanvasStore.getState().setView('flat') })}
      >
        {start.isPending ? (
          <>
            <Spinner className="size-3.5" /> {t.starting}
          </>
        ) : selected ? (
          t.regenerate
        ) : (
          t.generate
        )}
      </Button>
      {start.error && <ErrorNotice error={start.error} />}

      {running.map((v) => (
        <JobStages key={v.id} version={v} />
      ))}
      {last?.status === 'failed' &&
        (last.enhancement ? <EnhanceFailure version={last} /> : <VersionError version={last} />)}

      {selected ? (
        <>
          <div className="space-y-2">
            <p className="text-xs font-medium text-ink-muted">{t.selected(selected.number)}</p>
            {selected.legacy ? (
              <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-800">{t.legacy}</p>
            ) : (
              <VerifyResult verify={selected.verify} />
            )}
            <Button
              className="w-full justify-center"
              disabled={!isMergeSource(selected)}
              onClick={() => useCanvasStore.getState().mergeWith(selected.id)}
            >
              {t.useForMerge}
            </Button>
          </div>
          {onFlat && <FinishingSection projectId={pid} hasFrame={!!selected.frame} />}
          {selected.enhancement ? (
            <EnhanceResult
              key={selected.id}
              projectId={pid}
              version={selected}
              versions={versions}
              busy={running.length > 0}
            />
          ) : (
            isEnhanceable(selected) && (
              <EnhanceStart key={selected.id} projectId={pid} source={selected} busy={running.length > 0} />
            )
          )}
        </>
      ) : (
        running.length === 0 && <p className="text-xs text-ink-muted">{t.none}</p>
      )}
    </StepPanel>
  )
}
