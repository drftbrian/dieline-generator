import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

// 후가공 대상 요소 선택 (② 플랫 렌더). The selected ids are remembered per project in
// localStorage; hover and the click-cycle state are session only.

/** Candidates under the last clicked point (innermost first) and which one is selected. */
export type Cycle = { key: string; candidates: string[]; index: number }

type State = {
  /** Selection mode on the canvas ("요소 선택"). */
  selecting: boolean
  /** Selected asset ids, per project. */
  selected: Record<string, string[]>
  /** Asset under the pointer (canvas) or under the mouse in the layer list. */
  hover: { projectId: string; id: string } | null
  cycle: Record<string, Cycle | undefined>
}

type Actions = {
  setSelecting: (on: boolean) => void
  /** Replace the selection with one asset (null: clear it). */
  select: (projectId: string, id: string | null) => void
  /** Replace the selection with these assets. */
  selectMany: (projectId: string, ids: string[]) => void
  /** Shift+click: add or remove one asset. */
  toggle: (projectId: string, id: string) => void
  remove: (projectId: string, id: string) => void
  clear: (projectId: string) => void
  setHover: (projectId: string, id: string | null) => void
  setCycle: (projectId: string, cycle: Cycle | undefined) => void
  /**
   * Move the cycle by `step` and swap the previously cycled asset for the new one,
   * keeping any other (Shift-) selected assets.
   */
  stepCycle: (projectId: string, step: number) => void
  /** Drop ids that no longer exist (or are no longer selectable). */
  prune: (projectId: string, valid: Set<string>) => void
}

const EMPTY: string[] = []

export const useAssetSelectionStore = create<State & Actions>()(
  persist(
    (set) => ({
      selecting: false,
      selected: {},
      hover: null,
      cycle: {},
      setSelecting: (selecting) => set(selecting ? { selecting } : { selecting, hover: null }),
      select: (pid, id) => set((s) => ({ selected: { ...s.selected, [pid]: id ? [id] : [] } })),
      selectMany: (pid, ids) =>
        set((s) => ({ selected: { ...s.selected, [pid]: [...new Set(ids)] }, cycle: { ...s.cycle, [pid]: undefined } })),
      toggle: (pid, id) =>
        set((s) => {
          const cur = s.selected[pid] ?? EMPTY
          return {
            selected: { ...s.selected, [pid]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] },
          }
        }),
      remove: (pid, id) =>
        set((s) => ({ selected: { ...s.selected, [pid]: (s.selected[pid] ?? EMPTY).filter((x) => x !== id) } })),
      clear: (pid) => set((s) => ({ selected: { ...s.selected, [pid]: [] }, cycle: { ...s.cycle, [pid]: undefined } })),
      setHover: (pid, id) =>
        set((s) => {
          const next = id ? { projectId: pid, id } : null
          if (s.hover?.projectId === next?.projectId && s.hover?.id === next?.id) return s
          return { hover: next }
        }),
      setCycle: (pid, cycle) => set((s) => ({ cycle: { ...s.cycle, [pid]: cycle } })),
      stepCycle: (pid, step) =>
        set((s) => {
          const c = s.cycle[pid]
          if (!c || c.candidates.length < 2) return s
          const n = c.candidates.length
          const index = (((c.index + step) % n) + n) % n
          const prev = c.candidates[c.index]
          const next = c.candidates[index]
          if (next === undefined) return s
          const cur = (s.selected[pid] ?? EMPTY).filter((x) => x !== prev && x !== next)
          return {
            selected: { ...s.selected, [pid]: [...cur, next] },
            cycle: { ...s.cycle, [pid]: { ...c, index } },
          }
        }),
      prune: (pid, valid) =>
        set((s) => {
          const cur = s.selected[pid] ?? EMPTY
          const kept = cur.filter((id) => valid.has(id))
          return kept.length === cur.length ? s : { selected: { ...s.selected, [pid]: kept } }
        }),
    }),
    {
      name: 'dieline-asset-selection',
      storage: createJSONStorage(() => localStorage),
      // Only the selection itself survives a reload; drop empty projects to keep storage small.
      partialize: (s) => ({
        selected: Object.fromEntries(Object.entries(s.selected).filter(([, ids]) => ids.length > 0)),
      }),
    },
  ),
)

/** Selected asset ids of one project (stable empty array when none). */
export function useSelectedAssets(projectId: string) {
  return useAssetSelectionStore((s) => s.selected[projectId] ?? EMPTY)
}
