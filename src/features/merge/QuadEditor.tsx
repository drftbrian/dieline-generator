import { useLayoutEffect, useRef } from 'react'
import type { Point } from '@/api/scene'
import { cn } from '@/lib/cn'

export type EditableQuad = {
  id: string
  label: string
  /** Four corners as fractions of the image; at most one may be hidden (null). */
  quad: (Point | null)[]
  dim?: boolean
}

/** The hidden corner of a quad, shown where the parallelogram puts it (the server computes the
 *  exact one in 3D from the ground plane). */
function displayQuad(q: (Point | null)[]): Point[] {
  const k = q.findIndex((c) => c === null)
  if (k < 0) return q as Point[]
  const a = q[(k + 1) % 4] as Point
  const b = q[(k + 2) % 4] as Point
  const c = q[(k + 3) % 4] as Point
  const out = [...q] as Point[]
  out[k] = [a[0] + c[0] - b[0], a[1] + c[1] - b[1]]
  return out
}

/** Drag the corners of one or more quads on a photo. */
export function QuadEditor({
  imageUrl,
  aspect,
  quads,
  onChange,
}: {
  imageUrl: string
  aspect: number
  quads: EditableQuad[]
  /** A corner moved: every quad (``commit`` when the drag ends). */
  onChange: (quads: EditableQuad[], commit: boolean) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<{ i: number; c: number } | null>(null)
  const listRef = useRef(quads)
  useLayoutEffect(() => {
    listRef.current = quads
  })
  const move = (e: React.PointerEvent, commit: boolean) => {
    const d = drag.current
    const el = box.current
    if (!d || !el) return
    const r = el.getBoundingClientRect()
    const p: Point = [
      Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    ]
    const list = listRef.current.map((q, i) =>
      i === d.i ? { ...q, quad: q.quad.map((c, j) => (j === d.c ? p : c)) } : q,
    )
    onChange(list, commit)
  }
  return (
    <div
      ref={box}
      className="relative w-full touch-none overflow-hidden rounded border border-line"
      style={{ aspectRatio: String(aspect) }}
      onPointerMove={(e) => move(e, false)}
      onPointerUp={(e) => {
        move(e, true)
        drag.current = null
      }}
    >
      <img src={imageUrl} alt="" className="absolute inset-0 h-full w-full object-fill" draggable={false} />
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        {quads.map((item) => {
          const q = displayQuad(item.quad)
          return (
            <g key={item.id} opacity={item.dim ? 0.35 : 1}>
              <polygon
                points={q.map((p) => p.join(',')).join(' ')}
                fill="rgba(229,51,63,0.12)"
                stroke="#e5333f"
                strokeWidth={0.004}
              />
              <text x={q[0]?.[0] ?? 0} y={(q[0]?.[1] ?? 0) - 0.01} fontSize={0.035} fill="#e5333f">
                {item.label}
              </text>
            </g>
          )
        })}
      </svg>
      {quads.map((item, i) =>
        displayQuad(item.quad).map((p, c) => (
          <button
            key={`${item.id}-${c}`}
            type="button"
            aria-label={`${item.label} ${c + 1}`}
            onPointerDown={(e) => {
              ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
              drag.current = { i, c }
            }}
            className={cn(
              'absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow',
              item.quad[c] === null ? 'bg-white/70 outline-dashed outline-1 outline-red-600' : 'bg-red-600',
            )}
            style={{ left: `${p[0] * 100}%`, top: `${p[1] * 100}%` }}
          />
        )),
      )}
    </div>
  )
}
