import { useState } from 'react'
import type { SeparationItem, Separations } from '@/api/types'
import { Spinner } from '@/components/ui/Spinner'
import { GuideSheet } from '@/features/upload/GuideSheet'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'

const ORDER = ['cut', 'crease', 'artwork', 'finish'] as const

const STATE_CLASS: Record<SeparationItem['state'], string> = {
  detected: 'text-emerald-600',
  estimated: 'text-prov-ai',
  missing: 'text-red-600',
  absent_optional: 'text-ink-muted',
}

function advice(seps: Separations): string[] {
  const out: string[] = []
  const a = ko.separation.advice
  if (seps.cut.state === 'missing') out.push(a.cut_missing)
  else if (seps.cut.state === 'estimated') out.push(a.cut_estimated)
  if (seps.crease.state !== 'detected' && seps.cut.state !== 'missing') out.push(a.crease_missing)
  out.push(seps.finish.state === 'detected' ? a.finish_found : a.finish_missing)
  return out
}

/**
 * Separation detection report: mirrors the upload expectations 1:1 so the user
 * sees what was found and what was missing. Missing items are guidance, not errors.
 */
export function SeparationReport({ separations, compact }: { separations?: Separations; compact?: boolean }) {
  const [guide, setGuide] = useState(false)
  const s = ko.separation
  return (
    <div className="rounded-lg border border-line bg-surface p-4 text-sm">
      {!compact && <h2 className="mb-3 font-semibold">{s.title}</h2>}
      {!separations ? (
        <p className="flex items-center gap-2 text-ink-muted">
          <Spinner className="size-3.5" /> {s.detecting}
        </p>
      ) : (
        <>
          <ul className="space-y-1.5">
            {ORDER.map((key) => {
              const item = separations[key]
              return (
                <li key={key} className="grid grid-cols-[3.5rem_4.5rem_1fr] items-baseline gap-2">
                  <span
                    className={cn('font-medium', STATE_CLASS[item.state])}
                    title={s.stateLabel[item.state]}
                  >
                    {s.states[item.state]}
                    <span className="sr-only"> {s.stateLabel[item.state]}</span>
                  </span>
                  <span className="font-medium">{s.rows[key]}</span>
                  <span className="truncate text-xs text-ink-muted" title={item.evidence.join(' · ')}>
                    {item.evidence.length
                      ? item.evidence.join(' · ')
                      : item.state === 'missing'
                        ? s.stateLabel.missing
                        : s.stateLabel.absent_optional}
                    {key !== 'artwork' && item.path_count > 0 && ` · ${s.paths(item.path_count)}`}
                  </span>
                </li>
              )
            })}
          </ul>
          <ul className="mt-3 space-y-1 border-t border-line pt-3 text-xs text-ink-muted">
            {advice(separations).map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </>
      )}
      {!compact && (
        <button type="button" onClick={() => setGuide(true)} className="mt-3 text-xs font-medium text-accent hover:underline">
          {s.guideLink}
        </button>
      )}
      <GuideSheet open={guide} onOpenChange={setGuide} />
    </div>
  )
}
