import type { PathClass, StructuralPath } from '@/api/types'
import { ko } from '@/i18n/ko'

/**
 * Overlay styles: every class differs by line style *and* label,
 * never by color alone. Widths are screen pixels (non-scaling strokes).
 */
export type OverlayKind = PathClass | 'unresolved'

export const PATH_STYLE: Record<OverlayKind, { stroke: string; width: number; dash?: string; opacity?: number }> = {
  cut: { stroke: '#D92D20', width: 1.75 },
  crease: { stroke: '#2563EB', width: 1.5, dash: '6 4' },
  annotation: { stroke: '#6B6862', width: 1.25, dash: '1.5 3' },
  finish: { stroke: '#0891B2', width: 1.5, dash: '8 3 2 3' },
  bleed: { stroke: '#9CA3AF', width: 1, dash: '2 2' },
  artwork: { stroke: '#8A877F', width: 1, opacity: 0.55 },
  unresolved: { stroke: '#F97316', width: 2.75 },
}

export const overlayKind = (p: StructuralPath): OverlayKind => (p.status === 'unresolved' ? 'unresolved' : p.cls)

export const pathLabel = (p: StructuralPath) => `#${p.id.replace(/^p/, '')}`

export const CLASS_KEYS: { cls: PathClass; key: string }[] = [
  { cls: 'cut', key: 'c' },
  { cls: 'crease', key: 'f' },
  { cls: 'artwork', key: 'a' },
  { cls: 'annotation', key: 'n' },
]

export const clsLabel = (c: PathClass) => ko.review.cls[c]

/** Expand degenerate (line) bboxes so focusing on them doesn't zoom to infinity. */
export function focusBox(b: [number, number, number, number], min = 60): [number, number, number, number] {
  const cx = (b[0] + b[2]) / 2
  const cy = (b[1] + b[3]) / 2
  const w = Math.max(min, b[2] - b[0])
  const h = Math.max(min, b[3] - b[1])
  return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
}
