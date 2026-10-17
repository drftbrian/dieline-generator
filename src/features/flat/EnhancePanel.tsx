import { useState } from 'react'
import { ApiError } from '@/api/client'
import { useStartEnhance } from '@/api/generate'
import { useReferences } from '@/api/references'
import type { Version } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { VersionError } from '@/features/studio/StepPanel'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { useCanvasStore } from '@/stores/useCanvasStore'

const t = ko.studio.flat.enhance

const pct = (x: number) => `${Math.round(x * 100)}%`
const linkClass =
  'inline-flex h-8 flex-1 items-center justify-center rounded-md border border-line bg-surface px-2 text-xs font-medium hover:bg-canvas focus-visible:outline-2 focus-visible:outline-accent'

/** Why a start failed, plus a plain next step for the cases the server message doesn't cover. */
function StartError({ error }: { error: unknown }) {
  if (!error) return null
  const code = error instanceof ApiError ? error.code : null
  return (
    <div className="space-y-1">
      <ErrorNotice error={error} />
      {code === 'PROVIDER_UNAVAILABLE' && <p className="text-xs text-ink-muted">{t.noKey}</p>}
    </div>
  )
}

function StrengthSlider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <label className="block space-y-1">
      <span className="flex justify-between text-xs">
        <span className="font-medium">{t.strength}</span>
        <span className="tabular-nums text-ink-muted">{value}%</span>
      </span>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-accent"
      />
    </label>
  )
}

/** Optional AI 재질 보정 of a finished code render: picks a photo + strength, makes a new version. */
export function EnhanceStart({ projectId, source }: { projectId: string; source: Version }) {
  const start = useStartEnhance(projectId)
  const refs = useReferences(projectId).data ?? []
  const [refId, setRefId] = useState<string | null>(null)
  const [strength, setStrength] = useState(60)
  // A deleted reference falls back to the bundled look photo.
  const reference = refs.find((r) => r.id === refId) ?? null

  const tile = (selected: boolean) =>
    cn(
      'size-12 shrink-0 overflow-hidden rounded border text-[10px] leading-tight',
      'focus-visible:outline-2 focus-visible:outline-accent',
      selected ? 'border-accent ring-2 ring-accent/30' : 'border-line',
    )

  return (
    <section className="space-y-3 rounded-md border border-line p-3">
      <div className="space-y-1">
        <h3 className="text-xs font-semibold">{t.title}</h3>
        <p className="text-xs text-ink-muted">{t.intro}</p>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium">{t.reference}</p>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            title={t.fallbackRef}
            aria-pressed={!reference}
            onClick={() => setRefId(null)}
            className={cn(tile(!reference), 'bg-canvas px-0.5 text-ink-muted')}
          >
            {t.fallbackRef}
          </button>
          {refs.map((r) => (
            <button
              key={r.id}
              type="button"
              title={r.filename}
              aria-pressed={r.id === reference?.id}
              onClick={() => setRefId(r.id)}
              className={tile(r.id === reference?.id)}
            >
              <img src={r.thumb_url} alt={r.filename} className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      </div>

      <div>
        <StrengthSlider value={strength} onChange={setStrength} />
        <p className="mt-0.5 text-[11px] text-ink-muted">{t.strengthHint}</p>
      </div>

      <Button
        variant="primary"
        className="w-full justify-center"
        disabled={start.isPending}
        onClick={() =>
          start.mutate(
            { sourceId: source.id, strength: strength / 100, reference_id: reference?.id ?? null },
            { onSuccess: () => useCanvasStore.getState().setView('flat') },
          )
        }
      >
        {start.isPending ? (
          <>
            <Spinner className="size-3.5" /> {t.starting}
          </>
        ) : (
          t.start
        )}
      </Button>
      <p className="text-[11px] text-ink-muted">{t.cost}</p>
      <StartError error={start.error} />
    </section>
  )
}

/** A finished AI-enhanced version: before/after, requested vs applied strength, free re-apply, downloads. */
export function EnhanceResult({
  projectId,
  version,
  versions,
}: {
  projectId: string
  version: Version
  versions: Version[]
}) {
  const e = version.enhancement
  const start = useStartEnhance(projectId)
  const refs = useReferences(projectId).data ?? []
  const compare = useCanvasStore((s) => s.compare)
  const [strength, setStrength] = useState(() => Math.round((e?.strength ?? 0.6) * 100))
  if (!e) return null

  const source = versions.find((v) => v.id === e.source_version_id && v.status === 'done') ?? null
  const applied = version.verify?.strength_applied ?? null
  const reference = e.reference_id ? refs.find((r) => r.id === e.reference_id) : null

  return (
    <section className="space-y-3 rounded-md border border-violet-200 bg-violet-50/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold">{t.resultTitle}</h3>
        {source && <span className="text-[11px] text-ink-muted">{t.sourceOf(source.number)}</span>}
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <figure className="space-y-1">
          <button
            type="button"
            title={source ? t.showOriginal : t.sourceMissing}
            disabled={!source}
            onClick={() => source && useCanvasStore.getState().showVersion(source.id, 'flat')}
            className="block w-full overflow-hidden rounded border border-line bg-black focus-visible:outline-2 focus-visible:outline-accent"
          >
            <img src={source?.thumb_url ?? e.source_image_url} alt={t.original} className="aspect-square w-full object-contain" />
          </button>
          <figcaption className="text-center text-ink-muted">
            {t.original}
            {source && ` · v${source.number}`}
          </figcaption>
        </figure>
        <figure className="space-y-1">
          <div className="overflow-hidden rounded border border-accent bg-black">
            {version.thumb_url && (
              <img src={version.thumb_url} alt={t.enhanced} className="aspect-square w-full object-contain" />
            )}
          </div>
          <figcaption className="text-center font-medium">
            {t.enhanced} · v{version.number}
          </figcaption>
        </figure>
      </div>

      <label className="flex items-center gap-1.5 text-xs">
        <input type="checkbox" checked={compare} onChange={(ev) => useCanvasStore.getState().setCompare(ev.target.checked)} />
        {t.compare}
      </label>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-ink-muted">{t.requested}</dt>
        <dd className="tabular-nums">{pct(e.strength)}</dd>
        <dt className="text-ink-muted">{t.applied}</dt>
        <dd className="tabular-nums">{applied != null ? pct(applied) : '—'}</dd>
        <dt className="text-ink-muted">{t.usedReference}</dt>
        <dd className="truncate">{e.reference_id ? (reference?.filename ?? e.reference_id) : t.fallbackRef}</dd>
      </dl>
      {applied != null && applied < e.strength - 0.005 && <p className="text-[11px] text-amber-800">{t.appliedLower}</p>}

      <div className="space-y-2 border-t border-line pt-3">
        <p className="text-xs font-medium">{t.reapplyTitle}</p>
        <StrengthSlider value={strength} onChange={setStrength} />
        <Button
          className="w-full justify-center"
          disabled={start.isPending || !source}
          onClick={() =>
            start.mutate(
              {
                sourceId: e.source_version_id,
                strength: strength / 100,
                maps_from: version.id,
                // Provenance only (the maps are reused); a since-deleted photo would be refused.
                reference_id: reference?.id ?? null,
              },
              { onSuccess: () => useCanvasStore.getState().setView('flat') },
            )
          }
        >
          {start.isPending ? (
            <>
              <Spinner className="size-3.5" /> {t.starting}
            </>
          ) : (
            t.reapply
          )}
        </Button>
        <p className="text-[11px] text-ink-muted">{source ? t.reapplyHint : t.sourceMissing}</p>
        <StartError error={start.error} />
      </div>

      <div className="space-y-1 border-t border-line pt-3">
        <p className="text-xs font-medium">{t.download}</p>
        <div className="flex gap-2">
          {source?.download_url && (
            <a href={source.download_url} download className={linkClass}>
              ⤓ {t.downloadOriginal}
            </a>
          )}
          {version.download_url && (
            <a href={version.download_url} download className={linkClass}>
              ⤓ {t.downloadEnhanced}
            </a>
          )}
        </div>
      </div>
    </section>
  )
}

/** ENHANCE_REJECTED: the AI candidate failed a check, so nothing was delivered and v3 stays. */
export function EnhanceFailure({ version }: { version: Version }) {
  const err = version.error
  if (!err) return null
  if (err.code !== 'ENHANCE_REJECTED') {
    return (
      <div className="space-y-1">
        <VersionError version={version} />
        {err.code === 'SOURCE_OUTDATED' && <p className="text-xs text-ink-muted">{t.outdated}</p>}
      </div>
    )
  }
  const reasons = Array.isArray(err.details?.reasons) ? (err.details.reasons as unknown[]).map(String) : []
  return (
    <div role="status" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      <p className="font-medium">{t.rejectedTitle}</p>
      <p className="mt-0.5">{t.rejectedBody}</p>
      {reasons.length > 0 && (
        <>
          <p className="mt-2 font-medium">{t.reasonsTitle}</p>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
            {reasons.map((r) => (
              <li key={r}>{t.reasons[r] ?? r}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
