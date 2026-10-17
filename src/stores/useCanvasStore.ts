import { create } from 'zustand'

/** The Studio's steps: ① 원본 → ② 플랫 렌더 → ③ 레퍼런스 합성. */
export type ViewMode = 'source' | 'flat' | 'merge'

type State = {
  view: ViewMode
  /** Version shown in the flat view (null: the latest finished one). */
  flatId: string | null
  /** Version shown in the merge view (null: the latest finished one). */
  mergeId: string | null
  /** Flat render picked as the source for the next merge (null: latest usable one). */
  mergeSourceId: string | null
  fullscreen: boolean
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
  touch: () => void
}

export const useCanvasStore = create<State & Actions>()((set) => ({
  view: 'source',
  flatId: null,
  mergeId: null,
  mergeSourceId: null,
  fullscreen: false,
  interactedAt: 0,
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
  touch: () => set({ interactedAt: Date.now() }),
}))
