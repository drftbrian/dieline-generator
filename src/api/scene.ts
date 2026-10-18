import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from './client'
import { keys } from './keys'
import type { ComposeIn, GenerateOut } from './types'

// ③ 구조 합성 (structural composition): our folded carton in place of each package of a reference.

export type Point = [number, number]

/** One package of the reference: the four corners of its most visible face (fractions of the
 *  image; at most one hidden corner = null), its height for removal, and how ours sits on it. */
export type SceneInstance = {
  id: string
  quad: (Point | null)[]
  height: number
  enabled: boolean
  confidence?: number
  our_face?: string
  yaw_deg: number
  offset: [number, number]
}

export type SceneSettings = {
  size?: number
  shadow_strength?: number
  key_azimuth?: number | null
  key_elevation?: number | null
}

export type Scene = {
  source: string | null
  instances: SceneInstance[]
  settings: SceneSettings
}

export type StructureInfo = {
  ok: boolean
  carton: {
    family: string | null
    style: string | null
    supported: boolean
    reasons: string[]
    body?: { W_mm: number; D_mm: number; H_mm: number }
  }
  issues: { level: string; code: string; message: string }[]
}

export function useStructure(projectId: string) {
  return useQuery({
    queryKey: ['structure', projectId],
    queryFn: () => api<StructureInfo>(`/projects/${projectId}/structure`),
    staleTime: 60_000,
    retry: false,
  })
}

const sceneKey = (pid: string, rid: string) => ['scene', pid, rid] as const

export function useScene(projectId: string, referenceId: string | null) {
  return useQuery({
    queryKey: sceneKey(projectId, referenceId ?? ''),
    queryFn: () => api<Scene>(`/projects/${projectId}/references/${referenceId}/scene`),
    enabled: !!referenceId,
    staleTime: Infinity,
  })
}

export function useSaveScene(projectId: string, referenceId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (scene: Pick<Scene, 'instances' | 'settings'>) =>
      api<Scene>(`/projects/${projectId}/references/${referenceId}/scene`, {
        method: 'PUT',
        json: scene,
      }),
    onSuccess: (s) => qc.setQueryData(sceneKey(projectId, referenceId ?? ''), s),
  })
}

export function useDetectScene(projectId: string, referenceId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<Scene>(`/projects/${projectId}/references/${referenceId}/scene/detect`, { method: 'POST' }),
    onSuccess: (s) => qc.setQueryData(sceneKey(projectId, referenceId ?? ''), s),
  })
}

export type ComposeReport = {
  match?: boolean
  instances?: number
  lens_mm_35eq?: number
  ambient?: number
  light?: {
    azimuth: number
    elevation: number
    estimated?: { azimuth_source?: string } | null
  }
  reference_print_leak?: number
}

export type ComposeLayer = 'final' | 'placement' | 'removal_mask' | 'background' | 'albedo' | 'lighting' | 'shadow_only'

/** The deterministic composition (no AI) or one of its layers, at preview size. */
export async function fetchComposePreview(projectId: string, referenceId: string, flatId: string, layer: ComposeLayer) {
  const q = new URLSearchParams({
    reference_id: referenceId,
    flat_version_id: flatId,
    layer,
  })
  const res = await fetch(`/api/projects/${projectId}/compose/preview?${q}`)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.error ?? { code: 'HTTP_ERROR', message: res.statusText })
  }
  const report = JSON.parse(res.headers.get('X-Compose-Report') ?? '{}') as ComposeReport
  return { blob: await res.blob(), report }
}

export function useStartCompose(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ComposeIn) =>
      api<GenerateOut>(`/projects/${projectId}/compose`, {
        method: 'POST',
        json: body,
        idempotent: true,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.history(projectId) }),
  })
}
