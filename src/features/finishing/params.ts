import type { Finish, FinishParam, FinishTarget } from '@/api/types'

/** Every parameter of a finish at its default. */
export const defaultParams = (f: Finish): Record<string, number> =>
  Object.fromEntries(f.params.map((p) => [p.id, p.default]))

/** 100 steps across the range. */
export const paramStep = (p: FinishParam) => (p.max - p.min) / 100

const digits = (p: FinishParam) => Math.min(3, Math.max(0, Math.ceil(-Math.log10(paramStep(p)))))

export const formatParam = (p: FinishParam, v: number) => `${v.toFixed(digits(p))}${p.unit ? ` ${p.unit}` : ''}`

/** Snap to the slider grid so float noise does not create fake changes. */
export const snapParam = (p: FinishParam, v: number) => {
  const k = 10 ** digits(p)
  return Math.min(p.max, Math.max(p.min, Math.round(v * k) / k))
}

export type SurfaceChoice = { sheet: boolean; panels: string[] }

export const surfaceTargets = (c: SurfaceChoice): FinishTarget[] =>
  c.sheet ? [{ kind: 'sheet', id: null, range: null }] : c.panels.map((id) => ({ kind: 'panel', id, range: null }))

export const assetTargets = (ids: string[]): FinishTarget[] => ids.map((id) => ({ kind: 'asset', id, range: null }))

export const surfaceOf = (targets: FinishTarget[]): SurfaceChoice => ({
  sheet: targets.some((t) => t.kind === 'sheet'),
  panels: targets.filter((t) => t.kind === 'panel' && t.id).map((t) => t.id as string),
})

/** Same set of targets (order does not matter). */
export const sameTargets = (a: FinishTarget[], b: FinishTarget[]) => {
  const key = (l: FinishTarget[]) => l.map((t) => `${t.kind}:${t.id ?? ''}`).sort().join('|')
  return key(a) === key(b)
}
