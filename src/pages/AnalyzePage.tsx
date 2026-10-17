import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useJob } from '@/api/jobs'
import { useProject } from '@/api/projects'
import { sourceFileUrl, useAnalyze } from '@/api/source'
import { useSpecification } from '@/api/spec'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { AnalysisProgress } from '@/features/analysis/AnalysisProgress'
import { FlattenedPdfCard } from '@/features/analysis/FlattenedPdfCard'
import { PageSelectDialog } from '@/features/analysis/PageSelectDialog'
import { SeparationReport } from '@/features/analysis/SeparationReport'
import { SourcePreview } from '@/features/analysis/SourcePreview'
import { StatusBadge } from '@/features/projects/ProjectCard'
import { ko } from '@/i18n/ko'

const MM_TO_PT = 72 / 25.4
const NAV_DELAY_MS = 1200

/** Upload & analyze progress. Branches to Structural Review or the Studio. */
export function AnalyzePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const project = useProject(id)
  const p = project.data
  const analyze = useAnalyze(id)

  // Follow the project's active analysis job; keep showing the last one after it finishes.
  const [jobId, setJobId] = useState<string | null>(null)
  const active = p?.active_job_id ?? null
  if (active && active !== jobId) setJobId(active)
  const job = useJob(jobId).data

  const structureDone = job?.stages.some((s) => s.key === 'structure' && s.status === 'done')
  const specReady = !!p && (['needs_review', 'ready', 'rendering'].includes(p.status) || !!structureDone)
  const spec = useSpecification(id, specReady)

  const status = p?.status
  const flattened = spec.data?.flattened ?? false

  useEffect(() => {
    if (status === 'needs_review' && spec.data && !flattened) {
      const t = setTimeout(() => navigate(`/projects/${id}/review`, { replace: true }), NAV_DELAY_MS)
      return () => clearTimeout(t)
    }
    if (status === 'ready') {
      const t = setTimeout(() => navigate(`/projects/${id}/studio`, { replace: true }), NAV_DELAY_MS)
      return () => clearTimeout(t)
    }
  }, [status, spec.data, flattened, id, navigate])

  const restart = (page: number | null) =>
    analyze.mutate(page, { onSuccess: (r) => setJobId(r.job_id) })

  if (project.error) {
    return (
      <main className="flex h-full items-center justify-center p-8">
        <ErrorNotice error={project.error} />
      </main>
    )
  }
  if (!p) {
    return (
      <main className="flex h-full items-center justify-center text-ink-muted">
        <Spinner />
      </main>
    )
  }

  const pageCount = p.source?.page_count ?? 1
  const widthPt = spec.data?.page.width_pt ?? (p.source?.width_mm ?? 210) * MM_TO_PT
  const heightPt = spec.data?.page.height_pt ?? (p.source?.height_mm ?? 297) * MM_TO_PT
  const flatUrl = status === 'ready' ? `/api/projects/${id}/flat-thumb?v=${encodeURIComponent(p.updated_at)}` : null
  const stalled = status === 'analyzing' && !active && !job && !analyze.isPending

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <Link to="/projects" className="text-sm text-ink-muted hover:text-ink">
          ← {ko.appName}
        </Link>
        <span className="truncate font-semibold">{p.name}</span>
        <StatusBadge project={p} />
      </header>
      <div className="flex min-h-0 flex-1">
        <main className="relative min-w-0 flex-1 bg-canvas">
          {p.source ? (
            <SourcePreview
              url={sourceFileUrl(id)}
              pageIndex={spec.data?.page.index ?? 0}
              widthPt={widthPt}
              heightPt={heightPt}
              flatUrl={flatUrl}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-ink-muted">
              <Spinner /> <span className="ml-2">{ko.analyze.waitingPreview}</span>
            </div>
          )}
        </main>
        <aside className="w-[360px] shrink-0 space-y-4 overflow-y-auto border-l border-line bg-surface/60 p-4">
          <h1 className="text-base font-semibold">{ko.analyze.title}</h1>
          <AnalysisProgress job={job} />
          {(specReady || job?.stages.some((s) => s.key === 'separations' && s.status !== 'pending')) && (
            <SeparationReport separations={spec.data?.separations} />
          )}

          {status === 'failed' && (
            <ErrorNotice
              error={new ApiError(0, p.error ?? { code: 'ANALYZE_FAILED', message: ko.analyze.failedTitle })}
              actions={
                <>
                  <Button onClick={() => restart(spec.data?.page.index ?? null)} disabled={analyze.isPending}>
                    {ko.analyze.retry}
                  </Button>
                  <Button onClick={() => navigate('/projects')}>{ko.analyze.otherFile}</Button>
                </>
              }
            />
          )}
          {analyze.error && <ErrorNotice error={analyze.error} />}
          {stalled && (
            <div className="rounded-lg border border-line bg-surface p-3 text-sm">
              <p className="text-ink-muted">{ko.analyze.noJob}</p>
              <Button className="mt-2" onClick={() => restart(null)}>
                {ko.analyze.restart}
              </Button>
            </div>
          )}
          {status === 'needs_review' && flattened && (
            <FlattenedPdfCard
              onDraw={() => navigate(`/projects/${id}/review?draw=1`)}
              onOther={() => navigate('/projects')}
            />
          )}
          {status === 'needs_review' && spec.data && !flattened && (
            <div className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
              <span className="flex items-center gap-2 text-amber-900">
                <Spinner className="size-3.5" /> {ko.analyze.toReview}
              </span>
              <Button onClick={() => navigate(`/projects/${id}/review`)}>{ko.analyze.openReview}</Button>
            </div>
          )}
          {status === 'ready' && (
            <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm">
              <span className="text-emerald-900">✓ {ko.analyze.toStudio}</span>
              <Button variant="primary" onClick={() => navigate(`/projects/${id}/studio`)}>
                {ko.analyze.openStudio}
              </Button>
            </div>
          )}
        </aside>
      </div>
      <PageSelectDialog
        open={status === 'needs_page'}
        pageCount={pageCount}
        sourceUrl={sourceFileUrl(id)}
        pending={analyze.isPending}
        onSelect={(page) => restart(page)}
      />
    </div>
  )
}
