import { create } from 'zustand'

// The AI 보정 prompt being written, per project. Session only (not persisted): it survives
// switching versions and failed starts, and is never cleared by the app.
type State = {
  drafts: Record<string, string>
  setDraft: (projectId: string, text: string) => void
}

export const useEnhanceDraftStore = create<State>()((set) => ({
  drafts: {},
  setDraft: (projectId, text) => set((s) => ({ drafts: { ...s.drafts, [projectId]: text } })),
}))

export function useEnhanceDraft(projectId: string) {
  const draft = useEnhanceDraftStore((s) => s.drafts[projectId] ?? '')
  const setDraft = useEnhanceDraftStore((s) => s.setDraft)
  return [draft, (text: string) => setDraft(projectId, text)] as const
}
