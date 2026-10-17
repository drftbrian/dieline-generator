import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router'
import { api } from '@/api/client'
import { useJob } from '@/api/jobs'
import { keys } from '@/api/keys'
import { isApiError, useProject } from '@/api/projects'
import { sourceFileUrl } from '@/api/source'
import { useConfirmStructure, usePatchSpecification, useSpecification } from '@/api/spec'
import type { PathClass, SpecPatch, Specification, StructuralPath } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { PointPopover, Tooltip } from '@/components/ui/overlays'
import { Spinner } from '@/components/ui/Spinner'
import { PdfPageLayer } from '@/features/canvas/PdfPageLayer'
import { useViewport } from '@/features/canvas/useViewport'
import { Viewport } from '@/features/canvas/Viewport'
import { ClassificationOverlay } from '@/features/review/ClassificationOverlay'
import { ClassifyButtons } from '@/features/review/ClassifyButtons'
import { DrawLayer } from '@/features/review/DrawLayer'
import { PanelLabelForm, PanelOverlay } from '@/features/review/PanelLabelStep'
import { ReviewItemList as ReviewSidebar } from '@/features/review/ReviewItemList'
import { focusBox, PATH_STYLE, pathLabel } from '@/features/review/pathStyles'
import { ko } from '@/i18n/ko'
import { routeForStatus } from '@/lib/routes'
import { useShortcut } from '@/lib/shortcuts'
import { toast } from '@/stores/useToastStore'

type Mode = 'review' | 'rendering' | 'panels'

/** Structural Review gate. */
export function StructuralReviewPage() {
  const { id = '' } = useParams()
  const project = useProject(id)
  const spec = useSpecification(id)

  if (project.error || spec.error) {
    return (
      <main className="flex h-full items-center justify-center p-8">
        <ErrorNotice error={project.error ?? spec.error} />
      </main>
    )
  }
  const p = project.data
  if (p && ['uploading', 'analyzing', 'needs_page', 'failed'].includes(p.status)) {
    return <Navigate to={`../${routeForStatus(p.status)}`} replace />
  }
  if (!p || !spec.data) {
    return (
      <main className="flex h-full items-center justify-center text-ink-muted">
        <Spinner />
      </main>
    )
  }
  return <Review key={id} projectId={id} projectName={p.name} status={p.status} activeJobId={p.active_job_id} spec={spec.data} />
}

function Review({
  projectId,
  projectName,
  status,
  activeJobId,
  spec,
}: {
  projectId: string
  projectName: string
  status: string
  activeJobId: string | null
  spec: Specification
}) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const patch = usePatchSpecification(projectId)
  const confirm = useConfirmStructure(projectId)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [popover, setPopover] = useState<{ id: string; at: { x: number; y: number } } | null>(null)
  const [drawing, setDrawing] = useState(params.get('draw') === '1')
  const [points, setPoints] = useState<[number, number][]>([])
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const [drawError, setDrawError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>(status === 'rendering' ? 'rendering' : 'review')
  const [renderJob, setRenderJob] = useState<string | null>(status === 'rendering' ? activeJobId : null)
  const [activePanel, setActivePanel] = useState<string | null>(null)

  const vp = useViewport({ w: spec.page.width_pt, h: spec.page.height_pt })

  const pending = useMemo(() => spec.paths.filter((p) => p.status === 'unresolved'), [spec.paths])
  const manual = useMemo(() => spec.paths.filter((p) => p.source_ref.startsWith('manual:')), [spec.paths])
  const auto = useMemo(
    () => spec.paths.filter((p) => p.status !== 'unresolved' && !p.source_ref.startsWith('manual:')),
    [spec.paths],
  )
  const navList = pending.length ? pending : [...manual, ...auto]
  const byId = useMemo(() => new Map(spec.paths.map((p) => [p.id, p])), [spec.paths])
  const reasons = spec.review.reasons
  const busy = patch.isPending || confirm.isPending || mode !== 'review'

  // Render job after confirming: then panel labels (if Claude named them) or straight to Studio.
  useJob(renderJob, async (job) => {
    if (job.status !== 'done') {
      setMode('review')
      setRenderJob(null)
      if (job.error) toast({ message: job.error.message, tone: 'danger' })
      return
    }
    const latest = await qc.fetchQuery({
      queryKey: keys.spec(projectId),
      queryFn: () => api<Specification>(`/projects/${projectId}/specification`),
      staleTime: 0,
    })
    if (latest.panels.some((pn) => pn.name_provenance === 'claude_inferred')) setMode('panels')
    else navigate(`/projects/${projectId}/studio`, { replace: true })
  })

  const send = (body: SpecPatch, onDone?: () => void) =>
    patch.mutate(
      { patch: body, version: spec.version },
      {
        onSuccess: () => onDone?.(),
        onError: (e) => {
          if (isApiError(e) && e.code === 'SPEC_CONFLICT') {
            qc.invalidateQueries({ queryKey: keys.spec(projectId) })
            toast({ message: ko.review.conflict, tone: 'warning' })
          }
        },
      },
    )

  const select = (id: string, focus = true) => {
    setSelectedId(id)
    const p = byId.get(id)
    if (p && focus) vp.focus(focusBox(p.bbox as [number, number, number, number]), 120)
  }

  const classify = (id: string, cls: PathClass) => {
    setPopover(null)
    const idx = navList.findIndex((p) => p.id === id)
    const wasPending = byId.get(id)?.status === 'unresolved'
    send({ paths: [{ id, cls }] }, () => {
      if (!wasPending) return
      const rest = pending.filter((p) => p.id !== id)
      const next = rest[Math.min(Math.max(idx, 0), rest.length - 1)]
      if (next) select(next.id)
      else setSelectedId(null)
    })
  }

  const step = (dir: 1 | -1) => {
    if (!navList.length) return
    const i = navList.findIndex((p) => p.id === selectedId)
    const next = navList[(i + dir + navList.length) % navList.length]
    if (next) select(next.id)
  }

  const finishDrawing = () => {
    if (points.length < 3) {
      setDrawError(ko.review.drawNeed3)
      return
    }
    send({ manual_cut: { points } }, () => {
      setDrawing(false)
      setPoints([])
      setDrawError(null)
    })
  }

  const reviewKeys = mode === 'review' && !drawing && !popover
  useShortcut({ key: 'j' }, () => step(1), reviewKeys)
  useShortcut({ key: 'k' }, () => step(-1), reviewKeys)
  useShortcut({ key: 'c' }, () => selectedId && classify(selectedId, 'cut'), reviewKeys && !!selectedId)
  useShortcut({ key: 'f' }, () => selectedId && classify(selectedId, 'crease'), reviewKeys && !!selectedId)
  useShortcut({ key: 'a' }, () => selectedId && classify(selectedId, 'artwork'), reviewKeys && !!selectedId)
  useShortcut({ key: 'n' }, () => selectedId && classify(selectedId, 'annotation'), reviewKeys && !!selectedId)
  useShortcut({ key: 'Enter' }, finishDrawing, drawing)
  useShortcut({ key: 'Escape' }, () => {
    setDrawing(false)
    setPoints([])
    setDrawError(null)
  }, drawing)
  useShortcut({ key: 'Backspace' }, () => setPoints((pts) => pts.slice(0, -1)), drawing)

  const confirmDisabledReason =
    pending.length > 0
      ? ko.review.remaining(pending.length)
      : reasons.includes('cut_missing')
        ? ko.review.needCut
        : reasons.includes('cut_open')
          ? ko.review.cutOpen
          : null

  const banner = reasons.includes('uncertain_paths')
    ? ko.review.bannerUncertain(pending.length)
    : reasons.includes('cut_missing')
      ? spec.paths.length === 0
        ? ko.review.bannerCutMissingNoPaths
        : ko.review.bannerCutMissing
      : reasons.includes('cut_open')
        ? ko.review.bannerCutOpen
        : null

  const onConfirm = () =>
    confirm.mutate(undefined, {
      onSuccess: (r) => {
        setMode('rendering')
        setRenderJob(r.job_id)
      },
    })

  const popPath: StructuralPath | undefined = popover ? byId.get(popover.id) : undefined
  const W = spec.page.width_pt
  const H = spec.page.height_pt

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <Link
          to={status === 'ready' ? `/projects/${projectId}/studio` : '/projects'}
          className="max-w-48 truncate text-sm text-ink-muted hover:text-ink"
        >
          ← {projectName}
        </Link>
        <h1 className="font-semibold">{ko.review.title}</h1>
        <span className={pending.length ? 'text-sm text-amber-700' : 'text-sm text-emerald-700'}>
          {pending.length ? ko.review.pendingCount(pending.length) : ko.review.allResolved}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {mode === 'rendering' && (
            <span className="flex items-center gap-2 text-sm text-ink-muted">
              <Spinner className="size-3.5" /> {ko.review.rendering}
            </span>
          )}
          {mode === 'review' && (
            <Tooltip content={confirmDisabledReason}>
              <span>
                <Button variant="primary" disabled={!!confirmDisabledReason || busy || drawing} onClick={onConfirm}>
                  {confirm.isPending ? ko.review.confirming : ko.review.confirm}
                </Button>
              </span>
            </Tooltip>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="relative min-w-0 flex-1 bg-canvas">
          {banner && mode === 'review' && (
            <div role="status" className="absolute top-3 left-1/2 z-10 flex max-w-[90%] -translate-x-1/2 items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 shadow-sm">
              <span>{drawing ? ko.review.drawing : banner}</span>
              {(reasons.includes('cut_missing') || reasons.includes('cut_open')) && !drawing && (
                <Button className="h-7 shrink-0" onClick={() => setDrawing(true)}>
                  {ko.review.draw}
                </Button>
              )}
            </div>
          )}
          {drawing && !banner && (
            <div role="status" className="absolute top-3 left-1/2 z-10 -translate-x-1/2 rounded-lg border border-line bg-surface px-4 py-2 text-sm shadow-sm">
              {ko.review.drawing}
            </div>
          )}
          <Viewport
            vp={vp}
            cursor={drawing ? 'crosshair' : undefined}
            onWorldClick={(pt) => {
              if (drawing) {
                const first = points[0]
                if (first && points.length >= 3 && Math.hypot(pt.x - first[0], pt.y - first[1]) < 10 / vp.zoom) {
                  finishDrawing()
                } else {
                  setPoints((pts) => [...pts, [Math.round(pt.x * 100) / 100, Math.round(pt.y * 100) / 100]])
                  setDrawError(null)
                }
                return
              }
              setPopover(null)
            }}
            onWorldMove={(pt) => drawing && setCursor(pt)}
            overlay={
              <>
                <Legend />
                {drawing && (
                  <div className="absolute right-4 bottom-4 flex items-center gap-2 rounded-lg border border-line bg-surface p-2 text-sm shadow">
                    {drawError && <span className="text-xs text-red-700">{drawError}</span>}
                    <Button className="h-7" onClick={() => { setDrawing(false); setPoints([]) }}>
                      {ko.review.drawCancel}
                    </Button>
                    <Button className="h-7" variant="primary" disabled={points.length < 3 || patch.isPending} onClick={finishDrawing}>
                      {ko.review.drawFinish}
                    </Button>
                  </div>
                )}
                {!drawing && (
                  <div className="absolute right-4 bottom-4">
                    <Button className="h-7" onClick={() => vp.fit()}>
                      {ko.review.fit}
                    </Button>
                  </div>
                )}
              </>
            }
          >
            <PdfPageLayer url={sourceFileUrl(projectId)} pageIndex={spec.page.index} width={W} height={H} zoom={vp.zoom} />
            <ClassificationOverlay
              paths={spec.paths}
              width={W}
              height={H}
              zoom={vp.zoom}
              selectedId={selectedId}
              hoveredId={hoveredId}
              interactive={mode === 'review' && !drawing}
              onHover={setHoveredId}
              onPathClick={(pid, at) => {
                select(pid, false)
                setPopover({ id: pid, at })
              }}
            />
            {mode === 'panels' && (
              <PanelOverlay panels={spec.panels} zoom={vp.zoom} activeId={activePanel} onPick={setActivePanel} />
            )}
            {drawing && <DrawLayer points={points} cursor={cursor} width={W} height={H} zoom={vp.zoom} />}
          </Viewport>
        </main>

        <aside className="w-[360px] shrink-0 overflow-y-auto border-l border-line bg-surface/60 p-4">
          {mode === 'panels' ? (
            <PanelLabelForm
              panels={spec.panels}
              activeId={activePanel}
              saving={patch.isPending}
              error={patch.error}
              onActivate={setActivePanel}
              onSkip={() => navigate(`/projects/${projectId}/studio`, { replace: true })}
              onSave={(names) =>
                send({ panel_names: names }, () => navigate(`/projects/${projectId}/studio`, { replace: true }))
              }
            />
          ) : (
            <div className="space-y-4">
              {patch.error && !(isApiError(patch.error) && patch.error.code === 'SPEC_CONFLICT') && (
                <ErrorNotice error={patch.error} />
              )}
              {confirm.error && <ErrorNotice error={confirm.error} />}
              <ReviewSidebar
                pending={pending}
                auto={auto}
                manual={manual}
                selectedId={selectedId}
                busy={busy}
                onSelect={(sid) => select(sid)}
                onPick={classify}
                onRemoveManual={(mid) => send({ remove_paths: [mid] })}
              />
              <p className="text-xs text-ink-muted">{ko.review.shortcuts}</p>
            </div>
          )}
        </aside>
      </div>

      <PointPopover at={popover?.at ?? null} onClose={() => setPopover(null)}>
        {popPath && (
          <div className="w-72 space-y-2">
            <p className="font-medium">{ko.review.item(pathLabel(popPath))}</p>
            <p className="text-xs text-ink-muted">{popPath.reason}</p>
            {popPath.ai && (
              <p className="text-xs">
                <span className="font-medium text-prov-ai">◆ {ko.review.claude}:</span> “{popPath.ai.reason}”
              </p>
            )}
            <ClassifyButtons
              current={popPath.status === 'unresolved' ? null : popPath.cls}
              suggested={popPath.ai?.cls ?? popPath.suggested_cls}
              disabled={busy}
              onPick={(cls) => classify(popPath.id, cls)}
            />
          </div>
        )}
      </PointPopover>
    </div>
  )
}


function Legend() {
  const items = [
    ['cut', ko.review.legend.cut],
    ['crease', ko.review.legend.crease],
    ['annotation', ko.review.legend.annotation],
    ['finish', ko.review.legend.finish],
    ['artwork', ko.review.legend.artwork],
    ['unresolved', ko.review.legend.unresolved],
  ] as const
  return (
    <ul className="absolute bottom-4 left-4 space-y-1 rounded-lg border border-line bg-surface/95 px-3 py-2 text-xs shadow-sm">
      {items.map(([k, label]) => {
        const st = PATH_STYLE[k]
        return (
          <li key={k} className="flex items-center gap-2">
            <svg width="22" height="8" aria-hidden>
              <line x1="1" y1="4" x2="21" y2="4" stroke={st.stroke} strokeWidth={st.width} strokeDasharray={st.dash} strokeOpacity={st.opacity ?? 1} />
            </svg>
            {label}
          </li>
        )
      })}
    </ul>
  )
}
