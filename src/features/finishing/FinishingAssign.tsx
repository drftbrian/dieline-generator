import { useFinishingCatalog } from '@/api/finishing'
import type { Asset, Panel } from '@/api/types'
import { IconButton } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { MOD_LABEL } from '@/lib/shortcuts'
import { cn } from '@/lib/cn'
import {
  finishingRedo,
  finishingUndo,
  isDirty,
  useFinishingHistory,
  useFinishingStore,
} from '@/stores/useFinishingStore'
import { AppliedList } from './AppliedList'
import { FinishPicker } from './FinishPicker'

const t = ko.studio.finishing.assign

/** Milestone 3: choose a finish for the selection / sheet / panels and manage the applied list. */
export function FinishingAssign({
  projectId,
  selected,
  byId,
  panels,
}: {
  projectId: string
  selected: string[]
  byId: Map<string, Asset>
  panels: Panel[]
}) {
  const catalog = useFinishingCatalog()
  const ready = useFinishingStore((s) => s.projectId === projectId && s.status !== 'loading')
  const loadError = useFinishingStore((s) => (s.projectId !== projectId && s.status === 'error' ? s.error : null))

  return (
    <div className="space-y-3 border-t border-line pt-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">{t.title}</h4>
        <HistoryButtons disabled={!ready} />
      </div>
      <SaveStatus projectId={projectId} />
      <p className="rounded-md bg-violet-50 px-2.5 py-2 text-[11px] text-violet-900">{t.placeholder}</p>

      {catalog.error ? (
        <ErrorNotice error={catalog.error} />
      ) : loadError ? (
        <p className="rounded-md bg-red-50 p-2.5 text-xs text-red-800">{loadError}</p>
      ) : !catalog.data || !ready ? (
        <p className="flex items-center gap-1.5 text-xs text-ink-muted">
          <Spinner className="size-3" /> {t.catalogLoading}
        </p>
      ) : (
        <>
          <FinishPicker catalog={catalog.data} selected={selected} panels={panels} />
          <AppliedList projectId={projectId} catalog={catalog.data} byId={byId} panels={panels} selected={selected} />
        </>
      )}
    </div>
  )
}

function HistoryButtons({ disabled }: { disabled: boolean }) {
  const { canUndo, canRedo } = useFinishingHistory()
  return (
    <div className="flex items-center">
      <IconButton
        label={`${t.undo} (${MOD_LABEL}Z)`}
        className="size-7"
        disabled={disabled || !canUndo}
        onClick={finishingUndo}
      >
        ↶
      </IconButton>
      <IconButton
        label={`${t.redo} (⇧${MOD_LABEL}Z)`}
        className="size-7"
        disabled={disabled || !canRedo}
        onClick={finishingRedo}
      >
        ↷
      </IconButton>
    </div>
  )
}

function SaveStatus({ projectId }: { projectId: string }) {
  const mine = useFinishingStore((s) => s.projectId === projectId)
  const status = useFinishingStore((s) => s.status)
  const error = useFinishingStore((s) => s.error)
  const revision = useFinishingStore((s) => s.saved.revision)
  const dirty = useFinishingStore(isDirty)
  const s = t.status
  if (!mine) return null
  const text =
    status === 'loading'
      ? s.loading
      : status === 'saving'
        ? s.saving
        : status === 'error'
          ? s.error(error ?? s.unsaved)
          : dirty
            ? s.pending
            : s.saved(revision)
  return (
    <div className="flex items-center gap-2 text-[11px]" role="status" aria-live="polite">
      <span
        aria-hidden
        className={cn(
          'size-1.5 shrink-0 rounded-full',
          status === 'error' ? 'bg-red-500' : status === 'saving' || dirty ? 'bg-amber-500' : 'bg-emerald-500',
        )}
      />
      <span className={cn('min-w-0 flex-1', status === 'error' ? 'text-red-700' : 'text-ink-muted')}>{text}</span>
      {status === 'error' && (
        <button
          type="button"
          className="shrink-0 text-ink-muted underline underline-offset-2 hover:text-ink"
          onClick={() => useFinishingStore.getState().retry()}
        >
          {s.retry}
        </button>
      )}
    </div>
  )
}
