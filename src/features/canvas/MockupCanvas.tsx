import { useEffect, useRef } from 'react'
import { sourceFileUrl } from '@/api/source'
import { Spinner } from '@/components/ui/Spinner'
import type { StudioRegionProps } from '@/features/studio/types'
import { useShownVersion } from '@/features/studio/useShownVersion'
import { ko } from '@/i18n/ko'
import { formatDateTime } from '@/lib/format'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { ViewLabel, ZoomControls } from './CanvasControls'
import { GenerationStatus } from './GenerationStatus'
import { SourceLayer } from './SourceLayer'
import { useImageSize } from './useImageSize'
import { useStableSize } from './useStableSize'
import { useViewport } from './useViewport'
import { Viewport } from './Viewport'

const t = ko.studio.canvas

/** Center workspace: ① the source page, ② the selected flat render, or ③ the selected merge. */
export function MockupCanvas({ project, spec }: StudioRegionProps) {
  const pid = project.id
  const view = useCanvasStore((s) => s.view)
  const fullscreen = useCanvasStore((s) => s.fullscreen)
  const version = useShownVersion(pid)
  const imageUrl = view === 'source' ? null : (version?.image_url ?? null)
  const imageSize = useImageSize(imageUrl)

  const page = { w: Math.round(spec.page.width_pt), h: Math.round(spec.page.height_pt) }
  const size = view === 'source' ? page : (imageSize ?? { w: 0, h: 0 })
  const world = useStableSize(size.w, size.h)
  const vp = useViewport(world.w > 0 ? world : null, () => useCanvasStore.getState().touch())

  // Refit when switching between steps or versions: their sizes are unrelated.
  const shownKey = view === 'source' ? 'source' : (imageUrl ?? view)
  const lastKey = useRef(shownKey)
  useEffect(() => {
    if (lastKey.current === shownKey || world.w === 0) return
    lastKey.current = shownKey
    vp.fit()
  }, [shownKey, world, vp])

  // Fullscreen inspection (F).
  const rootRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    if (fullscreen && !document.fullscreenElement) el.requestFullscreen?.().catch(() => useCanvasStore.getState().setFullscreen(false))
    if (!fullscreen && document.fullscreenElement) void document.exitFullscreen?.()
  }, [fullscreen])
  useEffect(() => {
    const onChange = () => !document.fullscreenElement && useCanvasStore.getState().setFullscreen(false)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const label =
    view === 'source'
      ? t.labels.source
      : version
        ? (view === 'flat' ? t.labels.flat : t.labels.merge)(version.number, formatDateTime(version.created_at))
        : ''
  const empty = view !== 'source' && !version

  return (
    <div ref={rootRef} className="absolute inset-0 flex bg-canvas">
      <div className="relative w-full">
        <Viewport
          vp={vp}
          overlay={
            <>
              {label && <ViewLabel text={label} legacy={view !== 'source' && version?.legacy} />}
              {empty && (
                <div className="absolute inset-0 z-10 flex items-center justify-center p-10">
                  <p className="max-w-xs text-center text-sm text-ink-muted">{view === 'flat' ? t.noFlat : t.noMerge}</p>
                </div>
              )}
              {imageUrl && !imageSize && (
                <div className="absolute inset-0 z-10 flex items-center justify-center text-ink-muted">
                  <Spinner />
                </div>
              )}
              <ZoomControls vp={vp} />
            </>
          }
        >
          {view === 'source' ? (
            <SourceLayer
              url={sourceFileUrl(pid)}
              pageIndex={spec.page.index}
              width={page.w}
              height={page.h}
              zoom={vp.zoom}
              alt={t.alt.source}
            />
          ) : (
            imageUrl &&
            imageSize &&
            version && (
              <img
                src={imageUrl}
                alt={(view === 'flat' ? t.alt.flat : t.alt.merge)(version.number)}
                draggable={false}
                className="absolute top-0 left-0 max-w-none select-none"
                style={{ width: imageSize.w, height: imageSize.h }}
              />
            )
          )}
        </Viewport>
      </div>
      <GenerationStatus projectId={pid} />
    </div>
  )
}
