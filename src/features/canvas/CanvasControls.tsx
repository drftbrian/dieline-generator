import { Badge } from '@/components/ui/Badge'
import { IconButton } from '@/components/ui/controls'
import { Tooltip } from '@/components/ui/overlays'
import type { ViewportApi } from '@/features/canvas/useViewport'
import { ko } from '@/i18n/ko'
import { useCanvasStore } from '@/stores/useCanvasStore'

const t = ko.studio.canvas
const stop = (e: React.SyntheticEvent) => e.stopPropagation()

export function ZoomControls({ vp }: { vp: ViewportApi }) {
  const setFullscreen = useCanvasStore((s) => s.setFullscreen)
  const fullscreen = useCanvasStore((s) => s.fullscreen)
  return (
    <div
      onClick={stop}
      onPointerDown={stop}
      className="absolute right-3 bottom-3 z-10 flex items-center gap-0.5 rounded-lg border border-line bg-surface/95 p-0.5 shadow-sm"
    >
      <IconButton label={t.zoomOut} onClick={() => vp.setZoom(vp.zoom / 1.25)}>
        −
      </IconButton>
      <Tooltip content={t.fit}>
        <button type="button" className="h-8 w-12 rounded text-xs tabular-nums hover:bg-canvas" onClick={() => vp.fit()}>
          {Math.round(vp.zoom * 100)}%
        </button>
      </Tooltip>
      <IconButton label={t.zoomIn} onClick={() => vp.setZoom(vp.zoom * 1.25)}>
        +
      </IconButton>
      <span className="mx-0.5 h-5 w-px bg-line" />
      <IconButton label={t.fullscreen} active={fullscreen} onClick={() => setFullscreen(!fullscreen)}>
        ⤢
      </IconButton>
    </div>
  )
}

export function ViewLabel({ text, legacy }: { text: string; legacy?: boolean }) {
  return (
    <div className="pointer-events-none absolute top-3 left-3 z-10 flex flex-wrap items-center gap-1.5">
      <span className="rounded-md bg-surface/90 px-2 py-1 text-xs font-medium shadow-sm">{text}</span>
      {legacy && <Badge tone="warning">{t.labels.legacy}</Badge>}
    </div>
  )
}

/** Before/after divider for an AI-enhanced flat: original v3 on the left, AI 보정 on the right. */
export function CompareControls() {
  const on = useCanvasStore((s) => s.compare)
  const split = useCanvasStore((s) => s.split)
  const { setCompare, setSplit } = useCanvasStore.getState()
  const c = t.compare
  return (
    <div
      onClick={stop}
      onPointerDown={stop}
      className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-line bg-surface/95 px-3 py-1.5 text-xs shadow-sm"
    >
      <label className="flex items-center gap-1.5">
        <input type="checkbox" checked={on} onChange={(e) => setCompare(e.target.checked)} />
        {c.toggle}
      </label>
      {on && (
        <>
          <span className="ml-1 text-ink-muted">{c.original}</span>
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(split * 100)}
            aria-label={c.split}
            onChange={(e) => setSplit(Number(e.target.value) / 100)}
            className="w-40 accent-accent"
          />
          <span className="text-ink-muted">{c.enhanced}</span>
        </>
      )}
    </div>
  )
}
