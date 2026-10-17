import { useState } from 'react'
import type { Panel } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { ProvenanceBadge } from '@/components/ui/Provenance'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'

/** Panel outlines + names drawn on the review canvas. */
export function PanelOverlay({
  panels,
  zoom,
  activeId,
  onPick,
}: {
  panels: Panel[]
  zoom: number
  activeId: string | null
  onPick: (id: string) => void
}) {
  return (
    <>
      {panels.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onPick(p.id)
          }}
          className={cn(
            'absolute flex items-center justify-center rounded-sm border',
            p.id === activeId ? 'border-accent bg-accent/15' : 'border-accent/40 bg-accent/5 hover:bg-accent/10',
          )}
          style={{ left: p.bbox[0], top: p.bbox[1], width: p.bbox[2] - p.bbox[0], height: p.bbox[3] - p.bbox[1] }}
        >
          <span
            className="rounded bg-surface/90 px-1 font-medium whitespace-nowrap text-ink shadow-sm"
            style={{ fontSize: 12 / zoom, padding: `${1 / zoom}px ${4 / zoom}px` }}
          >
            {p.name}
          </span>
        </button>
      ))}
    </>
  )
}

/** Side form for confirming Claude's panel names; skipping has no effect on the mockup. */
export function PanelLabelForm({
  panels,
  activeId,
  saving,
  error,
  onActivate,
  onSave,
  onSkip,
}: {
  panels: Panel[]
  activeId: string | null
  saving: boolean
  error: unknown
  onActivate: (id: string) => void
  onSave: (names: { id: string; name: string }[]) => void
  onSkip: () => void
}) {
  const [names, setNames] = useState<Record<string, string>>(() =>
    Object.fromEntries(panels.map((p) => [p.id, p.name])),
  )
  const changed = panels
    .filter((p) => (names[p.id] ?? '').trim() && names[p.id]!.trim() !== p.name)
    .map((p) => ({ id: p.id, name: names[p.id]!.trim() }))
  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">{ko.panels.title}</h2>
        <p className="mt-1 text-xs text-ink-muted">{ko.panels.body}</p>
      </div>
      <ul className="space-y-1.5">
        {panels.map((p) => (
          <li key={p.id} className="flex items-center gap-2">
            <input
              aria-label={p.id}
              value={names[p.id] ?? ''}
              maxLength={40}
              autoFocus={p.id === activeId}
              onFocus={() => onActivate(p.id)}
              onChange={(e) => setNames((n) => ({ ...n, [p.id]: e.target.value }))}
              className={cn(
                'h-8 flex-1 rounded-md border bg-surface px-2 text-sm focus-visible:outline-2 focus-visible:outline-accent',
                p.id === activeId ? 'border-accent' : 'border-line',
              )}
            />
            {p.name_provenance === 'claude_inferred' && <ProvenanceBadge kind="claude_inferred" />}
          </li>
        ))}
      </ul>
      <ErrorNotice error={error} />
      <div className="flex justify-end gap-2">
        <Button onClick={onSkip} disabled={saving}>
          {ko.panels.skip}
        </Button>
        <Button variant="primary" disabled={saving} onClick={() => (changed.length ? onSave(changed) : onSkip())}>
          {ko.panels.save}
        </Button>
      </div>
    </div>
  )
}
