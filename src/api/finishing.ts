import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from './client'
import { keys } from './keys'
import type { Assignment, FinishCatalog, FinishingSpec } from './types'

/** Finish types (박, 형압, 코팅 …) with their adjustable parameters. Static per server build. */
export function useFinishingCatalog() {
  return useQuery({
    queryKey: keys.finishingCatalog,
    queryFn: () => api<FinishCatalog>('/finishing/catalog'),
    staleTime: Infinity,
  })
}

export const fetchFinishing = (projectId: string) => api<FinishingSpec>(`/projects/${projectId}/finishing`)

/** The saved finishing specification. The working copy lives in useFinishingStore. */
export function useFinishingSpec(projectId: string) {
  return useQuery({
    queryKey: keys.finishing(projectId),
    queryFn: () => fetchFinishing(projectId),
    staleTime: Infinity,
  })
}

/** Save the whole list as a new revision; 409 FINISHING_CONFLICT when `baseRevision` is stale. */
export function saveFinishing(projectId: string, baseRevision: number, assignments: Assignment[]) {
  return api<FinishingSpec>(`/projects/${projectId}/finishing`, {
    method: 'PUT',
    json: { base_revision: baseRevision, assignments },
  })
}

export type FinishingPreview = {
  blob: Blob
  /** Page-pt frame the PNG covers (same frame as the asset masks). */
  frame: { origin: [number, number]; size: [number, number] }
}

const pair = (h: string | null): [number, number] | null => {
  const [a, b] = (h ?? '').split(',').map(Number)
  return a !== undefined && b !== undefined && Number.isFinite(a) && Number.isFinite(b) ? [a, b] : null
}

async function fetchPreview(projectId: string, versionId: string, revision: number, signal: AbortSignal) {
  const q = new URLSearchParams({ version_id: versionId, revision: String(revision) })
  let res: Response
  try {
    res = await fetch(`/api/projects/${projectId}/finishing/preview?${q}`, { signal })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, { code: 'NETWORK_ERROR', message: '서버에 연결할 수 없습니다.' })
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: { code: string; message: string } } | null
    throw new ApiError(res.status, body?.error ?? { code: `HTTP_${res.status}`, message: '미리보기를 만들지 못했습니다.' })
  }
  const origin = pair(res.headers.get('X-Frame-Origin'))
  const size = pair(res.headers.get('X-Frame-Size'))
  if (!origin || !size) throw new ApiError(500, { code: 'PREVIEW_FRAME', message: '미리보기 위치 정보가 없습니다.' })
  return { blob: await res.blob(), frame: { origin, size } } satisfies FinishingPreview
}

/** PNG of a flat version with a saved finishing revision applied (placeholder effects for now). */
export function useFinishingPreview(projectId: string, versionId: string | null, revision: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.finishingPreview(projectId, versionId ?? '', revision),
    queryFn: ({ signal }) => fetchPreview(projectId, versionId ?? '', revision, signal),
    enabled: enabled && !!versionId && revision > 0,
    staleTime: Infinity,
    gcTime: 60_000,
    retry: 1,
    // Keep showing the previous revision of the same version while the new one renders.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === versionId ? prev : undefined),
  })
}
