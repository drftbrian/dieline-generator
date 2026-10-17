export const formatKRW = (n: number) => `₩${n.toLocaleString('ko-KR')}`

export const formatMB = (bytes: number) => `${(bytes / (1024 * 1024)).toFixed(1)}`

/** Human file size: KB below 1 MB so small files don't read as "0.0 MB". */
export const formatSize = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${formatMB(bytes)} MB`

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return '방금'
  if (s < 3600) return `${Math.floor(s / 60)}분 전`
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`
  return `${Math.floor(s / 86400)}일 전`
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/** Polylines in page points -> SVG path data. */
export function polylinesToD(polylines: [number, number][][], closed: boolean[] = []): string {
  return polylines
    .map((pl, i) => {
      if (pl.length === 0) return ''
      const [first, ...rest] = pl
      const d = `M${first![0]},${first![1]}` + rest.map(([x, y]) => `L${x},${y}`).join('')
      return closed[i] ? `${d}Z` : d
    })
    .join('')
}
