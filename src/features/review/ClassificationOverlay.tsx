import type { StructuralPath } from '@/api/types'
import { polylinesToD } from '@/lib/format'
import { overlayKind, PATH_STYLE, pathLabel } from './pathStyles'

/**
 * Classification overlay drawn over the PDF in page points. Each path gets a
 * wide invisible hit stroke so thin lines stay clickable at any zoom.
 */
export function ClassificationOverlay({
  paths,
  width,
  height,
  zoom,
  selectedId,
  hoveredId,
  interactive,
  onPathClick,
  onHover,
}: {
  paths: StructuralPath[]
  width: number
  height: number
  zoom: number
  selectedId: string | null
  hoveredId: string | null
  interactive: boolean
  onPathClick: (id: string, client: { x: number; y: number }) => void
  onHover: (id: string | null) => void
}) {
  // Draw unresolved and selected last so they sit on top.
  const ordered = [...paths].sort((a, b) => rank(a, selectedId) - rank(b, selectedId))
  const fontSize = 11 / zoom
  return (
    <svg
      className="absolute top-0 left-0 overflow-visible"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
    >
      {ordered.map((p) => {
        const kind = overlayKind(p)
        const st = PATH_STYLE[kind]
        const d = polylinesToD(p.polylines as [number, number][][], p.closed)
        const active = p.id === selectedId || p.id === hoveredId
        return (
          <g key={p.id}>
            {active && (
              <path
                d={d}
                fill="none"
                stroke="#2F5BD3"
                strokeOpacity={0.25}
                strokeWidth={st.width + 6}
                vectorEffect="non-scaling-stroke"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}
            <path
              d={d}
              fill="none"
              stroke={st.stroke}
              strokeWidth={active ? st.width + 1 : st.width}
              strokeDasharray={st.dash}
              strokeOpacity={st.opacity ?? 1}
              vectorEffect="non-scaling-stroke"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={kind === 'unresolved' ? 'motion-safe:animate-pulse' : undefined}
            />
            {interactive && (
              <path
                d={d}
                fill="none"
                stroke="transparent"
                strokeWidth={12}
                vectorEffect="non-scaling-stroke"
                style={{ cursor: 'pointer', pointerEvents: 'stroke' }}
                onMouseEnter={() => onHover(p.id)}
                onMouseLeave={() => onHover(null)}
                onClick={(e) => {
                  e.stopPropagation()
                  onPathClick(p.id, { x: e.clientX, y: e.clientY })
                }}
              />
            )}
            {kind === 'unresolved' && (
              <text
                x={p.bbox[0]}
                y={p.bbox[1] - fontSize * 0.4}
                fontSize={fontSize}
                fontWeight={600}
                fill="#C2410C"
                stroke="white"
                strokeWidth={fontSize * 0.25}
                paintOrder="stroke"
                style={{ pointerEvents: 'none' }}
              >
                {pathLabel(p)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function rank(p: StructuralPath, selectedId: string | null) {
  if (p.id === selectedId) return 3
  if (p.status === 'unresolved') return 2
  if (p.cls === 'cut') return 1
  return 0
}
