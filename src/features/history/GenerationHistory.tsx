import { useState } from 'react'
import { useDeleteVersion } from '@/api/history'
import type { Version } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { IconButton } from '@/components/ui/controls'
import { Dialog } from '@/components/ui/overlays'
import { Spinner } from '@/components/ui/Spinner'
import type { StudioRegionProps } from '@/features/studio/types'
import { useShownVersion } from '@/features/studio/useShownVersion'
import { useVersions } from '@/features/studio/versions'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { toast } from '@/stores/useToastStore'
import { useUiStore } from '@/stores/useUiStore'

const t = ko.studio.history

/** Bottom strip of every version: ② flat renders and ③ merges, oldest first. */
export function GenerationHistory({ project }: StudioRegionProps) {
  const pid = project.id
  const collapsed = useUiStore((s) => s.historyCollapsed)
  const toggle = useUiStore((s) => s.toggleHistory)
  const shown = useShownVersion(pid)
  const { versions } = useVersions(pid)
  const del = useDeleteVersion(pid)
  const [deleting, setDeleting] = useState<Version | null>(null)

  const remove = (v: Version) =>
    del.mutate(v.id, {
      onSuccess: () => {
        useCanvasStore.getState().forget(v.id)
        setDeleting(null)
        toast({ message: t.deleted(v.number) })
      },
      onError: (e) => toast({ message: e.message, tone: 'danger' }),
    })

  if (collapsed) {
    return (
      <div className="flex h-6 items-center justify-center border-t border-line bg-surface">
        <button type="button" className="px-3 text-[11px] text-ink-muted hover:text-ink" onClick={toggle} aria-label={t.expand}>
          ⌃ {t.title} ({versions.length})
        </button>
      </div>
    )
  }

  return (
    <section aria-label={t.title} className="flex h-28 border-t border-line bg-surface">
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto px-3">
        <span className="mr-1 shrink-0 text-[11px] font-semibold tracking-wide text-ink-muted">{t.title}</span>
        {versions.length === 0 && <span className="text-xs text-ink-muted">{t.empty}</span>}
        {versions.map((v) => (
          <HistoryCard
            key={v.id}
            version={v}
            selected={shown?.id === v.id}
            onOpen={() => v.status === 'done' && useCanvasStore.getState().showVersion(v.id, v.kind)}
            onDelete={() => setDeleting(v)}
          />
        ))}
      </div>
      <div className="flex shrink-0 items-start border-l border-line px-2 pt-2">
        <IconButton label={t.collapse} onClick={toggle}>
          ⌄
        </IconButton>
      </div>
      <Dialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={deleting ? t.deleteTitle(deleting.number) : ''}
        description={t.deleteBody}
        footer={
          <>
            <Button onClick={() => setDeleting(null)}>{ko.actions.cancel}</Button>
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              disabled={del.isPending}
              onClick={() => deleting && remove(deleting)}
            >
              {t.delete}
            </Button>
          </>
        }
      />
    </section>
  )
}

function HistoryCard({
  version: v,
  selected,
  onOpen,
  onDelete,
}: {
  version: Version
  selected: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  const verifyFailed = v.status === 'done' && v.verify && !v.verify.match
  const badge = v.enhancement
    ? { text: t.enhanced, tone: 'bg-violet-50 text-violet-700' }
    : v.kind === 'flat'
      ? { text: t.flat, tone: 'bg-canvas text-ink-muted' }
      : { text: t.merge, tone: 'bg-accent/10 text-accent' }
  const title = [`v${v.number}`, formatDateTime(v.created_at), v.provider_label, v.error?.message].filter(Boolean).join(' · ')
  return (
    <div className="group relative shrink-0">
      <button
        type="button"
        onClick={onOpen}
        title={v.legacy ? `${title}\n${t.legacyTitle}` : title}
        aria-label={`v${v.number} ${badge.text}`}
        className={cn(
          'flex h-[84px] w-24 flex-col overflow-hidden rounded-md border bg-surface text-left',
          'focus-visible:outline-2 focus-visible:outline-accent',
          selected ? 'border-accent ring-2 ring-accent/30' : v.status === 'failed' ? 'border-amber-300' : 'border-line',
        )}
      >
        {v.status === 'running' ? (
          <div className="flex h-14 w-full items-center justify-center bg-canvas">
            <Spinner className="size-4 text-ink-muted" />
          </div>
        ) : v.thumb_url ? (
          <img src={v.thumb_url} alt="" className="h-14 w-full bg-black object-cover" />
        ) : (
          <div className="flex h-14 w-full items-center justify-center bg-amber-50 text-amber-700">⚠</div>
        )}
        <span className="flex flex-wrap items-center gap-1 px-1.5 py-0.5 text-[11px] font-medium">
          v{v.number}
          <span className={cn('rounded px-1 font-normal', badge.tone)}>{badge.text}</span>
          {v.legacy && <span className="rounded bg-amber-50 px-1 font-normal text-amber-700">{t.legacy}</span>}
          {v.status === 'running' && <span className="font-normal text-ink-muted">{t.running}</span>}
          {v.status === 'failed' && <span className="font-normal text-amber-700">{t.failed}</span>}
          {verifyFailed && <span className="font-normal text-red-600">{t.verifyFail}</span>}
        </span>
      </button>
      {v.status !== 'running' && (
        <button
          type="button"
          aria-label={`v${v.number} ${t.delete}`}
          title={t.delete}
          onClick={onDelete}
          className="absolute top-1 right-1 hidden size-5 items-center justify-center rounded bg-surface/90 text-[11px] text-ink-muted shadow-sm group-focus-within:flex group-hover:flex hover:text-red-700"
        >
          ✕
        </button>
      )}
    </div>
  )
}
