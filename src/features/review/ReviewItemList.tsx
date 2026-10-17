import { useEffect, useRef, useState } from 'react'
import type { PathClass, StructuralPath } from '@/api/types'
import { ProvenanceBadge } from '@/components/ui/Provenance'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { ClassifyButtons } from './ClassifyButtons'
import { clsLabel, overlayKind, PATH_STYLE, pathLabel } from './pathStyles'

function Swatch({ p }: { p: StructuralPath }) {
  const st = PATH_STYLE[overlayKind(p)]
  return (
    <svg width="22" height="8" aria-hidden className="shrink-0">
      <line x1="1" y1="4" x2="21" y2="4" stroke={st.stroke} strokeWidth={st.width} strokeDasharray={st.dash} />
    </svg>
  )
}

function ReviewItemCard({
  p,
  selected,
  busy,
  onSelect,
  onPick,
}: {
  p: StructuralPath
  selected: boolean
  busy: boolean
  onSelect: () => void
  onPick: (cls: PathClass) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [selected])
  const pending = p.status === 'unresolved'
  return (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
      className={cn(
        'space-y-2 rounded-lg border p-3 text-sm outline-none',
        selected ? 'border-accent ring-1 ring-accent' : 'border-line hover:border-ink-muted/40',
        pending ? 'bg-surface' : 'bg-canvas/40',
      )}
    >
      <div className="flex items-center gap-2">
        <Swatch p={p} />
        <span className="font-medium">{ko.review.item(pathLabel(p))}</span>
        <span className="ml-auto text-xs text-ink-muted">
          {pending ? `${ko.review.suggestion}: ${p.suggested_cls ? clsLabel(p.suggested_cls) : '—'}` : clsLabel(p.cls)}
        </span>
      </div>
      <p className="text-xs text-ink-muted">
        <span className="font-medium text-ink/70">{ko.review.geometry}:</span> {p.reason}
      </p>
      {p.ai && (
        <p className="flex items-start gap-1.5 text-xs">
          <ProvenanceBadge kind="claude_inferred" />
          <span>
            “{p.ai.reason}” → <span className="font-medium">{clsLabel(p.ai.cls)}</span>
          </span>
        </p>
      )}
      {selected && (
        <p className="text-[11px] text-ink-muted">
          {p.color_space} · {p.width_pt}pt{p.dashed ? ' · 점선' : ''}
          {p.layers.length > 0 && ` · ${ko.review.layer} ${p.layers.join('/')}`}
        </p>
      )}
      {(pending || selected) && (
        <ClassifyButtons
          current={pending ? null : p.cls}
          suggested={p.ai?.cls ?? p.suggested_cls}
          disabled={busy}
          onPick={onPick}
          compact={!selected}
        />
      )}
    </div>
  )
}

export function ReviewItemList({
  pending,
  auto,
  manual,
  selectedId,
  busy,
  onSelect,
  onPick,
  onRemoveManual,
}: {
  pending: StructuralPath[]
  auto: StructuralPath[]
  manual: StructuralPath[]
  selectedId: string | null
  busy: boolean
  onSelect: (id: string) => void
  onPick: (id: string, cls: PathClass) => void
  onRemoveManual: (id: string) => void
}) {
  const [showAuto, setShowAuto] = useState(false)
  const selectedIsAuto = auto.some((p) => p.id === selectedId)
  const autoOpen = showAuto || selectedIsAuto
  return (
    <div className="space-y-4">
      {pending.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">{ko.review.pendingTitle(pending.length)}</h2>
          {pending.map((p) => (
            <ReviewItemCard
              key={p.id}
              p={p}
              selected={p.id === selectedId}
              busy={busy}
              onSelect={() => onSelect(p.id)}
              onPick={(cls) => onPick(p.id, cls)}
            />
          ))}
        </section>
      )}
      {manual.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">{ko.review.manualTitle}</h2>
          {manual.map((p) => (
            <div key={p.id} className="flex items-center gap-2 rounded-lg border border-line bg-surface p-3 text-sm">
              <Swatch p={p} />
              <span className="flex-1">{ko.review.item(pathLabel(p))}</span>
              <ProvenanceBadge kind="user_confirmed" />
              <button
                type="button"
                disabled={busy}
                onClick={() => onRemoveManual(p.id)}
                className="text-xs text-red-700 hover:underline disabled:opacity-40"
              >
                {ko.review.removeManual}
              </button>
            </div>
          ))}
        </section>
      )}
      {auto.length > 0 && (
        <section className="space-y-2">
          <button
            type="button"
            aria-expanded={autoOpen}
            onClick={() => setShowAuto((v) => !v)}
            className="flex w-full items-center justify-between text-sm font-semibold"
          >
            {ko.review.autoTitle(auto.length)}
            <span className="text-ink-muted">{autoOpen ? '▾' : '▸'}</span>
          </button>
          {autoOpen &&
            auto.map((p) => (
              <ReviewItemCard
                key={p.id}
                p={p}
                selected={p.id === selectedId}
                busy={busy}
                onSelect={() => onSelect(p.id)}
                onPick={(cls) => onPick(p.id, cls)}
              />
            ))}
        </section>
      )}
    </div>
  )
}
