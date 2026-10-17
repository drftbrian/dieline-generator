import { type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/**
 * Zoom/pan surface whose world coordinates are PDF page points (y down).
 * Every view (source PDF, flat mockup, enhanced mockup, overlays) is placed in the same
 * world, so switching views keeps the zoom and position.
 */

export const MIN_ZOOM = 0.1
export const MAX_ZOOM = 8

type Rect = [number, number, number, number]

export type ViewportApi = {
  containerRef: RefObject<HTMLDivElement | null>
  zoom: number
  pan: { x: number; y: number }
  world: { w: number; h: number } | null
  fit: () => void
  setZoom: (z: number, anchor?: { x: number; y: number }) => void
  panBy: (dx: number, dy: number) => void
  focus: (rect: Rect, padding?: number) => void
  /** Client (screen) coordinates -> world (page point) coordinates. */
  toWorld: (clientX: number, clientY: number) => { x: number; y: number }
  /** Did the user zoom/pan since the last fit? */
  touched: boolean
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function useViewport(world: { w: number; h: number } | null, onInteract?: () => void): ViewportApi {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [zoom, setZoomState] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [touched, setTouched] = useState(false)
  const interact = useRef(onInteract)
  useLayoutEffect(() => {
    interact.current = onInteract
  })

  const fitTo = useCallback((rect: Rect, padding: number) => {
    const el = containerRef.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const w = rect[2] - rect[0]
    const h = rect[3] - rect[1]
    if (w <= 0 || h <= 0 || width === 0) return
    const z = clamp(Math.min((width - padding * 2) / w, (height - padding * 2) / h), MIN_ZOOM, MAX_ZOOM)
    setZoomState(z)
    setPan({ x: (width - w * z) / 2 - rect[0] * z, y: (height - h * z) / 2 - rect[1] * z })
  }, [])

  const fit = useCallback(() => {
    if (!world) return
    fitTo([0, 0, world.w, world.h], 32)
    setTouched(false)
  }, [world, fitTo])

  // Fit on first layout and whenever the container resizes, until the user takes over.
  const worldKey = world ? `${world.w}x${world.h}` : ''
  useLayoutEffect(() => {
    if (world && !touched) fit()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [worldKey])
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => !touched && fit())
    ro.observe(el)
    return () => ro.disconnect()
  }, [fit, touched])

  const setZoom = useCallback(
    (z: number, anchor?: { x: number; y: number }) => {
      const el = containerRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const ax = anchor ? anchor.x - r.left : r.width / 2
      const ay = anchor ? anchor.y - r.top : r.height / 2
      setZoomState((old) => {
        const nz = clamp(z, MIN_ZOOM, MAX_ZOOM)
        setPan((p) => ({ x: ax - ((ax - p.x) / old) * nz, y: ay - ((ay - p.y) / old) * nz }))
        return nz
      })
      setTouched(true)
      interact.current?.()
    },
    [],
  )

  const panBy = useCallback((dx: number, dy: number) => {
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }))
    setTouched(true)
    interact.current?.()
  }, [])

  const focus = useCallback(
    (rect: Rect, padding = 80) => {
      fitTo(rect, padding)
      setTouched(true)
    },
    [fitTo],
  )

  const toWorld = useCallback(
    (clientX: number, clientY: number) => {
      const r = containerRef.current?.getBoundingClientRect()
      if (!r) return { x: 0, y: 0 }
      return { x: (clientX - r.left - pan.x) / zoom, y: (clientY - r.top - pan.y) / zoom }
    },
    [pan, zoom],
  )

  return { containerRef, zoom, pan, world, fit, setZoom, panBy, focus, toWorld, touched }
}
