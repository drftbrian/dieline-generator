import { create } from 'zustand'

export type ToastAction = { label: string; onClick: () => void }
export type Toast = {
  id: number
  message: string
  tone?: 'neutral' | 'success' | 'warning' | 'danger'
  actions?: ToastAction[]
  /** ms; 0 keeps it until dismissed */
  duration?: number
}

type State = {
  toasts: Toast[]
  push: (t: Omit<Toast, 'id'>) => number
  dismiss: (id: number) => void
}

let next = 1

export const useToastStore = create<State>()((set) => ({
  toasts: [],
  push: (t) => {
    const id = next++
    set((s) => ({ toasts: [...s.toasts, { duration: 5000, ...t, id }] }))
    return id
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export const toast = (t: Omit<Toast, 'id'>) => useToastStore.getState().push(t)
