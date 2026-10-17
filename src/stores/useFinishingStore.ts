import { temporal } from 'zundo'
import { create, useStore } from 'zustand'
import type { Assignment, FinishTarget, FinishingSpec } from '@/api/types'

// 후가공 지정 (Milestone 3): the working list of finish assignments of the open project.
// Only `assignments` is tracked by undo/redo (zundo); the last saved revision and the save
// status live beside it. useFinishingSync saves the working list ~600 ms after each change.

export type WorkingAssignment = Assignment & { id: string }

export type SaveStatus = 'loading' | 'saved' | 'saving' | 'error'

type State = {
  projectId: string | null
  assignments: WorkingAssignment[]
  /** What the server has: base_revision for the next save, and the state to revert to. */
  saved: { revision: number; assignments: WorkingAssignment[] }
  status: SaveStatus
  error: string | null
  /** Bumped by "다시 저장"; useFinishingSync saves when it changes. */
  retryTick: number
}

type Actions = {
  /** Replace everything with a server spec (no undo step; clears the history). */
  hydrate: (projectId: string, spec: FinishingSpec) => void
  add: (a: Omit<WorkingAssignment, 'order' | 'id'>) => string
  update: (id: string, patch: Partial<Pick<WorkingAssignment, 'params' | 'targets' | 'enabled'>>) => void
  remove: (id: string) => void
  /** Swap with the neighbour above (-1) or below (+1). */
  move: (id: string, dir: -1 | 1) => void
  setStatus: (status: SaveStatus, error?: string | null) => void
  /** A save went through; adopt the server's copy if nothing changed meanwhile. */
  savedAs: (spec: FinishingSpec, sent: WorkingAssignment[]) => void
  /** Back to the last saved state (after a 422). */
  revert: () => void
  retry: () => void
}

const randomHex = (n: number) =>
  Array.from(crypto.getRandomValues(new Uint8Array(Math.ceil(n / 2))), (b) => b.toString(16).padStart(2, '0'))
    .join('')
    .slice(0, n)

export const newAssignmentId = () => `fin_${randomHex(10)}`

const sorted = (list: WorkingAssignment[]) => [...list].sort((a, b) => a.order - b.order)

function fromServer(list: Assignment[]): WorkingAssignment[] {
  return sorted(list.map((a) => ({ ...a, id: a.id ?? newAssignmentId() })))
}

/** Stable JSON of what matters for saving (ignores timestamps and key order). */
export function canon(list: WorkingAssignment[]) {
  return JSON.stringify(
    sorted(list).map((a) => ({
      id: a.id,
      finish: a.finish,
      targets: a.targets.map((t) => [t.kind, t.id ?? null]),
      params: Object.keys(a.params)
        .sort()
        .map((k) => [k, a.params[k]]),
      order: a.order,
      enabled: a.enabled,
    })),
  )
}

/** The request body for one assignment. */
export function toPayload(a: WorkingAssignment): Assignment {
  return {
    id: a.id,
    finish: a.finish,
    targets: a.targets.map((t): FinishTarget => ({ kind: t.kind, id: t.id ?? null, range: null })),
    params: a.params,
    order: a.order,
    enabled: a.enabled,
  }
}

export const useFinishingStore = create<State & Actions>()(
  temporal(
    (set, get) => ({
      projectId: null,
      assignments: [],
      saved: { revision: 0, assignments: [] },
      status: 'loading',
      error: null,
      retryTick: 0,
      retry: () => set((s) => ({ retryTick: s.retryTick + 1 })),
      hydrate: (projectId, spec) => {
        const list = fromServer(spec.assignments)
        quietly(() =>
          set({
            projectId,
            assignments: list,
            saved: { revision: spec.revision, assignments: list },
            status: 'saved',
            error: null,
          }),
        )
        useFinishingStore.temporal.getState().clear()
      },
      add: (a) => {
        const id = newAssignmentId()
        const order = Math.max(-1, ...get().assignments.map((x) => x.order)) + 1
        set((s) => ({ assignments: [...s.assignments, { ...a, id, order }] }))
        return id
      },
      update: (id, patch) =>
        set((s) => ({ assignments: s.assignments.map((a) => (a.id === id ? { ...a, ...patch } : a)) })),
      remove: (id) => set((s) => ({ assignments: s.assignments.filter((a) => a.id !== id) })),
      move: (id, dir) =>
        set((s) => {
          const list = sorted(s.assignments)
          const i = list.findIndex((a) => a.id === id)
          const j = i + dir
          const a = list[i]
          const b = list[j]
          if (!a || !b) return s
          list[i] = { ...b, order: a.order }
          list[j] = { ...a, order: b.order }
          return { assignments: sorted(list) }
        }),
      setStatus: (status, error = null) => set({ status, error }),
      savedAs: (spec, sent) => {
        const list = fromServer(spec.assignments)
        const unchanged = get().assignments === sent
        quietly(() =>
          set({
            saved: { revision: spec.revision, assignments: list },
            // The server may have clamped params; show its copy unless the user moved on.
            ...(unchanged ? { assignments: list } : {}),
            status: 'saved',
            error: null,
          }),
        )
      },
      revert: () => quietly(() => set((s) => ({ assignments: s.saved.assignments, status: 'saved', error: null }))),
    }),
    {
      partialize: (s) => ({ assignments: s.assignments }),
      equality: (a, b) => a.assignments === b.assignments,
      limit: 100,
    },
  ),
)

/** Apply a change without recording an undo step. */
function quietly(fn: () => void) {
  const t = useFinishingStore.temporal.getState()
  const was = t.isTracking
  t.pause()
  fn()
  if (was) t.resume()
}

export const finishingUndo = () => useFinishingStore.temporal.getState().undo()
export const finishingRedo = () => useFinishingStore.temporal.getState().redo()

/** Can undo / redo right now (for the buttons). */
export function useFinishingHistory() {
  const past = useStore(useFinishingStore.temporal, (s) => s.pastStates.length)
  const future = useStore(useFinishingStore.temporal, (s) => s.futureStates.length)
  return { canUndo: past > 0, canRedo: future > 0 }
}

/** Unsaved changes in the working list. */
export const isDirty = (s: State) => canon(s.assignments) !== canon(s.saved.assignments)
