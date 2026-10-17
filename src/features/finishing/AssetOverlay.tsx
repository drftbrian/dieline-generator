import { useState } from 'react'
import { assetMaskUrl } from '@/api/assets'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { useAssetSelectionStore, useSelectedAssets } from '@/stores/useAssetSelectionStore'
import { HOVER_COLOR, SELECT_COLOR } from './geometry'

const t = ko.studio.finishing
const stop = (e: React.SyntheticEvent) => e.stopPropagation()

type Rect = { x: number; y: number; w: number; h: number }

/** One mask PNG placed over the render (hidden if the server can't draw it). */
function Mask({ src, rect, className }: { src: string; rect: Rect; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null)
  if (failed === src) return null
  return (
    <img
      src={src}
      alt=""
      aria-hidden
      draggable={false}
      onError={() => setFailed(src)}
      className={cn('pointer-events-none absolute max-w-none select-none', className)}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
    />
  )
}

/**
 * Selected assets (orange outline + light fill) and the hovered one (blue outline), drawn
 * in the flat view's world. `rect` is where the asset frame lies on the render.
 */
export function AssetOverlay({ projectId, rect, valid }: { projectId: string; rect: Rect; valid: Set<string> }) {
  const selected = useSelectedAssets(projectId)
  const hover = useAssetSelectionStore((s) => (s.hover?.projectId === projectId ? s.hover.id : null))
  return (
    <>
      {selected
        .filter((id) => valid.has(id))
        .map((id) => (
          <div key={id}>
            <Mask src={assetMaskUrl(projectId, id, 'fill', SELECT_COLOR)} rect={rect} className="opacity-40" />
            <Mask src={assetMaskUrl(projectId, id, 'outline', SELECT_COLOR)} rect={rect} />
          </div>
        ))}
      {hover && valid.has(hover) && !selected.includes(hover) && (
        <Mask key={hover} src={assetMaskUrl(projectId, hover, 'outline', HOVER_COLOR)} rect={rect} />
      )}
    </>
  )
}

/** Canvas toggle for selection mode ("요소 선택"), top right of the flat view. */
export function SelectModeToggle({ disabled, reason }: { disabled?: boolean; reason?: string }) {
  const on = useAssetSelectionStore((s) => s.selecting)
  return (
    <div
      onClick={stop}
      onPointerDown={stop}
      className="absolute top-3 right-3 z-10 rounded-lg border border-line bg-surface/95 p-0.5 shadow-sm"
    >
      <button
        type="button"
        aria-pressed={on}
        disabled={disabled}
        title={disabled ? reason : t.modeTitle}
        onClick={() => useAssetSelectionStore.getState().setSelecting(!on)}
        className={cn(
          'flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium',
          'disabled:cursor-not-allowed disabled:opacity-40',
          'focus-visible:outline-2 focus-visible:outline-accent',
          on ? 'bg-accent text-white' : 'text-ink-muted hover:bg-canvas hover:text-ink',
        )}
      >
        <span aria-hidden>⌖</span>
        {t.modeOn}
      </button>
    </div>
  )
}
