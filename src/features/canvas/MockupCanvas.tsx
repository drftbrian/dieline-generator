import { useEffect, useMemo, useRef } from 'react'
import { useAssets } from '@/api/assets'
import { useFinishingPreview } from '@/api/finishing'
import { sourceFileUrl } from '@/api/source'
import { Spinner } from '@/components/ui/Spinner'
import type { StudioRegionProps } from '@/features/studio/types'
import { useShownVersion } from '@/features/studio/useShownVersion'
import { useVersions } from '@/features/studio/versions'
import { ko } from '@/i18n/ko'
import { AssetOverlay, SelectModeToggle } from '@/features/finishing/AssetOverlay'
import { pickGeometry } from '@/features/finishing/geometry'
import { useAssetPicking } from '@/features/finishing/useAssetPicking'
import { FinishPreviewLayer, FinishSplitControl, FinishViewToggle } from '@/features/finishing/FinishingView'
import { useObjectUrl } from '@/features/finishing/useObjectUrl'
import { formatDateTime } from '@/lib/format'
import { useAssetSelectionStore } from '@/stores/useAssetSelectionStore'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { isDirty, useFinishingStore } from '@/stores/useFinishingStore'
import { CompareControls, ViewLabel, ZoomControls } from './CanvasControls'
import { GenerationStatus } from './GenerationStatus'
import { SourceLayer } from './SourceLayer'
import { useImageSize } from './useImageSize'
import { useStableSize } from './useStableSize'
import { useViewport } from './useViewport'
import { Viewport } from './Viewport'

const t = ko.studio.canvas
const tf = ko.studio.finishing

/** Center workspace: ① the source page, ② the selected flat render, or ③ the selected merge. */
export function MockupCanvas({ project, spec }: StudioRegionProps) {
  const pid = project.id
  const view = useCanvasStore((s) => s.view)
  const fullscreen = useCanvasStore((s) => s.fullscreen)
  const version = useShownVersion(pid)
  const imageUrl = view === 'source' ? null : (version?.image_url ?? null)
  const imageSize = useImageSize(imageUrl)
  // AI 재질 보정: the untouched original v3 render, laid over the left of the divider.
  const compareOn = useCanvasStore((s) => s.compare)
  const split = useCanvasStore((s) => s.split)
  const { flats } = useVersions(pid)
  const enhancement = view === 'flat' ? version?.enhancement : null
  // Only while the source render still exists (a deleted one has no image to compare with).
  const originalUrl =
    enhancement && flats.some((f) => f.id === enhancement.source_version_id) ? enhancement.source_image_url : null


  // 후가공 요소 선택: only on a finished flat render that knows where it sits on the page.
  const frame = view === 'flat' && version?.status === 'done' ? version.frame : null
  const pickable = !!frame && !!imageSize
  const assets = useAssets(pid, pickable)
  const selecting = useAssetSelectionStore((s) => s.selecting)
  const maskFrame = assets.data?.frame
  const geo = useMemo(
    () => (selecting && frame && imageSize && maskFrame ? pickGeometry(frame, imageSize, maskFrame) : null),
    [selecting, frame, imageSize, maskFrame],
  )
  const selectableIds = useMemo(
    () => new Set((assets.data?.assets ?? []).filter((a) => a.selectable).map((a) => a.id)),
    [assets.data],
  )
  const picking = useAssetPicking(pid, geo)

  // 후가공 보기 (원본 / 후가공 / 비교): the saved revision's preview over the render.
  const savedRevision = useFinishingStore((s) => (s.projectId === pid ? s.saved.revision : 0))
  const hasFinishes = useFinishingStore((s) => s.projectId === pid && s.saved.assignments.some((a) => a.enabled))
  const finishPending = useFinishingStore((s) => s.projectId === pid && (s.status === 'saving' || isDirty(s)))
  const finishView = useCanvasStore((s) => s.finishView)
  const finishable = !!frame && !!imageSize
  const finishOn = finishable && hasFinishes && finishView !== 'original'
  const preview = useFinishingPreview(pid, version?.id ?? null, savedRevision, finishOn)
  const previewUrl = useObjectUrl(finishOn ? preview.data?.blob : null)
  const finishCompare = finishOn && finishView === 'compare'
  // The AI 보정 divider only while the finishing preview is off (one comparison at a time).
  const comparing = !!originalUrl && compareOn && !finishOn
  const hovering = useAssetSelectionStore((s) => s.hover?.projectId === pid)

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
        ? (view === 'merge' ? t.labels.merge : version.enhancement ? t.labels.enhanced : t.labels.flat)(
            version.number,
            formatDateTime(version.created_at),
          )
        : ''
  const empty = view !== 'source' && !version

  return (
    <div ref={rootRef} className="absolute inset-0 flex bg-canvas">
      <div className="relative w-full">
        <Viewport
          vp={vp}
          cursor={geo ? (hovering ? 'pointer' : 'crosshair') : undefined}
          onWorldClick={geo ? picking.onWorldClick : undefined}
          onWorldMove={geo ? picking.onWorldMove : undefined}
          onWorldLeave={geo ? picking.onWorldLeave : undefined}
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
              {originalUrl && imageSize && !finishOn && <CompareControls />}
              {view === 'flat' && version && finishable && (
                <FinishViewToggle
                  available={hasFinishes}
                  loading={finishOn && (preview.isFetching || (!previewUrl && !preview.isError))}
                  stale={finishPending}
                  failed={finishOn && preview.isError}
                />
              )}
              {finishCompare && <FinishSplitControl />}
              {view === 'flat' && version && imageSize && (
                <SelectModeToggle
                  disabled={!frame || !!assets.error}
                  reason={!frame ? tf.noFrame : tf.modeUnavailable}
                />
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
              <>
                <img
                  src={imageUrl}
                  alt={(view === 'flat' ? t.alt.flat : t.alt.merge)(version.number)}
                  draggable={false}
                  className="absolute top-0 left-0 max-w-none select-none"
                  style={{ width: imageSize.w, height: imageSize.h }}
                />
                {comparing && (
                  <>
                    <img
                      src={originalUrl}
                      alt={t.alt.original}
                      draggable={false}
                      className="absolute top-0 left-0 max-w-none select-none"
                      style={{
                        width: imageSize.w,
                        height: imageSize.h,
                        clipPath: `inset(0 ${(1 - split) * 100}% 0 0)`,
                      }}
                    />
                    <div
                      aria-hidden
                      className="pointer-events-none absolute top-0 bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.4)]"
                      style={{ left: split * imageSize.w, height: imageSize.h, width: 2 / vp.zoom, marginLeft: -1 / vp.zoom }}
                    />
                  </>
                )}
                {finishOn && previewUrl && preview.data && (
                  <FinishPreviewLayer
                    url={previewUrl}
                    rect={preview.data.rect}
                    image={imageSize}
                    compare={finishCompare}
                    zoom={vp.zoom}
                  />
                )}
                {geo && <AssetOverlay projectId={pid} rect={geo.maskRect} valid={selectableIds} />}
              </>
            )
          )}
        </Viewport>
      </div>
      <GenerationStatus projectId={pid} />
    </div>
  )
}
