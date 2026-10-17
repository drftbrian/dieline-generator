import { DropdownMenu } from 'radix-ui'
import { useState } from 'react'
import { Link } from 'react-router'
import { useDeleteProject, useRenameProject } from '@/api/projects'
import type { Project } from '@/api/types'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Dialog } from '@/components/ui/overlays'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { timeAgo } from '@/lib/format'
import { toast } from '@/stores/useToastStore'

export function StatusBadge({ project }: { project: Project }) {
  const s = project.status
  const label = ko.project.status[s]
  if (s === 'uploading' || s === 'analyzing' || s === 'rendering') {
    return (
      <Badge>
        <Spinner className="size-3" /> {label}
      </Badge>
    )
  }
  if (s === 'needs_review' || s === 'needs_page') return <Badge tone="warning">{label}</Badge>
  if (s === 'failed') return <Badge tone="danger">{label}</Badge>
  if (project.latest_version) return <Badge>v{project.latest_version}</Badge>
  return <Badge tone="success">{label}</Badge>
}

export function ProjectCard({ project }: { project: Project }) {
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  return (
    <div className="group relative overflow-hidden rounded-lg border border-line bg-surface transition-shadow hover:shadow-md">
      <Link to={`/projects/${project.id}`} className="block focus-visible:outline-2 focus-visible:outline-accent">
        <div className="flex aspect-[4/3] items-center justify-center bg-canvas">
          {project.thumbnail_url ? (
            <img src={project.thumbnail_url} alt={`${project.name} 미리보기`} className="h-full w-full object-contain" />
          ) : (
            <span className="text-xs text-ink-muted">{ko.project.noThumb}</span>
          )}
        </div>
        <div className="space-y-1 p-3 pr-10">
          <p className="truncate text-sm font-medium" title={project.name}>
            {project.name}
          </p>
          <div className="flex items-center gap-2 text-xs text-ink-muted">
            <StatusBadge project={project} />
            {project.figma && <Badge>{ko.figma.badge}</Badge>}
            <span>{timeAgo(project.updated_at)}</span>
          </div>
        </div>
      </Link>
      <div className="absolute right-2 bottom-3">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            aria-label={ko.project.menu}
            className="inline-flex size-7 items-center justify-center rounded-md text-ink-muted hover:bg-canvas hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
          >
            ⋯
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={4}
              className="z-50 min-w-36 rounded-lg border border-line bg-surface p-1 text-sm shadow-lg"
            >
              <MenuItem onSelect={() => setRenaming(true)}>{ko.project.rename}</MenuItem>
              <DropdownMenu.Separator className="my-1 h-px bg-line" />
              <MenuItem danger onSelect={() => setDeleting(true)}>
                {ko.project.delete}
              </MenuItem>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
      <RenameDialog project={project} open={renaming} onOpenChange={setRenaming} />
      <DeleteDialog project={project} open={deleting} onOpenChange={setDeleting} />
    </div>
  )
}

function MenuItem({
  children,
  onSelect,
  danger,
  disabled,
}: {
  children: React.ReactNode
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
}) {
  return (
    <DropdownMenu.Item
      disabled={disabled}
      onSelect={onSelect}
      className={`cursor-pointer rounded px-2 py-1.5 outline-none data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40 data-[highlighted]:bg-canvas ${danger ? 'text-red-700' : ''}`}
    >
      {children}
    </DropdownMenu.Item>
  )
}

function RenameDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const rename = useRenameProject(project.id)
  const [name, setName] = useState(project.name)
  const submit = () => {
    const n = name.trim()
    if (!n || n === project.name) return onOpenChange(false)
    rename.mutate(n, { onSuccess: () => onOpenChange(false) })
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (o) setName(project.name)
        rename.reset()
        onOpenChange(o)
      }}
      title={ko.project.renameTitle}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{ko.actions.cancel}</Button>
          <Button variant="primary" onClick={submit} disabled={rename.isPending}>
            {ko.project.renameSave}
          </Button>
        </>
      }
    >
      <input
        autoFocus
        aria-label={ko.project.renameTitle}
        value={name}
        maxLength={120}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        className="h-9 w-full rounded-md border border-line px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent"
      />
      <ErrorNotice error={rename.error} className="mt-2" />
    </Dialog>
  )
}

function DeleteDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const del = useDeleteProject()
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={ko.project.deleteTitle}
      description={ko.project.deleteBody(project.name)}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{ko.actions.cancel}</Button>
          <Button
            className="bg-red-600 text-white hover:bg-red-700"
            disabled={del.isPending}
            onClick={() =>
              del.mutate(project.id, {
                onSuccess: () => {
                  onOpenChange(false)
                  toast({ message: ko.project.deleted })
                },
              })
            }
          >
            {ko.project.deleteConfirm}
          </Button>
        </>
      }
    >
      {del.error ? <ErrorNotice error={del.error} /> : null}
    </Dialog>
  )
}
