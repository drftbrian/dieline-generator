import { Navigate, useParams } from 'react-router'
import { useProject } from '@/api/projects'
import { useSpecification } from '@/api/spec'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { MockupCanvas } from '@/features/canvas/MockupCanvas'
import { FinishingSync } from '@/features/finishing/FinishingSync'
import { FlatPanel } from '@/features/flat/FlatPanel'
import { GenerationHistory } from '@/features/history/GenerationHistory'
import { SourceInspector } from '@/features/inspector/SourceInspector'
import { MergePanel } from '@/features/merge/MergePanel'
import { StudioTopBar } from '@/features/studio/StudioTopBar'
import { routeForStatus } from '@/lib/routes'
import { useCanvasStore } from '@/stores/useCanvasStore'

/**
 * Studio layout: top bar (steps + download) / left source facts / center canvas /
 * right panel for the current step (② flat render or ③ reference merge) / bottom history.
 */
export function StudioPage() {
  const { id = '' } = useParams()
  const project = useProject(id)
  const ready = project.data?.status === 'ready'
  const spec = useSpecification(id, ready)
  const merge = useCanvasStore((s) => s.view === 'merge')

  if (project.error || spec.error) {
    return (
      <main className="flex h-full items-center justify-center p-8">
        <ErrorNotice error={project.error ?? spec.error} />
      </main>
    )
  }
  if (project.data && !ready) return <Navigate to={`../${routeForStatus(project.data.status)}`} replace />
  if (!project.data || !spec.data) {
    return (
      <main className="flex h-full items-center justify-center text-ink-muted">
        <Spinner />
      </main>
    )
  }

  const props = { project: project.data, spec: spec.data }
  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr_auto] overflow-hidden bg-canvas">
      <StudioTopBar {...props} />
      <FinishingSync key={project.data.id} projectId={project.data.id} />
      <div className="flex min-h-0">
        <SourceInspector {...props} />
        <main className="relative min-w-0 flex-1">
          <MockupCanvas {...props} />
        </main>
        {merge ? <MergePanel {...props} /> : <FlatPanel {...props} />}
      </div>
      <GenerationHistory {...props} />
    </div>
  )
}
