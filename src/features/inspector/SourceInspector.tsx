import { Link } from 'react-router'
import { sourceFileUrl } from '@/api/source'
import { IconButton } from '@/components/ui/controls'
import { ProvenanceBadge } from '@/components/ui/Provenance'
import { Tooltip } from '@/components/ui/overlays'
import type { StudioRegionProps } from '@/features/studio/types'
import { ko } from '@/i18n/ko'
import { formatDateTime, formatSize } from '@/lib/format'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { useUiStore } from '@/stores/useUiStore'
import { PhysicalSize } from './PhysicalSize'

const t = ko.studio.inspector

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border-b border-line px-3 py-2 text-xs">
      <div className="mb-1.5 flex items-center justify-between gap-1">
        <h2 className="font-semibold text-ink-muted">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  )
}

/** Left sidebar: where the design came from, its size, structure and panels. */
export function SourceInspector({ project, spec }: StudioRegionProps) {
  const collapsed = useUiStore((s) => s.leftPanelCollapsed)
  const toggle = useUiStore((s) => s.toggleLeftPanel)
  const setView = useCanvasStore((s) => s.setView)
  const pageImage = `/api/projects/${project.id}/page-image`

  if (collapsed) {
    return (
      <aside className="flex w-12 shrink-0 flex-col items-center gap-2 border-r border-line bg-surface py-2">
        <IconButton label={t.expand} onClick={toggle}>
          »
        </IconButton>
        <Tooltip content={t.openSource}>
          <button type="button" onClick={() => setView('source')} className="size-8 overflow-hidden rounded border border-line">
            <img src={pageImage} alt="" className="h-full w-full object-cover" />
          </button>
        </Tooltip>
      </aside>
    )
  }

  const src = project.source
  const f = project.figma

  return (
    <aside aria-label={t.title} className="flex w-60 shrink-0 flex-col overflow-y-auto border-r border-line bg-surface">
      <div className="flex h-9 items-center justify-between border-b border-line px-3">
        <span className="text-[11px] font-semibold tracking-wide text-ink-muted">{t.title}</span>
        <IconButton label={t.collapse} onClick={toggle} className="size-6">
          «
        </IconButton>
      </div>

      <Section title={t.source}>
        <button
          type="button"
          onClick={() => setView('source')}
          className="mb-2 block w-full overflow-hidden rounded border border-line bg-canvas"
          aria-label={t.openSource}
        >
          <img src={pageImage} alt="" className="mx-auto max-h-32 object-contain" />
        </button>
        {f && (
          <div className="mb-2 space-y-0.5">
            <p className="truncate font-medium" title={`${f.file_name} / ${f.node_name}`}>
              {f.file_name} / {f.node_name}
            </p>
            {f.last_modified && <p className="text-ink-muted">{t.figmaUpdated(formatDateTime(f.last_modified))}</p>}
            <a href={f.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              {t.figma} ↗
            </a>
            {!f.content_ready && <p className="text-amber-700">{t.figmaPending}</p>}
          </div>
        )}
        {src && (
          <dl className="space-y-0.5">
            <div className="flex items-center justify-between gap-2">
              <dt className="truncate font-medium" title={src.filename}>
                {src.filename}
              </dt>
              <a href={`${sourceFileUrl(project.id)}?download=true`} className="shrink-0 text-accent hover:underline" title={t.download}>
                ⤓
              </a>
            </div>
            <dd className="text-ink-muted">
              {formatSize(src.size_bytes)} · {formatDateTime(src.uploaded_at)} <ProvenanceBadge kind="pdf" />
            </dd>
          </dl>
        )}
        <PhysicalSize projectId={project.id} spec={spec} />
      </Section>

      <Section
        title={t.structure}
        aside={
          spec.structure_confirmed ? (
            <span className="text-[11px] text-emerald-700">{t.confirmed}</span>
          ) : (
            <span className="text-[11px] text-amber-700">⚠ {spec.review.pending}</span>
          )
        }
      >
        <Link to={`/projects/${project.id}/review`} className="text-accent hover:underline">
          {t.review} →
        </Link>
      </Section>

      <Section title={`${t.panels} (${spec.panels.length})`}>
        <ul className="space-y-0.5">
          {spec.panels.map((p) => (
            <li key={p.id} className="flex items-center gap-1">
              <span className="flex-1 truncate">{p.name}</span>
              {p.width_mm > 0 && (
                <span className="shrink-0 text-[11px] text-ink-muted tabular-nums">
                  {p.width_mm.toFixed(0)}×{p.height_mm.toFixed(0)}mm
                </span>
              )}
              {p.name_provenance === 'claude_inferred' && <ProvenanceBadge kind="claude_inferred" />}
            </li>
          ))}
        </ul>
      </Section>
    </aside>
  )
}
