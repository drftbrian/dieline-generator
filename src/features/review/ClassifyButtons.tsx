import type { PathClass } from '@/api/types'
import { Kbd } from '@/components/ui/controls'
import { Tooltip } from '@/components/ui/overlays'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { CLASS_KEYS, clsLabel } from './pathStyles'

/** The five classification choices. "잘 모르겠음" keeps the line as printed artwork. */
export function ClassifyButtons({
  current,
  suggested,
  disabled,
  onPick,
  compact,
}: {
  current?: PathClass | null
  suggested?: PathClass | null
  disabled?: boolean
  onPick: (cls: PathClass) => void
  compact?: boolean
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {CLASS_KEYS.map(({ cls, key }) => (
        <button
          key={cls}
          type="button"
          disabled={disabled}
          onClick={(e) => {
            e.stopPropagation()
            onPick(cls)
          }}
          className={cn(
            'inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs font-medium',
            'focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40',
            current === cls
              ? 'border-accent bg-accent text-white'
              : suggested === cls
                ? 'border-accent/60 bg-accent/5 text-ink'
                : 'border-line bg-surface hover:bg-canvas',
          )}
        >
          {clsLabel(cls)}
          {!compact && <Kbd>{key.toUpperCase()}</Kbd>}
        </button>
      ))}
      <Tooltip content={ko.review.unsureHint}>
        <button
          type="button"
          disabled={disabled}
          onClick={(e) => {
            e.stopPropagation()
            onPick('artwork')
          }}
          className="inline-flex h-7 items-center rounded-md border border-dashed border-line px-2 text-xs text-ink-muted hover:bg-canvas disabled:opacity-40"
        >
          {ko.review.unsure}
        </button>
      </Tooltip>
    </div>
  )
}
