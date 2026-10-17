import { useShortcut } from '@/lib/shortcuts'
import { useAssetSelectionStore } from '@/stores/useAssetSelectionStore'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { useUiStore } from '@/stores/useUiStore'

/** Global Studio shortcuts. Canvas zoom/pan keys live in the Viewport. */
export function StudioShortcuts() {
  const c = useCanvasStore.getState
  // In ② selection mode "[" / "]" cycle overlapping elements instead.
  const onFlat = useCanvasStore((s) => s.view === 'flat')
  const selecting = useAssetSelectionStore((s) => s.selecting)
  const picking = onFlat && selecting
  useShortcut({ key: 'Digit1' }, () => c().setView('source'))
  useShortcut({ key: 'Digit2' }, () => c().setView('flat'))
  useShortcut({ key: 'Digit3' }, () => c().setView('merge'))
  useShortcut({ key: 'f' }, () => c().setFullscreen(!c().fullscreen))
  useShortcut({ key: '[' }, () => useUiStore.getState().toggleLeftPanel(), !picking)
  useShortcut({ key: 'h' }, () => useUiStore.getState().toggleHistory())
  return null
}
