import type { Frame } from '@/api/types'
import { SegmentedControl } from '@/components/ui/controls'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { useCanvasStore, type FinishView } from '@/stores/useCanvasStore'
import { frameRect } from './geometry'

const t = ko.studio.finishing.view
const stop = (e: React.SyntheticEvent) => e.stopPropagation()

/** H: "원본 / 후가공 / 비교" on the ② canvas, top centre. */
export function FinishViewToggle({
  available,
  loading,
  stale,
  failed,
}: {
  /** Some enabled finish has been saved. */
  available: boolean
  loading: boolean
  stale: boolean
  failed: boolean
}) {
  const view = useCanvasStore((s) => s.finishView)
  const shown: FinishView = available ? view : 'original'
  const note = !available ? t.none : failed ? t.failed : loading ? t.loading : stale && shown !== 'original' ? t.stale : null
  return (
    <div
      onClick={stop}
      onPointerDown={stop}
      className="absolute top-3 left-1/2 z-10 flex -translate-x-1/2 flex-col items-center gap-1"
    >
      <div className="rounded-lg border border-line bg-surface/95 p-0.5 shadow-sm">
        <SegmentedControl
          size="sm"
          label={t.label}
          value={shown}
          onChange={(v) => useCanvasStore.getState().setFinishView(v)}
          options={[
            { value: 'original', label: t.original },
            { value: 'finished', label: t.finished, disabled: !available, title: available ? undefined : t.none },
            { value: 'compare', label: t.compare, disabled: !available, title: available ? undefined : t.none },
          ]}
        />
      </div>
      {note && (shown !== 'original' || !available) && (
        <span className="flex items-center gap-1 rounded-md bg-surface/90 px-2 py-0.5 text-[11px] text-ink-muted shadow-sm">
          {loading && shown !== 'original' && <Spinner className="size-3" />}
          {note}
        </span>
      )}
    </div>
  )
}

/** Divider slider of the 비교 view, bottom centre (original left, finished right). */
export function FinishSplitControl() {
  const split = useCanvasStore((s) => s.finishSplit)
  return (
    <div
      onClick={stop}
      onPointerDown={stop}
      className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-line bg-surface/95 px-3 py-1.5 text-xs shadow-sm"
    >
      <span className="text-ink-muted">{t.left}</span>
      <input
        type="range"
        min={0}
        max={100}
        value={Math.round(split * 100)}
        aria-label={t.split}
        onChange={(e) => useCanvasStore.getState().setFinishSplit(Number(e.target.value) / 100)}
        className="w-40 accent-accent"
      />
      <span className="text-ink-muted">{t.right}</span>
    </div>
  )
}

/**
 * The finishing preview PNG laid over the render (in the flat view's world). It covers
 * `previewFrame` (page pt); the render covers `frame`. In 비교 only the right of the divider.
 */
export function FinishPreviewLayer({
  url,
  frame,
  previewFrame,
  image,
  compare,
  zoom,
}: {
  url: string
  frame: Frame
  previewFrame: { origin: [number, number]; size: [number, number] }
  image: { w: number; h: number }
  compare: boolean
  zoom: number
}) {
  const split = useCanvasStore((s) => s.finishSplit)
  const rect = frameRect(frame, image, previewFrame)
  const cut = rect.w > 0 ? Math.min(100, Math.max(0, ((split * image.w - rect.x) / rect.w) * 100)) : 0
  return (
    <>
      <img
        src={url}
        alt={t.alt}
        draggable={false}
        className="pointer-events-none absolute max-w-none select-none"
        style={{
          left: rect.x,
          top: rect.y,
          width: rect.w,
          height: rect.h,
          clipPath: compare ? `inset(0 0 0 ${cut}%)` : undefined,
        }}
      />
      {compare && (
        <div
          aria-hidden
          className="pointer-events-none absolute top-0 bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.4)]"
          style={{ left: split * image.w, height: image.h, width: 2 / zoom, marginLeft: -1 / zoom }}
        />
      )}
    </>
  )
}
