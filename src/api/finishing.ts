import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from './client'
import { keys } from './keys'
import type {
  Assignment,
  FinishCatalog,
  FinishingPreflight,
  FinishingSpec,
  FinishingWarnings,
  FinishLight,
} from './types'

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
  /** Transparent PNG of only the finished pixels, at the version image's own resolution. */
  blob: Blob
  /** Where it sits in the version image: x, y, w, h as fractions of the image's width/height. */
  rect: { x: number; y: number; w: number; h: number }
}

/** GET a binary finishing resource; JSON error bodies become ApiErrors like every other call. */
async function fetchBinary(path: string, signal: AbortSignal, fallback: string) {
  let res: Response
  try {
    res = await fetch(`/api${path}`, { signal })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, { code: 'NETWORK_ERROR', message: '서버에 연결할 수 없습니다.' })
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: { code: string; message: string } } | null
    throw new ApiError(res.status, body?.error ?? { code: `HTTP_${res.status}`, message: fallback })
  }
  return res
}

async function fetchPreview(
  projectId: string,
  versionId: string,
  revision: number,
  light: FinishLight,
  signal: AbortSignal,
) {
  const q = new URLSearchParams({ version_id: versionId, revision: String(revision), light })
  const res = await fetchBinary(`/projects/${projectId}/finishing/preview?${q}`, signal, '미리보기를 만들지 못했습니다.')
  const px = (res.headers.get('X-Overlay-Rect') ?? '').split(',').map(Number)
  const [x = NaN, y = NaN, w = NaN, h = NaN, iw = NaN, ih = NaN] = px
  if (px.length !== 6 || !px.every(Number.isFinite) || iw <= 0 || ih <= 0)
    throw new ApiError(500, { code: 'PREVIEW_FRAME', message: '미리보기 위치 정보가 없습니다.' })
  const rect = { x: x / iw, y: y / ih, w: w / iw, h: h / ih }
  return { blob: await res.blob(), rect } satisfies FinishingPreview
}

/** Overlay of a flat version's finished pixels for a saved finishing revision, under the chosen light. */
export function useFinishingPreview(
  projectId: string,
  versionId: string | null,
  revision: number,
  light: FinishLight,
  enabled: boolean,
) {
  return useQuery({
    queryKey: keys.finishingPreview(projectId, versionId ?? '', revision, light),
    queryFn: ({ signal }) => fetchPreview(projectId, versionId ?? '', revision, light, signal),
    enabled: enabled && !!versionId && revision > 0,
    staleTime: Infinity,
    gcTime: 60_000,
    retry: 1,
    // Keep showing the previous revision/light of the same version while the new one renders.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === versionId ? prev : undefined),
  })
}

/** 빛 움직여 보기: an animated GIF of only the finished area with the light moving across it (5–30 s). */
export function useFinishingSweep(
  projectId: string,
  versionId: string | null,
  revision: number,
  light: FinishLight,
  enabled: boolean,
) {
  return useQuery({
    queryKey: keys.finishingSweep(projectId, versionId ?? '', revision, light),
    queryFn: async ({ signal }) => {
      const q = new URLSearchParams({ version_id: versionId ?? '', revision: String(revision), light })
      const res = await fetchBinary(`/projects/${projectId}/finishing/sweep?${q}`, signal, '빛 움직임을 만들지 못했습니다.')
      return res.blob()
    },
    enabled: enabled && !!versionId && revision > 0,
    staleTime: Infinity,
    gcTime: 5 * 60_000,
    retry: false,
  })
}

/** 제조 점검: manufacturing checks for a saved finishing revision. */
export function useFinishingWarnings(projectId: string, revision: number, enabled = true) {
  return useQuery({
    queryKey: keys.finishingWarnings(projectId, revision),
    queryFn: () => api<FinishingWarnings>(`/projects/${projectId}/finishing/warnings?revision=${revision}`),
    enabled: enabled && revision > 0,
    staleTime: Infinity,
    retry: 1,
  })
}

/** Can a revision's plates be exported for production (every target exact source geometry)? */
export function useFinishingPreflight(projectId: string, revision: number, enabled = true) {
  return useQuery({
    queryKey: keys.finishingPreflight(projectId, revision),
    queryFn: () => api<FinishingPreflight>(`/projects/${projectId}/finishing/preflight?revision=${revision}`),
    enabled: enabled && revision > 0,
    staleTime: Infinity,
    retry: 1,
  })
}

/** Download URL of the finishing plates (one vector PDF per finish + JSON) for a saved revision.
 * `draft`: the export for review when the preflight found approximate or missing geometry
 * (every file is marked DRAFT / not for production; a production export is refused then). */
export const finishingPlatesUrl = (projectId: string, revision: number, draft = false) =>
  `/api/projects/${projectId}/finishing/plates?revision=${revision}${draft ? '&draft=true' : ''}`
