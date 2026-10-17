/**
 * Polygon drawing preview for a manual cut outline.
 * Points are in page points; the first point is enlarged as the "close" target.
 */
export function DrawLayer({
  points,
  cursor,
  width,
  height,
  zoom,
}: {
  points: [number, number][]
  cursor: { x: number; y: number } | null
  width: number
  height: number
  zoom: number
}) {
  const r = 4 / zoom
  const all = cursor && points.length ? [...points, [cursor.x, cursor.y] as [number, number]] : points
  return (
    <svg className="pointer-events-none absolute top-0 left-0 overflow-visible" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      {all.length > 1 && (
        <polyline
          points={all.map((p) => p.join(',')).join(' ')}
          fill="rgba(217,45,32,0.06)"
          stroke="#D92D20"
          strokeWidth={1.75}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {points.map((p, i) => (
        <circle
          key={i}
          cx={p[0]}
          cy={p[1]}
          r={i === 0 && points.length >= 3 ? r * 2 : r}
          fill={i === 0 ? '#D92D20' : 'white'}
          stroke="#D92D20"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  )
}
