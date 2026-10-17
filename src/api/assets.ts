import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from './client'
import { keys } from './keys'
import type { Asset, Assets, HitOut } from './types'

export type AssetKind = 'text' | 'vector' | 'group' | 'image'

/** Selectable design assets (logos, text, shapes) of a ready project, for finishing. */
export function useAssets(projectId: string, enabled = true) {
  return useQuery({
    queryKey: keys.assets(projectId),
    queryFn: () => api<Assets>(`/projects/${projectId}/assets`),
    enabled,
    // The tree only changes when the structure is re-confirmed.
    staleTime: 5 * 60_000,
    retry: (n, e) => !(e instanceof ApiError && e.status === 409) && n < 2,
  })
}

/** Transparent PNG of one asset's mask, exactly covering `Assets.frame` (page pt). */
export function assetMaskUrl(projectId: string, assetId: string, style: 'outline' | 'fill', color: string) {
  const q = new URLSearchParams({ style, color: color.replace('#', '') })
  return `/api/projects/${projectId}/assets/${encodeURIComponent(assetId)}/mask?${q}`
}

/** Selectable assets under a page point, innermost first. */
export async function hitAssets(projectId: string, x: number, y: number, signal?: AbortSignal) {
  const res = await api<HitOut>(`/projects/${projectId}/assets/hit`, { method: 'POST', json: { x, y }, signal })
  return res.candidates
}

/** What the finishing list shows for an asset: the text itself for text, else the layer name. */
// Figma's automatic layer names say nothing to a designer ("Union", "Vector 12", "Group 3").
const GENERIC_NAME = /^(Vector|Union|Group|Frame|Subtract|Intersect|Exclude|Rectangle|Ellipse|Line|Path|Polygon|Star)( \d+)?$/i

export function assetLabel(a: Asset) {
  const text = a.kind === 'text' ? a.text?.replace(/\s+/g, ' ').trim() : ''
  if (text) return text
  return GENERIC_NAME.test(a.name.trim()) ? (a.kind === 'group' ? '그룹' : '그래픽') : a.name
}
