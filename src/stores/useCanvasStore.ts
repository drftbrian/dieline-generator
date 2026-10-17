import { create } from 'zustand'
import type { FinishLight } from '@/api/types'

/** The Studio's steps: ① 원본 → ② 플랫 렌더 → ③ 레퍼런스 합성. */
export type ViewMode = 'source' | 'flat' | 'merge'

/** ② 후가공 보기: the render as is, with the finishing preview laid over it, or split. */
export type FinishView = 'original' | 'finished' | 'compare'

type State = {
  view: ViewMode
  /** Version shown in the flat view (null: the latest finished one). */
  flatId: string | null
  /** Version shown in the merge view (null: the latest finished one). */
  mergeId: string | null
  /** Flat render picked as the source for the next merge (null: latest usable one). */
  mergeSourceId: string | null
  fullscreen: boolean
  /** Before/after overlay on an AI-enhanced flat: the original v3 render on the left of `split`. */
  compare: boolean
  /** Divider position of the before/after overlay, 0..1 of the image width. */
  split: number
  finishView: FinishView
  /** Divider of the 후가공 비교 view, 0..1 of the image width (original on the left). */
  finishSplit: number
  /** 후가공 미리보기 조명: light from above, or a low raking light that shows relief. */
  finishLight: FinishLight
  /** Last time the user zoomed/panned/switched view — decides whether a finished job takes over the canvas. */
  interactedAt: number
}

type Actions = {
  setView: (v: ViewMode) => void
  /** Show a version in the step it belongs to. */
  showVersion: (id: string, kind: 'flat' | 'merge') => void
  /** "이 버전으로 합성 →": use this flat render for ③ and switch there. */
  mergeWith: (flatId: string) => void
  setMergeSource: (id: string | null) => void
  /** Forget a deleted version wherever it was selected. */
  forget: (id: string) => void
  setFullscreen: (on: boolean) => void
  setCompare: (on: boolean) => void
  setSplit: (x: number) => void
  setFinishView: (v: FinishView) => void
  setFinishSplit: (x: number) => void
  setFinishLight: (l: FinishLight) => void
  touch: () => void
}

export const useCanvasStore = create<State & Actions>()((set) => ({
  view: 'source',
  flatId: null,
  mergeId: null,
  mergeSourceId: null,
  fullscreen: false,
  compare: true,
  split: 0.5,
  interactedAt: 0,
  finishView: 'original',
  finishSplit: 0.5,
  finishLight: 'top',
  setFinishLight: (finishLight) => set({ finishLight }),
  setFinishView: (finishView) => set({ finishView }),
  setFinishSplit: (x) => set({ finishSplit: Math.min(1, Math.max(0, x)) }),
  setView: (view) => set({ view, interactedAt: Date.now() }),
  showVersion: (id, kind) => set(kind === 'flat' ? { view: 'flat', flatId: id } : { view: 'merge', mergeId: id }),
  mergeWith: (flatId) => set({ view: 'merge', mergeSourceId: flatId, interactedAt: Date.now() }),
  setMergeSource: (mergeSourceId) => set({ mergeSourceId }),
  forget: (id) =>
    set((s) => ({
      flatId: s.flatId === id ? null : s.flatId,
      mergeId: s.mergeId === id ? null : s.mergeId,
      mergeSourceId: s.mergeSourceId === id ? null : s.mergeSourceId,
    })),
  setFullscreen: (fullscreen) => set({ fullscreen }),
  setCompare: (compare) => set({ compare }),
  setSplit: (split) => set({ split: Math.min(1, Math.max(0, split)) }),
  touch: () => set({ interactedAt: Date.now() }),
}))
