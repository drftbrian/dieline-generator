import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

// Per-viewer layout preferences. Server data never goes here.
type UiState = {
  leftPanelCollapsed: boolean
  historyCollapsed: boolean
  toggleLeftPanel: () => void
  toggleHistory: () => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      leftPanelCollapsed: false,
      historyCollapsed: false,
      toggleLeftPanel: () => set((s) => ({ leftPanelCollapsed: !s.leftPanelCollapsed })),
      toggleHistory: () => set((s) => ({ historyCollapsed: !s.historyCollapsed })),
    }),
    { name: 'dieline-ui', storage: createJSONStorage(() => localStorage) },
  ),
)
