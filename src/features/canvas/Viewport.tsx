import { type ReactNode, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { useShortcut } from '@/lib/shortcuts'
import type { ViewportApi } from './useViewport'

type ViewportProps = {
  vp: ViewportApi
  children: ReactNode
  /** Rendered above the world, not transformed (zoom controls, labels). */
  overlay?: ReactNode
  className?: string
  /** Register Cmd+/-, Shift+0, Shift+1 and arrow keys. */
  shortcuts?: boolean
  cursor?: string
  onWorldClick?: (p: { x: number; y: number }, e: React.MouseEvent) => void
  onWorldMove?: (p: { x: number; y: number }, e: React.MouseEvent) => void
}

export function Viewport({
  vp,
  children,
  overlay,
  className,
  shortcuts = true,
  cursor,
  onWorldClick,
  onWorldMove,
}: ViewportProps) {
  const [spaceDown, setSpaceDown] = useState(false)
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{ x: number; y: number } | null>(null)
  const { containerRef, world, pan, zoom } = vp

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.code === 'Space' && !['INPUT', 'TEXTAREA'].includes(t.tagName)) {
        setSpaceDown(true)
        if (t === document.body) e.preventDefault()
      }
    }
    const up = (e: KeyboardEvent) => e.code === 'Space' && setSpaceDown(false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

  // Native wheel listener: React's onWheel is passive and can't preventDefault page zoom.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) {
        vp.setZoom(vp.zoom * Math.exp(-e.deltaY * 0.01), { x: e.clientX, y: e.clientY })
      } else {
        vp.panBy(-e.deltaX, -e.deltaY)
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [vp, containerRef])

  useShortcut({ key: '=', mod: true }, () => vp.setZoom(vp.zoom * 1.25), shortcuts)
  useShortcut({ key: '+', mod: true, shift: true }, () => vp.setZoom(vp.zoom * 1.25), shortcuts)
  useShortcut({ key: '-', mod: true }, () => vp.setZoom(vp.zoom / 1.25), shortcuts)
  useShortcut({ key: 'Digit0', shift: true }, () => vp.fit(), shortcuts)
  useShortcut({ key: 'Digit1', shift: true }, () => vp.setZoom(1), shortcuts)
  useShortcut({ key: 'ArrowLeft' }, () => vp.panBy(60, 0), shortcuts)
  useShortcut({ key: 'ArrowRight' }, () => vp.panBy(-60, 0), shortcuts)
  useShortcut({ key: 'ArrowUp' }, () => vp.panBy(0, 60), shortcuts)
  useShortcut({ key: 'ArrowDown' }, () => vp.panBy(0, -60), shortcuts)

  const panning = spaceDown || dragging

  return (
    <div
      ref={containerRef}
      className={cn('relative h-full w-full touch-none overflow-hidden select-none', className)}
      style={{ cursor: panning ? 'grab' : cursor }}
      onPointerDown={(e) => {
        if (spaceDown || e.button === 1) {
          drag.current = { x: e.clientX, y: e.clientY }
          setDragging(true)
          e.currentTarget.setPointerCapture(e.pointerId)
        }
      }}
      onPointerMove={(e) => {
        if (drag.current) {
          vp.panBy(e.clientX - drag.current.x, e.clientY - drag.current.y)
          drag.current = { x: e.clientX, y: e.clientY }
        }
      }}
      onPointerUp={(e) => {
        if (drag.current) {
          e.currentTarget.releasePointerCapture(e.pointerId)
          drag.current = null
          setDragging(false)
        }
      }}
      onClick={(e) => !spaceDown && onWorldClick?.(vp.toWorld(e.clientX, e.clientY), e)}
      onMouseMove={(e) => onWorldMove?.(vp.toWorld(e.clientX, e.clientY), e)}
    >
      {world && (
        <div
          className="absolute top-0 left-0 origin-top-left"
          style={{
            width: world.w,
            height: world.h,
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          }}
        >
          {children}
        </div>
      )}
      {overlay}
    </div>
  )
}

/** Place a child at a page-space rectangle inside the Viewport world. */
export function WorldRect({
  rect,
  children,
  className,
  style,
}: {
  rect: { x: number; y: number; w: number; h: number }
  children?: ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div
      className={cn('absolute', className)}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, ...style }}
    >
      {children}
    </div>
  )
}
