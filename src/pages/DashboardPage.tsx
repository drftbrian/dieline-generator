import { useHealth } from '@/api/health'
import { useProjects } from '@/api/projects'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ProjectGrid } from '@/features/projects/ProjectGrid'
import { FigmaLinkImport } from '@/features/upload/FigmaLinkImport'
import { PDFUploadZone } from '@/features/upload/PDFUploadZone'
import { ko } from '@/i18n/ko'

/** Project dashboard: a Figma link is the main way in; PDF upload stays as a small fallback. */
export function DashboardPage() {
  const projects = useProjects()
  const list = projects.data ?? []
  const empty = projects.isSuccess && list.length === 0

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-surface px-4">
        <span className="font-semibold">{ko.appName}</span>
        <ServerStatus />
      </header>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl space-y-8 p-8">
          <h1 className="sr-only">{ko.dashboard.title}</h1>
          <FigmaLinkImport large={empty} />
          <PDFUploadZone large={false} />
          {projects.isPending && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="aspect-[4/3]" />
              ))}
            </div>
          )}
          {projects.error && <ErrorNotice error={projects.error} />}
          {list.length > 0 && <ProjectGrid projects={list} />}
        </div>
      </main>
    </div>
  )
}

function ServerStatus() {
  const { isPending, isError } = useHealth()
  if (isPending) {
    return (
      <Badge>
        <Spinner className="size-3" /> {ko.server.checking}
      </Badge>
    )
  }
  if (isError) {
    return (
      <span title={ko.server.downHint}>
        <Badge tone="danger">{ko.server.down}</Badge>
      </span>
    )
  }
  return <Badge tone="success">{ko.server.ok}</Badge>
}
