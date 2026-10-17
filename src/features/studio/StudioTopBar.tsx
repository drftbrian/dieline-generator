import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useDeleteProject, useRenameProject } from '@/api/projects'
import { Button } from '@/components/ui/Button'
import { SegmentedControl } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Dialog, Popover, Tooltip } from '@/components/ui/overlays'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { type ViewMode, useCanvasStore } from '@/stores/useCanvasStore'
import { StudioShortcuts } from './StudioShortcuts'
import type { StudioRegionProps } from './types'
import { useShownVersion } from './useShownVersion'

const t = ko.studio.topbar

function ProjectMenu({ project }: StudioRegionProps) {
  const navigate = useNavigate()
  const rename = useRenameProject(project.id)
  const remove = useDeleteProject()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(project.name)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const commit = () => {
    setEditing(false)
    const next = name.trim()
    if (next && next !== project.name) rename.mutate(next)
    else setName(project.name)
  }

  if (editing) {
    return (
      <input
        autoFocus
        aria-label={t.rename}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') {
            setName(project.name)
            setEditing(false)
          }
        }}
        className="h-8 w-56 rounded-md border border-accent bg-surface px-2 text-sm font-semibold outline-none"
      />
    )
  }

  const item = 'block w-full rounded px-2 py-1.5 text-left hover:bg-canvas'
  return (
    <>
      <Popover
        open={open}
        onOpenChange={setOpen}
        align="start"
        trigger={
          <button type="button" aria-label={t.menu} className="flex h-8 max-w-64 items-center gap-1.5 rounded-md px-2 font-semibold hover:bg-canvas">
            <span aria-hidden>◧</span>
            <span className="truncate">{project.name}</span>
            <span className="text-ink-muted">▾</span>
          </button>
        }
      >
        <div className="flex min-w-40 flex-col">
          <button type="button" className={item} onClick={() => (setOpen(false), setName(project.name), setEditing(true))}>
            {t.rename}
          </button>
          <button type="button" className={item} onClick={() => navigate('/projects')}>
            {t.toDashboard}
          </button>
          <button type="button" className={cn(item, 'text-red-700')} onClick={() => (setOpen(false), setConfirmDelete(true))}>
            {t.delete}
          </button>
        </div>
      </Popover>
      <Dialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t.deleteTitle}
        description={t.deleteBody}
        footer={
          <>
            <Button onClick={() => setConfirmDelete(false)}>{ko.actions.cancel}</Button>
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              disabled={remove.isPending}
              onClick={() => remove.mutate(project.id, { onSuccess: () => navigate('/projects') })}
            >
              {t.delete}
            </Button>
          </>
        }
      >
        {remove.error && <ErrorNotice error={remove.error} />}
      </Dialog>
      {rename.error && <span className="sr-only">{String(rename.error)}</span>}
    </>
  )
}

/** Top bar: project menu, the three steps, and a PNG download of what is on screen. */
export function StudioTopBar(props: StudioRegionProps) {
  const view = useCanvasStore((s) => s.view)
  const setView = useCanvasStore((s) => s.setView)
  const shown = useShownVersion(props.project.id)
  const step = (n: string, label: string) => (
    <>
      <span className="mr-1 text-xs text-ink-muted">{n}</span>
      {label}
    </>
  )

  return (
    <header className="flex h-12 items-center gap-3 border-b border-line bg-surface px-3">
      <StudioShortcuts />
      <ProjectMenu {...props} />
      <div className="flex flex-1 items-center justify-center">
        <SegmentedControl<ViewMode>
          label={t.viewGroup}
          value={view}
          onChange={setView}
          options={[
            { value: 'source', label: step('①', t.views.source), title: '1' },
            { value: 'flat', label: step('②', t.views.flat), title: '2' },
            { value: 'merge', label: step('③', t.views.merge), title: '3' },
          ]}
        />
      </div>
      {shown?.download_url ? (
        <a
          href={shown.download_url}
          download
          title={t.downloadTitle}
          className="inline-flex h-8 items-center rounded-md border border-line bg-surface px-3 text-sm font-medium hover:bg-canvas focus-visible:outline-2 focus-visible:outline-accent"
        >
          {t.download}
        </a>
      ) : (
        <Tooltip content={t.downloadDisabled}>
          <span>
            <Button className="h-8" disabled>
              {t.download}
            </Button>
          </span>
        </Tooltip>
      )}
    </header>
  )
}
