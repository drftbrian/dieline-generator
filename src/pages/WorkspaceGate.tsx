import { Navigate, useParams } from 'react-router'
import { useProject } from '@/api/projects'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { routeForStatus } from '@/lib/routes'

export function WorkspaceGate() {
  const { id } = useParams()
  const { data, error } = useProject(id)
  if (error) {
    return (
      <main className="flex h-full items-center justify-center p-8">
        <ErrorNotice error={error} />
      </main>
    )
  }
  if (!data) {
    return (
      <main className="flex h-full items-center justify-center gap-2 text-sm text-ink-muted">
        <Spinner /> {ko.pages.gate}
      </main>
    )
  }
  return <Navigate to={routeForStatus(data.status)} replace />
}
